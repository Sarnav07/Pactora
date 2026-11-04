import asyncio
import secrets
import time
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pactora.crypto import b64, canonical
from pactora.engine import Refused
from pactora.wallet_api import create_wallet_app
from pactora.wallet_service import PaymentBinding, WalletService


class Wallet:
    network = "regtest"

    def __init__(self):
        self.signs = 0
        self.broadcasts = []
        self.fail_sign = False
        self.fail_broadcast = False
        self.crossing = 0
        self.fail_sync = False

    async def sync(self):
        if self.fail_sync:
            raise RuntimeError("secret endpoint details")

    def propose(self, destination, amount, **flags):
        assert flags == {"allow_transparent": False, "allow_pool_crossing": False}
        if destination == "transparent":
            raise Refused("transparent")
        return SimpleNamespace(paying_out=amount, fee=10, crossing_value=self.crossing)

    async def sign_proposal(self, proposal):
        self.signs += 1
        await asyncio.sleep(0)
        if self.fail_sign:
            raise RuntimeError("secret native details")
        return "stored-tx-" + str(self.signs)

    async def rebroadcast_transaction(self, txid):
        self.broadcasts.append(txid)
        if self.fail_broadcast:
            raise RuntimeError("network failure")
        return txid


@pytest.fixture
def setup(tmp_path):
    key = Ed25519PrivateKey.generate()
    enc = b64(secrets.token_bytes(32))
    pub = b64(key.public_key().public_bytes_raw())
    wallet = Wallet()
    service = WalletService(wallet, tmp_path, enc, pub, 220)
    yield service, wallet, key, tmp_path, enc, pub
    service.close()


def binding(**changes):
    return PaymentBinding(
        **{
            "merchant": "merchant-secret",
            "invoice": "invoice-secret",
            "product": "product-secret",
            "destination": "shielded-secret",
            "network": "regtest",
            "amount_zat": 100,
            "max_debit_zat": 110,
            "expires_at": int(time.time()) + 600,
            **changes,
        }
    )


def sign(key, approval):
    return b64(key.sign(canonical(approval)))


async def test_exact_approval_and_concurrent_replay(setup):
    service, wallet, key, *_ = setup
    approval = await service.prepare(binding())
    ref = approval["reference"]
    results = await asyncio.gather(
        *(service.execute(ref, sign(key, approval)) for _ in range(2)), return_exceptions=True
    )
    assert sum(isinstance(r, Refused) for r in results) == 1
    assert wallet.signs == 1
    assert "secret" not in str(service.status(ref))


@pytest.mark.parametrize(
    "field,value",
    [
        ("destination", "attacker"),
        ("merchant", "attacker"),
        ("invoice", "new"),
        ("product", "new"),
        ("network", "test"),
        ("fee_zat", 0),
        ("total_zat", 0),
        ("expires_at", 9999999999),
        ("reference", "other"),
        ("amount_zat", 1),
    ],
)
async def test_changed_approval_never_signs(setup, field, value):
    service, wallet, key, *_ = setup
    approval = await service.prepare(binding())
    changed = {**approval, field: value}
    with pytest.raises(Refused, match="approval_invalid"):
        await service.execute(approval["reference"], sign(key, changed))
    assert wallet.signs == 0


async def test_expired_and_revoked(setup, monkeypatch):
    service, wallet, key, *_ = setup
    approval = await service.prepare(binding())
    await service.revoke(approval["reference"])
    with pytest.raises(Refused):
        await service.execute(approval["reference"], sign(key, approval))
    approval = await service.prepare(binding())
    monkeypatch.setattr(time, "time", lambda: approval["expires_at"])
    with pytest.raises(Refused, match="expired"):
        await service.execute(approval["reference"], sign(key, approval))
    assert wallet.signs == 0


