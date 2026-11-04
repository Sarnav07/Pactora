import secrets
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from pactora.controlled_provider import ControlledMerchant
from pactora.engine import Refused
from pactora.models import Product
from pactora.test_merchant import CATALOG, InvoiceRequest, TestMerchant, create_merchant_app


class Invoices:
    def __init__(self):
        self.items = {}
        self.paid = False
        self.created = 0

    def create(self, amount, reference):
        self.created += 1
        invoice = SimpleNamespace(
            reference=reference,
            address="regtest-shielded-address",
            amount_zat=amount,
            created_at=int(time.time()),
        )
        self.items[reference] = invoice
        return invoice

    def by_reference(self, reference):
        return self.items[reference]

    def poll(self, confirmations):
        assert confirmations >= 1

    def status(self, invoice):
        return SimpleNamespace(
            state="paid" if self.paid else "unpaid", confirmed_zat=invoice.amount_zat if self.paid else 0
        )


class Receiver:
    network = "regtest"
    can_send = False

    def __init__(self):
        self.invoices = Invoices()
        self.syncs = 0

    async def sync(self):
        self.syncs += 1


async def test_merchant_invoice_replay_and_native_receipt(tmp_path):
    wallet = Receiver()
    merchant = TestMerchant(wallet, tmp_path)
    ref = secrets.token_urlsafe(24)
    request = InvoiceRequest(operation=ref, product="test-voucher", package="one test voucher")
    first = merchant.invoice(request)
    assert merchant.invoice(request) == first
    assert wallet.invoices.created == 1
    with pytest.raises(Refused, match="changed"):
        merchant.invoice(InvoiceRequest(operation=ref, product="test-attack", package="unauthorized"))
    assert (await merchant.status(ref))["status"] == "unpaid"
    wallet.invoices.paid = True
    assert (await merchant.status(ref))["confirmed_zat"] == first["amount_zat"]
    assert wallet.syncs == 2
    merchant.db.close()


async def test_merchant_api_auth_and_watch_only(tmp_path):
    wallet = Receiver()
    wallet.can_send = True
    with pytest.raises(ValueError):
        TestMerchant(wallet, tmp_path)
    wallet.can_send = False
    merchant = TestMerchant(wallet, tmp_path)
    app = create_merchant_app(merchant, "x" * 32)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://merchant"
    ) as client:
        assert (await client.get("/catalog")).status_code == 403
        response = await client.get("/catalog", headers={"Authorization": "Bearer " + "x" * 32})
        assert response.json()["test_only"] is True
        assert response.headers["cache-control"] == "no-store"
    merchant.db.close()


@pytest.mark.parametrize(
    "url,network",
    [
        ("http://remote.example", "test"),
        ("http://127.0.0.1:8791", "test"),
        ("https://secret@remote.example", "test"),
    ],
)
def test_testmerchant_endpoint_restrictions(settings, url, network):
    with pytest.raises(ValueError):
        ControlledMerchant(
            replace(settings, provider="test_merchant", test_merchant_url=url, wallet_network=network)
        )


async def test_provider_validates_invoice_binding(settings, monkeypatch):
    provider = ControlledMerchant(
        replace(
            settings,
            provider="test_merchant",
            wallet_network="regtest",
            test_merchant_url="http://127.0.0.1:8791",
        )
    )

    async def changed(method, path, body=None):
        return {
            "reference": body["operation"],
            "product": {**CATALOG[0], "id": "attacker"},
            "amount_zat": 100000,
            "network": "regtest",
            "test_only": True,
        }

    monkeypatch.setattr(provider, "request", changed)
    with pytest.raises(Exception, match="binding"):
        await provider.quote_for(Product.model_validate(CATALOG[0]), secrets.token_urlsafe(24))


