import asyncio
import secrets
import time

import pytest
from conftest import new_job
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pactora.crypto import PrivateStoreCipher, b64, canonical
from pactora.engine import Refused
from pactora.mandates import MandateBook, product_key


def document(**updates):
    return {
        "domain": "veilcart-mandate-v1",
        "reference": secrets.token_urlsafe(24),
        "version": 1,
        "wallet_id": "test-wallet",
        "network": "regtest",
        "merchant": "merchant-secret",
        "eligible": [product_key("product-secret", "package")],
        "per_purchase_cents": 210,
        "total_cents": 420,
        "per_purchase_zat": 110,
        "total_zat": 220,
        "max_purchases": 2,
        "expires_at": int(time.time()) + 600,
        **updates,
    }


@pytest.fixture
def ledger(tmp_path):
    key = Ed25519PrivateKey.generate()
    book = MandateBook(
        tmp_path, PrivateStoreCipher(b64(secrets.token_bytes(32))), b64(key.public_key().public_bytes_raw())
    )
    doc = document()
    signature = b64(key.sign(canonical(doc)))
    book.install(doc, signature)
    yield book, doc, key, signature
    book.close()


def reserve(book, doc, purchase="one", **changes):
    args = dict(
        merchant=doc["merchant"],
        wallet_id="test-wallet",
        network="regtest",
        product="product-secret",
        package="package",
        cents=210,
        zat=110,
        quote_expires=int(time.time()) + 100,
    )
    args.update(changes)
    return book.reserve(doc["reference"], purchase, "selection", **args)


def test_two_purchases_and_no_reset_on_registration(ledger):
    book, doc, _, signature = ledger
    first, fresh = reserve(book, doc)
    assert fresh
    retry, fresh = reserve(book, doc)
    assert not fresh and retry == first
    reserve(book, doc, "two")
    book.install(doc, signature)
    with pytest.raises(Refused, match="limit"):
        reserve(book, doc, "three")
    with pytest.raises(Refused, match="changed"):
        book.lookup(doc["reference"], "one", "new-selection")


@pytest.mark.parametrize(
    "change",
    [
        {"merchant": "attacker"},
        {"wallet_id": "other"},
        {"network": "test"},
        {"product": "attacker"},
        {"package": "other"},
        {"cents": 4000},
        {"zat": 111},
        {"quote_expires": 1},
    ],
)
def test_binding_and_quote_refusals(ledger, change):
    book, doc, *_ = ledger
    with pytest.raises(Refused):
        reserve(book, doc, **change)
    assert book.lookup(doc["reference"], "one", "selection")["status"] == "refused"
    with pytest.raises(Refused):
        book.lookup(doc["reference"], "one", "changed")


def test_signed_documents_and_revocation(ledger):
    book, doc, key, signature = ledger
    with pytest.raises(Refused, match="signature"):
        book.install({**doc, "max_purchases": 99}, signature)
    book.revoke(doc["reference"])
    book.install(doc, signature)
    assert book.status(doc["reference"])["status"] == "revoked"
    with pytest.raises(Refused):
        reserve(book, doc)


async def approved(client, gateway, private, device):
    search = await new_job(client, gateway)
    body = {
        "search_ref": search,
        "per_purchase_cents": 250,
        "total_cents": 500,
        "per_purchase_zat": 300000,
        "total_zat": 600000,
        "max_purchases": 2,
        "duration_seconds": 600,
    }
    response = await client.post("/internal/mandates", headers=gateway, json=body)
    assert response.status_code == 200, response.text
    ref = response.json()["reference"]
    view = next(v for v in (await client.get("/api/mandates")).json() if v["reference"] == ref)
    response = await client.post(
        f"/api/mandates/{ref}/approve",
        headers=private,
        json={"draft_hash": view["draft_hash"], "device_public_key": device[1]},
    )
    assert response.status_code == 200, response.text
    return ref, search


async def test_http_mandate_purchase_replay_and_receipts(client, gateway, private, device, provider):
    ref, search = await approved(client, gateway, private, device)

    async def buy(purchase, option=0):
        return await client.post(
            f"/internal/mandates/{ref}/purchase",
            headers=gateway,
            json={"search_ref": search, "option": option, "purchase_ref": purchase},
        )

    one, retry = await asyncio.gather(buy("one"), buy("one"))
    assert one.status_code == retry.status_code == 200
    assert one.json() == retry.json()
    assert provider.executions == 1
    assert "SIM-CODE" not in one.text and "SIM-INVOICE" not in one.text
    status = await client.get("/internal/status/" + one.json()["reference"], headers=gateway)
    assert status.json()["status"] == "completed"
    assert (await buy("two")).json()["status"] == "completed"
    assert (await buy("three")).status_code == 409
    assert (await buy("one", 1)).status_code == 409
    assert provider.executions == 2
    views = (await client.get("/api/mandates")).json()
    assert len(views[0]["receipts"]) == 2
    assert "SIM-CODE" not in str(views)