async def test_budget_and_unknown_signing(setup):
    service, wallet, key, *_ = setup
    wallet.fail_sign = True
    for _ in range(2):
        a = await service.prepare(binding())
        with pytest.raises(Refused, match="uncertain"):
            await service.execute(a["reference"], sign(key, a))
        with pytest.raises(Refused):
            await service.recover(a["reference"])
    a = await service.prepare(binding())
    with pytest.raises(Refused, match="aggregate_cap"):
        await service.execute(a["reference"], sign(key, a))
    assert wallet.signs == 2


async def test_restart_rebroadcasts_identical_transaction(setup):
    service, wallet, key, directory, enc, pub = setup
    a = await service.prepare(binding())
    unused = await service.prepare(binding())
    wallet.fail_broadcast = True
    assert (await service.execute(a["reference"], sign(key, a)))["state"] == "signed"
    service.close()
    # Fixture cleanup follows the replacement instance.
    replacement = WalletService(wallet, directory, enc, pub, 220)
    service.__dict__.update(replacement.__dict__)
    assert service.status(unused["reference"])["state"] == "quarantined"
    wallet.fail_broadcast = False
    assert (await service.recover(a["reference"]))["state"] == "broadcast"
    assert wallet.signs == 1
    assert wallet.broadcasts == ["stored-tx-1", "stored-tx-1"]
    raw = (directory / "journal.sqlite").read_bytes()
    assert b"shielded-secret" not in raw and b"stored-tx-1" not in raw


async def test_signing_crash_journal_is_quarantined(setup):
    service, wallet, key, directory, enc, pub = setup
    a = await service.prepare(binding())
    _, data = service.private_record(a["reference"])
    data["reserved"] = True
    service._save(a["reference"], "signing", data)
    service.close()
    replacement = WalletService(wallet, directory, enc, pub, 220)
    service.__dict__.update(replacement.__dict__)
    assert service.status(a["reference"])["state"] == "quarantined"
    with pytest.raises(Refused):
        await service.execute(a["reference"], sign(key, a))
    assert wallet.signs == 0


async def test_wallet_rules(setup):
    service, wallet, *_ = setup
    for changes in (
        {"destination": "transparent"},
        {"max_debit_zat": 100},
        {"network": "test"},
        {"expires_at": 1},
    ):
        with pytest.raises(Refused):
            await service.prepare(binding(**changes))
    wallet.crossing = 1
    with pytest.raises(Refused, match="pool_crossing"):
        await service.prepare(binding())


async def test_api_auth_and_redaction(setup):
    service, wallet, *_ = setup
    app = create_wallet_app(service, "x" * 32)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://wallet") as client:
        assert (await client.post("/prepare", json=binding().model_dump())).status_code == 403
        headers = {"Authorization": "Bearer " + "x" * 32}
        response = await client.post(
            "/prepare", headers=headers, json={**binding().model_dump(), "amount_zat": "secret-invalid"}
        )
        assert response.status_code == 422
        assert "secret-invalid" not in response.text
        assert (
            await client.post(
                "/prepare", headers={**headers, "Origin": "http://evil"}, json=binding().model_dump()
            )
        ).status_code == 403
        response = await client.post("/prepare", headers=headers, json=binding().model_dump())
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


async def test_protected_sync_failure_prevents_signing(setup):
    service, wallet, key, *_ = setup
    approval = await service.prepare(binding())
    wallet.fail_sync = True
    with pytest.raises(Refused, match="protected_wallet_sync_unavailable"):
        await service.execute(approval["reference"], sign(key, approval))
    assert wallet.signs == 0
    assert service.status(approval["reference"])["state"] == "prepared"


async def test_expiry_during_sync_prevents_signing(setup, monkeypatch):
    service, wallet, key, *_ = setup
    approval = await service.prepare(binding())

    async def sync():
        monkeypatch.setattr(time, "time", lambda: approval["expires_at"])

    wallet.sync = sync
    with pytest.raises(Refused, match="expired"):
        await service.execute(approval["reference"], sign(key, approval))
    assert wallet.signs == 0