async def test_controlled_flow_wallet_policy_and_private_confirmation(settings, tmp_path, device):
    from conftest import PASSWORD
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from test_wallet_service import Wallet as SigningWallet

    from pactora.app import create_app
    from pactora.crypto import b64
    from pactora.wallet_api import create_wallet_app
    from pactora.wallet_service import WalletService

    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "authority"
    key_file.write_text(b64(key.private_bytes_raw()))
    key_file.chmod(0o600)
    cfg = replace(
        settings,
        provider="test_merchant",
        wallet_network="regtest",
        test_merchant_url="http://127.0.0.1:8791",
        mandate_signing_key_file=str(key_file),
    )
    receiver = Receiver()
    merchant = TestMerchant(receiver, tmp_path / "merchant")
    merchant_app = create_merchant_app(merchant, "m" * 32)
    provider = ControlledMerchant(cfg)

    async def merchant_request(method, path, body=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=merchant_app), base_url="http://merchant"
        ) as client:
            response = await client.request(
                method, path, json=body, headers={"Authorization": "Bearer " + "m" * 32}
            )
            assert response.status_code == 200, response.text
            return response.json()

    provider.request = merchant_request
    signer = SigningWallet()
    service = WalletService(
        signer, tmp_path / "wallet", settings.master_key, b64(key.public_key().public_bytes_raw()), 500000
    )
    wallet_app = create_wallet_app(service, "w" * 32)
    app = create_app(cfg, provider, run_worker=False)

    async def wallet_call(path, body=None, *, method="POST"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wallet_app), base_url="http://wallet"
        ) as client:
            response = await client.request(
                method, path, json=body, headers={"Authorization": "Bearer " + "w" * 32}
            )
            if response.status_code != 200:
                raise Refused("wallet_bridge_unavailable")
            return response.json()

    app.state.mandates.wallet = SimpleNamespace(call=wallet_call)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=cfg.origin) as client:
            origin = {"Origin": cfg.origin}
            login = await client.post("/api/login", headers=origin, json={"password": PASSWORD})
            private = {**origin, "X-CSRF-Token": login.json()["csrf"]}
            gateway = {"Authorization": "Bearer " + cfg.gateway_key}
            search = (
                await client.post(
                    "/internal/search",
                    headers=gateway,
                    json={"query": "test voucher", "country": "IN", "budget_cents": 500},
                )
            ).json()["reference"]
            draft = await client.post(
                "/internal/mandates",
                headers=gateway,
                json={
                    "search_ref": search,
                    "per_purchase_cents": 200,
                    "total_cents": 400,
                    "per_purchase_zat": 200000,
                    "total_zat": 400000,
                    "max_purchases": 2,
                    "duration_seconds": 600,
                },
            )
            ref = draft.json()["reference"]
            value = app.state.mandates.view(ref)
            assert (
                await client.post(
                    f"/api/mandates/{ref}/approve",
                    headers=private,
                    json={"draft_hash": value["draft_hash"], "device_public_key": device[1]},
                )
            ).status_code == 200
            payload = {"search_ref": search, "option": 0, "purchase_ref": "one"}
            first = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=payload)
            assert first.status_code == 200, first.text
            assert first.json()["status"] == "awaiting_test_confirmation"
            assert signer.signs == 1
            retry = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=payload)
            assert retry.json() == first.json()
            attack = await client.post(
                f"/internal/mandates/{ref}/purchase",
                headers=gateway,
                json={**payload, "option": 1, "purchase_ref": "attack"},
            )
            assert attack.status_code == 409 and signer.signs == 1
            receiver.invoices.paid = True
            recovered = await client.post(f"/api/mandates/{ref}/recover", headers=private)
            assert recovered.status_code == 200, recovered.text
            assert len(app.state.mandates.view(ref)["receipts"]) == 1
            assert signer.signs == 1
            complete = await client.post(f"/internal/mandates/{ref}/purchase", headers=gateway, json=payload)
            assert complete.json()["status"] == "completed"
            assert "stored-tx" not in complete.text and "regtest-shielded" not in complete.text
    finally:
        service.close()
        merchant.db.close()
        app.state.mandates.book.close()
        app.state.engine.store.db.close()
