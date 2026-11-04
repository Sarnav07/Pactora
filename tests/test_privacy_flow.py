import json
import time

import pytest
from conftest import new_job, select_and_approve
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pactora.crypto import unb64


async def test_private_purchase_and_device_only_receipt(client, app, gateway, private, device, provider):
    job, approval = await select_and_approve(client, gateway, private, device)
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)).status_code == 200
    await app.state.engine.tick()
    status = (await client.get(f"/internal/status/{job}", headers=gateway)).json()
    assert status["status"] == "completed"
    assert set(status) == {"reference", "status", "environment"}
    assert provider.executions == 1
    row = app.state.engine.store.get(job)
    assert row["quote"] is None and row["device_key"] is None
    assert app.state.engine.store.cipher.decrypt(row["details"], job + ":details") == {}
    item = (await client.get("/api/jobs")).json()[0]
    envelope = item["vault"]
    raw = device[0].decrypt(
        unb64(envelope["key"]),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    result = json.loads(
        AESGCM(raw).decrypt(unb64(envelope["iv"]), unb64(envelope["ciphertext"]), b"veilcart-receipt-v1")
    )
    assert result["product"]["id"] == "demo-0" and result["code"].startswith("SIM-CODE-")
    for secret in (result["code"], result["invoice"], result["transaction"], "demo-0"):
        assert secret not in json.dumps(status)
        with app.state.engine.store.lock:
            dump = "\n".join(app.state.engine.store.db.iterdump())
        assert secret not in dump
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    with pytest.raises(ValueError):
        wrong.decrypt(
            unb64(envelope["key"]),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )


async def test_gateway_cannot_read_private_jobs_or_approve(client, gateway, device):
    job = await new_job(client, gateway)
    assert (await client.get("/api/jobs", headers=gateway)).status_code == 401
    r = await client.post(
        f"/api/jobs/{job}/approve",
        headers={**gateway, "Origin": "http://127.0.0.1:8787"},
        json={"quote_hash": "a" * 64, "device_public_key": device[1]},
    )
    assert r.status_code == 401


async def test_chat_selection_requires_private_opt_in(client, gateway, private):
    job = await new_job(client, gateway)
    r = await client.post(f"/internal/chat-select/{job}", headers=gateway, json={"option": 0})
    assert r.status_code == 409
    assert r.json() == {"error": "requires_private_attention"}
    assert (
        await client.post(f"/api/jobs/{job}/chat", headers=private, json={"enabled": True})
    ).status_code == 200
    assert (
        await client.post(f"/internal/chat-select/{job}", headers=gateway, json={"option": 0})
    ).status_code == 200


async def test_forget_expired_search_but_preserve_unresolved(client, app, gateway, private, device):
    job, approval = await select_and_approve(client, gateway, private, device)
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)).status_code == 200
    abandoned = await new_job(client, gateway)
    with app.state.engine.store.transaction() as db:
        db.execute("UPDATE jobs SET expires=?", (int(time.time()) - 1,))
    app.state.engine.store.cleanup()
    assert app.state.engine.store.get(abandoned)["state"] == "expired"
    assert app.state.engine.store.get(abandoned)["quote"] is None
    assert app.state.engine.store.get(job)["state"] == "approved"
    assert app.state.engine.store.get(job)["reservation"] > 0


async def test_auth_origin_csrf_and_no_cache(client, private):
    assert (await client.post("/api/logout", headers={"Origin": "https://evil.example"})).status_code == 403
    assert (await client.post("/api/logout", headers={"Origin": "http://127.0.0.1:8787"})).status_code == 403
    r = await client.get("/")
    assert "no-store" in r.headers["cache-control"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert (await client.get("/health", headers={"Host": "evil.example"})).status_code == 400
    assert (await client.post("/api/logout", headers=private)).status_code == 200
    assert (await client.get("/api/jobs")).status_code == 401


async def test_login_rate_limit(client):
    for _ in range(5):
        assert (
            await client.post(
                "/api/login", headers={"Origin": "http://127.0.0.1:8787"}, json={"password": "wrong"}
            )
        ).status_code == 401
    assert (
        await client.post(
            "/api/login", headers={"Origin": "http://127.0.0.1:8787"}, json={"password": "wrong"}
        )
    ).status_code == 429
