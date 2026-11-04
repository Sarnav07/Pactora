import copy
import time
from types import SimpleNamespace

import pytest
from test_mandates import approved

from pactora.app import create_app
from pactora.engine import Refused
from pactora.mandate_commerce import MandateApproval


async def buy(client, gateway, ref, search, purchase="one"):
    return await client.post(
        f"/internal/mandates/{ref}/purchase",
        headers=gateway,
        json={"search_ref": search, "option": 0, "purchase_ref": purchase},
    )


@pytest.mark.parametrize(
    "mutation", ["missing", "invalid", "product", "invoice", "environment", "amount", "operation"]
)
async def test_unverified_deliverable_never_completes(
    client, gateway, private, device, provider, app, monkeypatch, mutation
):
    ref, search = await approved(client, gateway, private, device)
    original = provider.execute

    async def bad_result(quote, operation):
        result = await original(quote, operation)
        if mutation == "missing":
            result.pop("code")
        elif mutation == "invalid":
            result["code"] = {"url": "https://untrusted.invalid"}
        elif mutation == "product":
            result["product"]["country"] = "GB"
        elif mutation == "invoice":
            result["invoice"] = "wrong-invoice"
        elif mutation == "environment":
            result["simulated"] = False
        elif mutation == "amount":
            result["total_cents"] += 1
        else:
            result["transaction"] = "wrong-operation"
        return result

    monkeypatch.setattr(provider, "execute", bad_result)
    response = await buy(client, gateway, ref, search)
    assert response.status_code == 200
    assert response.json()["status"] == "requires_private_attention"
    assert provider.executions == 1
    value = app.state.mandates.view(ref)
    assert value["receipts"] == []
    assert len(value["recovery"]) == 1
    delivery = next(iter(value["deliveries"].values()))
    assert delivery["fulfillment"] == ("pending" if mutation == "missing" else "private_attention")
    assert delivery["private_delivery"] == "not_stored"
    assert (await buy(client, gateway, ref, search)).json() == response.json()
    assert provider.executions == 1


async def test_late_delivery_recovers_after_restart_without_checkout(
    client, gateway, private, device, provider, app, settings, monkeypatch
):
    ref, search = await approved(client, gateway, private, device)
    original = provider.execute
    issued = []

    async def delayed(quote, operation):
        result = await original(quote, operation)
        issued.append(copy.deepcopy(result))
        result.pop("code")
        return result

    monkeypatch.setattr(provider, "execute", delayed)
    response = await buy(client, gateway, ref, search)
    assert response.json()["status"] == "requires_private_attention"
    app.state.mandates.book.close()
    replacement = create_app(settings, provider, run_worker=False)
    commerce = replacement.state.mandates
    reads = []

    async def reconcile(quote, operation):
        reads.append(operation)
        assert quote.invoice_id == issued[0]["invoice"]
        return issued[0]

    monkeypatch.setattr(provider, "reconcile", reconcile)
    try:
        await commerce.tick()
        await commerce.tick()
        value = commerce.view(ref)
        assert len(value["receipts"]) == 1 and value["recovery"] == {}
        assert len(reads) == 1 and provider.executions == 1
        assert next(iter(value["deliveries"].values()))["private_delivery"] == "encrypted_stored"
        assert commerce.book.operation_status(response.json()["reference"])["status"] == "completed"
    finally:
        commerce.book.close()
        replacement.state.engine.store.db.close()


async def test_polling_backoff_timeout_and_reservation_retained(
    client, gateway, private, device, provider, app, monkeypatch
):
    ref, search = await approved(client, gateway, private, device)
    original = provider.execute

    async def delayed(quote, operation):
        result = await original(quote, operation)
        result.pop("code")
        return result

    calls = []

    async def unavailable(*args):
        calls.append(True)
        raise TimeoutError("private provider details")

    monkeypatch.setattr(provider, "execute", delayed)
    monkeypatch.setattr(provider, "reconcile", unavailable)
    await buy(client, gateway, ref, search)
    commerce = app.state.mandates
    await commerce.tick()
    await commerce.tick()
    assert len(calls) == 1
    value = commerce.view(ref)
    delivery = next(iter(value["deliveries"].values()))
    assert delivery["next_poll"] > time.time()
    delivery.update(deadline=int(time.time()) - 1, next_poll=0)
    commerce._save(ref, value)
    await commerce.tick()
    await commerce.tick()
    value = commerce.view(ref)
    assert next(iter(value["deliveries"].values()))["fulfillment"] == "private_attention"
    assert len(calls) == 1 and provider.executions == 1
    assert commerce.book._get("mandates", ref)["count"] == 1
    assert commerce.book._get("mandates", ref)["cents"] == 210