async def test_second_process_owner_is_refused(setup):
    service, wallet, key, directory, enc, pub = setup
    with pytest.raises(Refused, match="already_running"):
        WalletService(wallet, directory, enc, pub, 220)


async def test_api_exact_payment_flow(setup):
    service, wallet, key, *_ = setup
    app = create_wallet_app(service, "x" * 32)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://wallet",
        headers={"Authorization": "Bearer " + "x" * 32},
    ) as client:
        assert (await client.post("/sync")).json()["state"] == "synced"
        approval = (await client.post("/prepare", json=binding().model_dump())).json()
        reference = approval["reference"]
        response = await client.post(
            f"/operations/{reference}/execute", json={"signature": sign(key, approval)}
        )
        assert response.json()["state"] == "broadcast"
        assert "stored-tx" not in response.text
        assert (
            await client.post(f"/operations/{reference}/execute", json={"signature": sign(key, approval)})
        ).status_code == 403
        assert wallet.signs == 1


def test_owner_only_secret_files(tmp_path):
    from pactora.wallet_cli import protected_file

    path = tmp_path / "secret"
    path.write_text("secret")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        protected_file(path)
    path.chmod(0o600)
    assert protected_file(path) == "secret"
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        protected_file(alias)


def test_private_approval_helper(tmp_path, monkeypatch):
    import json
    import sys

    from pactora.crypto import digest
    from pactora.wallet_approval import main

    key = Ed25519PrivateKey.generate()
    approval = {
        "domain": "veilcart-wallet-approval-v1",
        "reference": "private-reference",
        **binding().model_dump(),
        "fee_zat": 10,
        "total_zat": 110,
    }
    pending, secret, output = (tmp_path / n for n in ("pending", "key", "signature"))
    pending.write_text(json.dumps(approval))
    secret.write_text(b64(key.private_bytes_raw()))
    pending.chmod(0o600)
    secret.chmod(0o600)
    monkeypatch.setattr(
        sys,
        "argv",
        ["approve", "--approval-file", str(pending), "--key-file", str(secret), "--output", str(output)],
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "approve " + digest(approval)[:12])
    main()
    from pactora.crypto import unb64

    key.public_key().verify(unb64(json.loads(output.read_text())["signature"]), canonical(approval))
    assert output.stat().st_mode & 0o077 == 0


def test_wallet_directory_permissions(tmp_path):
    from pactora.wallet_cli import protected_wallet_directory

    wallet = tmp_path / "wallet"
    wallet.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        protected_wallet_directory(wallet)
    wallet.chmod(0o700)
    protected_wallet_directory(wallet)
    link = tmp_path / "link"
    link.symlink_to(wallet, target_is_directory=True)
    with pytest.raises(ValueError):
        protected_wallet_directory(link)


async def test_wallet_enforces_mandate_before_signing(setup):
    from pactora.mandates import product_key

    service, wallet, key, *_ = setup
    ref = secrets.token_urlsafe(24)
    doc = {
        "domain": "veilcart-mandate-v1",
        "reference": ref,
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
        "expires_at": int(time.time()) + 500,
    }
    service.mandates.install(doc, sign(key, doc))

    async def pay(purchase, **changes):
        return await service.purchase_under_mandate(
            ref, purchase, binding(**changes), "package", 210, int(time.time()) + 100
        )

    first = await pay("one")
    assert first["state"] == "broadcast"
    # Exact retry uses the identical full bound envelope (including timestamps).
    bound = binding()
    expires = int(time.time()) + 100
    await service.purchase_under_mandate(ref, "two", bound, "package", 210, expires)
    await service.purchase_under_mandate(ref, "two", bound, "package", 210, expires)
    assert wallet.signs == 2
    with pytest.raises(Refused):
        await pay("three")
    assert wallet.signs == 2


