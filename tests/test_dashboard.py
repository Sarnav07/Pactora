"""Private dashboard, durable decisions and signing controls."""

import importlib.util
from pathlib import Path

import pytest
from conftest import new_job

from pactora.crypto import PrivateStoreCipher
from pactora.store import Store


async def approved(client, gateway, private, device):
    search = await new_job(client, gateway)
    draft = (
        await client.post(
            "/internal/mandates",
            headers=gateway,
            json={
                "search_ref": search,
                "per_purchase_cents": 250,
                "total_cents": 500,
                "per_purchase_zat": 300000,
                "total_zat": 600000,
                "max_purchases": 2,
                "duration_seconds": 3600,
            },
        )
    ).json()
    ref = draft["reference"]
    view = (await client.get("/api/mandates")).json()[0]
    response = await client.post(
        f"/api/mandates/{ref}/approve",
        headers=private,
        json={
            "draft_hash": view["draft_hash"],
            "device_public_key": device[1],
        },
    )
    assert response.status_code == 200
    return ref, {"search_ref": search, "option": 0, "purchase_ref": "one"}


async def test_private_endpoints_and_routes(client, gateway, private):
    for path in ("/api/dashboard", "/api/wallet"):
        # Gateway bearer alone cannot authenticate a browser view.
        client.cookies.clear()
        assert (await client.get(path, headers=gateway)).status_code == 401
    for path in ("/", "/setup", "/app", "/app/live", "/app/wallet", "/app/settings"):
        response = await client.get(path)
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
    assert (await client.get("/static/mark.svg")).status_code == 200
    assert (await client.get("/static/../wallet_cli.py")).status_code == 404


async def test_decisions_deduplicate_hide_secrets_and_persist(
    client, app, settings, gateway, private, device, provider
):
    ref, body = await approved(client, gateway, private, device)
    endpoint = f"/internal/mandates/{ref}/purchase"
    first = await client.post(endpoint, headers=gateway, json=body)
    again = await client.post(endpoint, headers=gateway, json=body)
    assert first.json() == again.json()
    assert provider.executions == 1
    dashboard = (await client.get("/api/dashboard")).json()
    assert len(dashboard["decisions"]) == 1
    assert dashboard["decisions"][0]["state"] == "completed"
    intent = dashboard["intents"][0]
    assert intent["usage"]["count"] == 1
    assert not {"signature", "device_key", "recovery", "pending", "delivered"} & intent.keys()
    # A rejected changed selection is its own decision, never another payment.
    refused = await client.post(endpoint, headers=gateway, json={**body, "option": 1})
    assert refused.status_code == 409
    assert refused.json() == {"error": "requires_private_attention"}
    decisions = (await client.get("/api/dashboard")).json()["decisions"]
    assert len(decisions) == 2 and provider.executions == 1
    assert any(d["state"] == "refused" for d in decisions)
    assert "SIM-CODE" not in str(decisions)
    assert "SIM-CODE" not in "\n".join(app.state.engine.store.db.iterdump())
    restored = Store(settings.data_dir, PrivateStoreCipher(settings.master_key))
    try:
        assert restored.decisions() == decisions
    finally:
        restored.db.close()


async def test_pause_resume_durable_and_no_mcp_controls(
    client, app, gateway, private, device, provider, settings
):
    ref, body = await approved(client, gateway, private, device)
    assert (
        await client.post("/api/control", headers={"Origin": settings.origin}, json={"paused": True})
    ).status_code == 403
    assert (await client.post("/api/control", headers=private, json={"paused": True})).json() == {
        "paused": True
    }
    result = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=body)
    assert result.status_code == 409 and provider.executions == 0
    restored = Store(settings.data_dir, PrivateStoreCipher(settings.master_key))
    assert restored.paused()
    restored.db.close()
    assert (await client.post("/api/control", headers=private, json={"paused": False})).status_code == 200
    result = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=body)
    assert result.json()["status"] == "completed" and provider.executions == 1
    assert (await client.get("/api/wallet")).json()["connected"] is False


async def test_failed_wallet_pause_is_locally_fail_closed(client, app, private):
    class Unavailable:
        async def call(self, *args, **kwargs):
            from pactora.engine import Refused

            raise Refused("wallet_bridge_unavailable")

    app.state.mandates.wallet = Unavailable()
    result = await client.post("/api/control", headers=private, json={"paused": True})
    assert result.status_code == 409
    assert app.state.engine.store.paused()


async def test_readiness_retries_reads_only_and_times_out(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "regtest_rpc", Path(__file__).parents[1] / "tools/proofs/regtest_rpc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def disconnected(method, *, timeout):
        calls.append((method, timeout))
        raise OSError("not ready")

    with pytest.raises(RuntimeError, match="not ready"):
        await module.wait_for_node(0, request=disconnected)
    assert calls == [("getblockcount", 2)]

    class Writer:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def connect(*args):
        return None, Writer()

    monkeypatch.setattr(module.asyncio, "open_connection", connect)
    assert await module.wait_for_node(1, request=lambda *args, **kwargs: 310) == 310


async def test_delivery_view_exposes_status_without_payment_envelope(client, gateway, private, device):
    ref, body = await approved(client, gateway, private, device)
    assert (
        await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=body)
    ).status_code == 200
    intent = (await client.get("/api/dashboard")).json()["intents"][0]
    delivery = next(iter(intent["deliveries"].values()))
    assert delivery["fulfillment"] == "simulator_issued"
    assert delivery["receipt"]["ciphertext"]
    assert not {"quote", "invoice", "operation"} & delivery.keys()
    assert set(delivery["expected"]) == {"product"}
    assert "SIM-CODE" not in str(delivery)