async def test_device_ack_issue_and_model_redaction(client, gateway, private, device, provider, app):
    ref, search = await approved(client, gateway, private, device)
    response = await buy(client, gateway, ref, search)
    value = app.state.mandates.view(ref)
    purchase = next(iter(value["deliveries"]))
    path = f"/api/mandates/{ref}/deliveries/{purchase}/action"
    assert (await client.post(path, headers=private, json={"action": "acknowledged"})).status_code == 409
    for action in ("accessible", "acknowledged", "invalid"):
        assert (await client.post(path, headers=private, json={"action": action})).status_code == 200
    await app.state.mandates.tick()
    value = app.state.mandates.view(ref)
    delivery = value["deliveries"][purchase]
    assert delivery["private_delivery"] == "acknowledged"
    assert delivery["refund"] == "operator_review_required"
    assert delivery["issue"]["reason"] == "invalid"
    public = await client.get("/internal/status/" + response.json()["reference"], headers=gateway)
    assert public.json()["status"] == "requires_private_attention"
    for forbidden in ("invalid", "SIM-CODE", "SIM-INVOICE", "device", "refund"):
        assert forbidden not in public.text
    await client.post("/api/logout", headers=private)
    assert (await client.post(path, headers=gateway, json={"action": "accessible"})).status_code in (401, 403)
    assert provider.executions == 1


async def test_expired_private_views_are_accurate(client, gateway, private, device, app, monkeypatch):
    ref, _ = await approved(client, gateway, private, device)
    expires = app.state.mandates.view(ref)["document"]["expires_at"]
    monkeypatch.setattr(time, "time", lambda: expires)
    assert app.state.mandates.status(ref)["status"] == "expired"
    assert next(v for v in app.state.mandates.views() if v["reference"] == ref)["state"] == "expired"


async def test_lost_registration_response_is_revocable(client, gateway, private, device, app):
    # Start with an approved record, then emulate the durable state at the
    # registration crash boundary. The remote wallet already has the mandate.
    ref, _ = await approved(client, gateway, private, device)
    commerce = app.state.mandates
    value = commerce.view(ref)
    value["state"] = "registration_pending"
    commerce._save(ref, value)
    calls = []

    async def remote(path, body=None):
        calls.append(path)
        if path.endswith("/revoke"):
            return {"status": "revoked"}
        return {"status": "approved"}

    commerce.wallet = SimpleNamespace(call=remote)
    assert (await client.post(f"/api/mandates/{ref}/revoke", headers=private)).status_code == 200
    assert calls == ["/mandates", f"/mandates/{ref}/revoke"]
    assert commerce.status(ref)["status"] == "revoked"
    with pytest.raises(Refused):
        await commerce.approve(
            ref, MandateApproval(draft_hash=value["draft_hash"], device_public_key=device[1])
        )


async def test_same_product_id_cannot_change_country(client, gateway, private, device, provider):
    ref, _ = await approved(client, gateway, private, device)
    search = await client.post(
        "/internal/search",
        headers=gateway,
        json={"query": "gift cards", "country": "GB", "budget_cents": 500},
    )
    other = search.json()["reference"]
    assert (await buy(client, gateway, ref, other)).status_code == 409
    assert provider.executions == 0
    # A policy refusal consumes the reference binding, even before obtaining a quote.
    retry = await buy(client, gateway, ref, other)
    assert retry.json()["status"] == "refused"


async def test_cancellation_keeps_uncertainty_and_propagates(
    client, gateway, private, device, provider, app, monkeypatch
):
    import asyncio

    from pactora.mandate_commerce import PurchaseRequest

    ref, search = await approved(client, gateway, private, device)

    async def cancelled(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(provider, "execute", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await app.state.mandates.purchase(
            ref, PurchaseRequest(search_ref=search, option=0, purchase_ref="cancel")
        )
    value = app.state.mandates.view(ref)
    assert next(iter(value["deliveries"].values()))["payment"] == "uncertain"
    assert app.state.mandates.book._get("mandates", ref)["count"] == 1
    assert (await buy(client, gateway, ref, search, "cancel")).json()[
        "status"
    ] == "requires_private_attention"