async def test_wallet_mandate_substitution_and_revocation(setup):
    from pactora.mandates import product_key

    service, wallet, key, *_ = setup
    ref = secrets.token_urlsafe(24)
    doc = {
        "domain": "veilcart-mandate-v1",
        "reference": ref,
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
        "expires_at": int(time.time()) + 500,
    }
    service.mandates.install(doc, sign(key, doc))
    with pytest.raises(Refused):
        await service.purchase_under_mandate(
            ref, "attack", binding(product="attacker"), "package", 210, int(time.time()) + 100
        )
    service.mandates.revoke(ref)
    with pytest.raises(Refused):
        await service.purchase_under_mandate(ref, "one", binding(), "package", 210, int(time.time()) + 100)
    assert wallet.signs == 0


async def test_wallet_mandate_http_registration_and_revoke(setup):
    import httpx

    from pactora.mandates import product_key
    from pactora.wallet_api import create_wallet_app

    service, wallet, key, *_ = setup
    ref = secrets.token_urlsafe(24)
    doc = {
        "domain": "veilcart-mandate-v1",
        "reference": ref,
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
        "expires_at": int(time.time()) + 500,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_wallet_app(service, "t" * 32)),
        base_url="http://wallet",
        headers={"Authorization": "Bearer " + "t" * 32},
    ) as client:
        response = await client.post("/mandates", json={"document": doc, "signature": sign(key, doc)})
        assert response.status_code == 200
        changed = {**doc, "max_purchases": 99}
        response = await client.post("/mandates", json={"document": changed, "signature": sign(key, doc)})
        assert response.status_code == 403
        payload = {
            "purchase_ref": "one",
            "binding": binding().model_dump(),
            "package": "package",
            "total_cents": 210,
            "quote_expires": int(time.time()) + 100,
        }
        response = await client.post(f"/mandates/{ref}/purchase", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "broadcast"
        assert (await client.post(f"/mandates/{ref}/revoke")).status_code == 200
        response = await client.post(f"/mandates/{ref}/purchase", json={**payload, "purchase_ref": "two"})
        assert response.status_code == 403
        assert wallet.signs == 1


async def test_ineligible_product_rejected_before_native_proposal(setup, monkeypatch):
    from pactora.mandates import product_key

    service, wallet, key, *_ = setup
    ref = secrets.token_urlsafe(24)
    doc = {
        "domain": "veilcart-mandate-v1",
        "reference": ref,
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
        "expires_at": int(time.time()) + 500,
    }
    service.mandates.install(doc, sign(key, doc))

    def unavailable(*args, **kwargs):
        raise AssertionError("native proposal must never be reached for ineligible product")

    monkeypatch.setattr(wallet, "propose", unavailable)
    with pytest.raises(Refused, match="product_not_permitted"):
        await service.purchase_under_mandate(
            ref, "attack", binding(product="attacker"), "package", 210, int(time.time()) + 100
        )
    assert wallet.signs == 0
    # Early policy refusal must still consume this reference's immutable binding.
    with pytest.raises(Refused, match="purchase_reference_changed"):
        await service.purchase_under_mandate(ref, "attack", binding(), "package", 210, int(time.time()) + 100)
    assert wallet.signs == 0


async def test_pause_blocks_signing_and_survives_restart(setup):
    service, wallet, key, path, enc, pub = setup
    approval = await service.prepare(binding())
    await service.set_paused(True)
    with pytest.raises(Refused, match="signing_paused"):
        await service.execute(approval["reference"], sign(key, approval))
    assert wallet.signs == 0
    # Reopen using the same encrypted journal, preserving the control row.
    service.db.close()
    service.db = __import__("sqlite3").connect(path / "journal.sqlite")
    assert service.control() == {"paused": True}
    await service.set_paused(False)
    assert (await service.execute(approval["reference"], sign(key, approval)))["state"] == "broadcast"
    assert wallet.signs == 1