async def test_agent_cannot_approve_or_read_private(client, gateway, private, device):
    ref, search = await approved(client, gateway, private, device)
    await client.post("/api/logout", headers=private)
    assert (await client.get("/api/mandates", headers=gateway)).status_code == 401
    assert (await client.post(f"/api/mandates/{ref}/revoke", headers=gateway)).status_code in (401, 403)
    # Gateway cannot choose recipients even with an approved mandate.
    response = await client.post(
        f"/internal/mandates/{ref}/purchase",
        headers=gateway,
        json={"search_ref": search, "option": 0, "purchase_ref": "one", "destination": "attacker"},
    )
    assert response.status_code == 422


async def test_http_revocation_and_malicious_option(client, gateway, private, device, provider):
    ref, search = await approved(client, gateway, private, device)
    response = await client.post(
        f"/internal/mandates/{ref}/purchase",
        headers=gateway,
        json={"search_ref": search, "option": 3, "purchase_ref": "attack"},
    )
    assert response.status_code == 409
    assert provider.executions == 0
    assert (await client.post(f"/api/mandates/{ref}/revoke", headers=private)).status_code == 200
    response = await client.post(
        f"/internal/mandates/{ref}/purchase",
        headers=gateway,
        json={"search_ref": search, "option": 0, "purchase_ref": "one"},
    )
    assert response.status_code == 409
    assert provider.executions == 0


def test_expiry_and_persistence(ledger, monkeypatch):
    book, doc, _, signature = ledger
    reserve(book, doc)
    monkeypatch.setattr(time, "time", lambda: doc["expires_at"])
    with pytest.raises(Refused):
        reserve(book, doc, "expired")
    book.install(doc, signature)
    assert book.status(doc["reference"])["status"] == "expired"
    assert book.lookup(doc["reference"], "one", "selection")["status"] == "reserved"


async def test_uncertain_execution_never_retried(client, gateway, private, device, provider, monkeypatch):
    ref, search = await approved(client, gateway, private, device)
    calls = []

    async def broken(quote, operation):
        calls.append(operation)
        raise TimeoutError("unknown merchant outcome")

    monkeypatch.setattr(provider, "execute", broken)
    args = {"search_ref": search, "option": 0, "purchase_ref": "one"}
    assert (
        await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=args)
    ).status_code == 409
    retry = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=args)
    assert retry.json()["status"] == "requires_private_attention"
    assert len(calls) == 1


async def test_receipt_recovery_does_not_reexecute(
    client, gateway, private, device, provider, app, monkeypatch
):
    ref, search = await approved(client, gateway, private, device)
    commerce = app.state.mandates
    original = commerce.recover_receipts

    def fail_delivery(reference):
        raise RuntimeError("device delivery interrupted")

    monkeypatch.setattr(commerce, "recover_receipts", fail_delivery)
    args = {"search_ref": search, "option": 0, "purchase_ref": "one"}
    assert (
        await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=args)
    ).status_code == 409
    assert provider.executions == 1
    monkeypatch.setattr(commerce, "recover_receipts", original)
    for _ in range(2):
        response = await client.post(f"/api/mandates/{ref}/recover", headers=private)
        assert response.status_code == 200
    assert len(commerce.view(ref)["receipts"]) == 1
    assert provider.executions == 1
    retry = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=args)
    assert retry.json()["status"] == "completed"


def test_persistent_budget_across_connections(ledger):
    book, doc, key, signature = ledger
    directory = book.db.execute("PRAGMA database_list").fetchone()[2]
    from pathlib import Path

    other = MandateBook(Path(directory).parent, book.cipher, b64(key.public_key().public_bytes_raw()))
    try:
        reserve(book, doc, "one")
        other.install(doc, signature)
        reserve(other, doc, "two")
        with pytest.raises(Refused):
            reserve(book, doc, "three")
        other.revoke(doc["reference"])
        assert book.status(doc["reference"])["status"] == "revoked"
    finally:
        other.close()
