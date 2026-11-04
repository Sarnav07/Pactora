"""Actual shielded regtest payment through Pactora policy and receiver detection.

Requires the dedicated pactora-regtest container and ZecPy. Never uses mainnet.
Creates fresh owner-only wallets; all funds are mined on the private test chain.
"""

import argparse
import asyncio
import json
import os
import re
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zecpy import Wallet

from pactora.crypto import b64, canonical
from pactora.engine import Refused
from pactora.mandates import product_key
from pactora.test_merchant import InvoiceRequest, TestMerchant
from pactora.wallet_service import PaymentBinding, WalletService

HEIGHTS = {
    name: 1
    for name in (
        "overwinter",
        "sapling",
        "blossom",
        "heartwood",
        "canopy",
        "nu5",
        "nu6",
        "nu6_1",
        "nu6_2",
        "nu6_3",
    )
}
SERVER = "http://127.0.0.1:19067"


def rpc(method, params=None):
    request = urllib.request.Request(
        "http://127.0.0.1:18232",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode(),
        {"content-type": "application/json"},
    )
    result = json.load(urllib.request.urlopen(request, timeout=600))
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result["result"]


async def main(state, node_state, funding_state=None):
    os.umask(0o077)
    state = Path(state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    node_state = Path(node_state).resolve()
    info = json.loads(
        subprocess.run(["docker", "inspect", "pactora-regtest"], check=True, capture_output=True).stdout
    )[0]
    if info["Config"].get("Labels", {}).get("dev.pactora.proof") != "regtest":
        raise RuntimeError("refusing to modify a container not owned by this proof")
    config = node_state / "zebrad.toml"
    if 'network = "Regtest"' not in config.read_text():
        raise RuntimeError("regtest config required")
    if rpc("getblockcount") < 3:
        rpc("generate", [3])
    if funding_state:
        funding_state = Path(funding_state).resolve()
        miner = Wallet.open(
            funding_state / "miner",
            server=SERVER,
            mnemonic=(funding_state / "miner.mnemonic").read_text(),
            tor=False,
        )
        await miner.sync()
    else:
        miner, phrase = await Wallet.create(
            state / "miner", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
        )
        (state / "miner.mnemonic").write_text(phrase.reveal())
        address = miner.address()
        config.write_text(
            re.sub(
                r"^miner_address = .*$",
                'miner_address = "' + address + '"',
                config.read_text(),
                flags=re.MULTILINE,
            )
        )
        subprocess.run(["docker", "restart", "pactora-regtest"], check=True, capture_output=True)
        for _ in range(60):
            try:
                rpc("getblockcount")
                break
            except Exception:
                await asyncio.sleep(1)
        print("Mining private regtest funds; no public-chain funds involved", flush=True)
        rpc("generate", [105])
        await miner.sync()
    sender, phrase = await Wallet.create(
        state / "sender", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
    )
    (state / "sender.mnemonic").write_text(phrase.reveal())
    await miner.send_proposal(miner.propose(sender.address(), 2000000))
    rpc("generate", [20])
    await sender.sync()
    receiver, phrase = await Wallet.create(
        state / "receiver", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
    )
    (state / "receiver.mnemonic").write_text(phrase.reveal())
    del receiver
    receiver = Wallet.open(state / "receiver", server=SERVER, tor=False)
    merchant = TestMerchant(receiver, state / "merchant", amount_zat=100000)
    authority = Ed25519PrivateKey.generate()
    (state / "authority.key").write_text(b64(authority.private_bytes_raw()))
    storage_key = b64(secrets.token_bytes(32))
    (state / "journal.key").write_text(storage_key)
    service = WalletService(
        sender,
        state / "service",
        storage_key,
        b64(authority.public_key().public_bytes_raw()),
        1000000,
    )
    ref = secrets.token_urlsafe(24)
    document = {
        "domain": "veilcart-mandate-v1",
        "reference": ref,
        "version": 1,
        "wallet_id": "test-wallet",
        "network": "regtest",
        "merchant": "test_merchant",
        "eligible": [product_key("test-voucher", "one test voucher")],
        "per_purchase_cents": 100,
        "total_cents": 100,
        "per_purchase_zat": 200000,
        "total_zat": 200000,
        "max_purchases": 1,
        "expires_at": int(time.time()) + 1800,
    }
    service.mandates.install(document, b64(authority.sign(canonical(document))))
    operation = secrets.token_urlsafe(24)
    invoice = merchant.invoice(
        InvoiceRequest(operation=operation, product="test-voucher", package="one test voucher")
    )
    binding = PaymentBinding(
        merchant="test_merchant",
        invoice=operation,
        product="test-voucher",
        destination=invoice["address"],
        network="regtest",
        amount_zat=invoice["amount_zat"],
        max_debit_zat=200000,
        expires_at=invoice["expires_at"],
    )
    try:
        before = len(sender.transactions())
        result = await service.purchase_under_mandate(
            ref, "purchase-one", binding, "one test voucher", 100, invoice["expires_at"]
        )
        assert result["state"] == "broadcast"
        again = await service.purchase_under_mandate(
            ref, "purchase-one", binding, "one test voucher", 100, invoice["expires_at"]
        )
        assert again == result
        assert len(sender.transactions()) == before + 1
        attack = binding.model_copy(update={"product": "test-attack"})
        blocked = False
        try:
            await service.purchase_under_mandate(
                ref, "attack", attack, "unauthorized", 4000, invoice["expires_at"]
            )
        except Refused:
            blocked = True
        assert blocked
        rpc("generate", [1])
        receipt = await merchant.status(operation)
        assert receipt["status"] == "paid" and receipt["confirmed_zat"] == 100000
        report = {
            "proof": "native_zcash_policy_payment",
            "network": "regtest",
            "actual_shielded_receipt_confirmed": True,
            "confirmed_zat": 100000,
            "identical_retry_created_no_second_transaction": True,
            "unauthorized_purchase_blocked": True,
            "signing": "single full-key policy service",
            "frost_used": False,
            "bitrefill_used": False,
            "public_funds_moved": False,
            "tor_verified": False,
            "notice": "loopback regtest proof; no network anonymity claim",
        }
        (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        service.close()
        merchant.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--node-state", required=True)
    parser.add_argument("--funding-state", help="Existing private regtest miner state; never a public wallet")
    args = parser.parse_args()
    asyncio.run(main(args.state, args.node_state, args.funding_state))
