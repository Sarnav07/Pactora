"""MCP + private Chromium + actual regtest wallet/merchant HTTP proof.

Uses dedicated newly generated test wallets. All services share one host/process;
this demonstrates API integration, not production OS isolation or real goods.
"""

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_payment import HEIGHTS, SERVER, rpc
from playwright.async_api import async_playwright
from zecpy import Wallet

from pactora.app import create_app
from pactora.config import Settings
from pactora.crypto import b64, password_hash
from pactora.test_merchant import TestMerchant, create_merchant_app
from pactora.wallet_api import create_wallet_app
from pactora.wallet_service import WalletService


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main(args):
    os.umask(0o077)
    state = Path(args.state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    funding = Path(args.funding_state).resolve()
    miner = Wallet.open(
        funding / "miner", server=SERVER, tor=False, mnemonic=(funding / "miner.mnemonic").read_text()
    )
    sender, phrase = await Wallet.create(
        state / "sender", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
    )
    (state / "sender.mnemonic").write_text(phrase.reveal())
    receiver, phrase = await Wallet.create(
        state / "receiver", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
    )
    (state / "receiver.mnemonic").write_text(phrase.reveal())
    del receiver
    receiver = Wallet.open(state / "receiver", server=SERVER, tor=False)
    await miner.sync()
    await miner.send_proposal(miner.propose(sender.address(), 1000000))
    await asyncio.to_thread(rpc, "generate", [20])
    await sender.sync()
    key = Ed25519PrivateKey.generate()
    key_file = state / "authority.key"
    key_file.write_text(b64(key.private_bytes_raw()))
    merchant_token, wallet_token, gateway_token = (secrets.token_urlsafe(32) for _ in range(3))
    for name, token in (("merchant.token", merchant_token), ("wallet.token", wallet_token)):
        (state / name).write_text(token)
    storage_key = b64(secrets.token_bytes(32))
    (state / "journal.key").write_text(storage_key)
    service = WalletService(
        sender, state / "wallet-state", storage_key, b64(key.public_key().public_bytes_raw()), 500000
    )
    merchant = TestMerchant(receiver, state / "merchant-state")
    merchant_port, wallet_port, executor_port = port(), port(), port()
    origin = f"http://127.0.0.1:{executor_port}"
    password = secrets.token_urlsafe(20)
    cfg = Settings(
        data_dir=state / "commerce",
        master_key=storage_key,
        gateway_key=gateway_token,
        password_hash=password_hash(password),
        origin=origin,
        provider="test_merchant",
        wallet_network="regtest",
        wallet_service_url=f"http://127.0.0.1:{wallet_port}",
        wallet_api_token_file=str(state / "wallet.token"),
        test_merchant_url=f"http://127.0.0.1:{merchant_port}",
        test_merchant_token_file=str(state / "merchant.token"),
        mandate_signing_key_file=str(key_file),
    )
    apps = [
        (create_merchant_app(merchant, merchant_token), merchant_port),
        (create_wallet_app(service, wallet_token), wallet_port),
        (create_app(cfg), executor_port),
    ]
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=p, access_log=False, log_level="critical"))
        for app, p in apps
    ]
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        for _ in range(100):
            if all(server.started for server in servers):
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("local proof services did not start")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "pactora.mcp_server"],
            env={**os.environ, "PACTORA_EXECUTOR_URL": origin, "PACTORA_GATEWAY_KEY": gateway_token},
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            async def tool(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.isError
                return json.loads(result.content[0].text)

            found = await tool(
                "search_products", {"query": "test voucher", "country": "IN", "budget_cents": 500}
            )
            draft = await tool(
                "request_mandate",
                {
                    "search_ref": found["reference"],
                    "per_purchase_cents": 100,
                    "total_cents": 100,
                    "per_purchase_zat": 150000,
                    "total_zat": 150000,
                    "max_purchases": 1,
                    "duration_seconds": 900,
                },
            )
            ref = draft["reference"]
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(executable_path=args.browser, headless=True)
                try:
                    page = await browser.new_page()
                    await page.goto(origin + "/app")
                    await page.get_by_label("Private-view password").fill(password)
                    await page.get_by_role("button", name="Unlock private view").click()
                    await page.get_by_role("button", name="Approve intent", exact=True).click()
                    await page.get_by_role("button", name="Approve intent", exact=True).wait_for(
                        state="detached"
                    )
                    purchase = {
                        "reference": ref,
                        "search_ref": found["reference"],
                        "option": 0,
                        "purchase_ref": "native-one",
                    }
                    before = len(sender.transactions())
                    first = await tool("request_purchase", purchase)
                    assert first["status"] == "awaiting_test_confirmation", first
                    assert await tool("request_purchase", purchase) == first
                    assert len(sender.transactions()) == before + 1
                    refused = await tool(
                        "request_purchase", {**purchase, "option": 1, "purchase_ref": "attack"}
                    )
                    assert refused["status"] == "requires_private_attention"
                    assert len(sender.transactions()) == before + 1
                    await asyncio.to_thread(rpc, "generate", [1])
                    await page.get_by_role(
                        "button", name="Recover existing payment / receipt", exact=True
                    ).click()
                    await page.get_by_role("link", name="Live", exact=False).click()
                    await page.get_by_role("button", name="Reveal / hide mandate receipt", exact=True).click()
                    await (
                        page.locator(".secret")
                        .filter(has_text="Actual shielded test-network receipt")
                        .wait_for()
                    )
                    assert (await tool("purchase_status", {"reference": first["reference"]}))[
                        "status"
                    ] == "completed"
                    record = apps[-1][0].state.mandates.view(ref)
                    delivery = next(iter(record["deliveries"].values()))
                    assert delivery["payment"] == "confirmed" and delivery["fulfillment"] == "not_applicable"
                    assert '"confirmed_zat": 100000' in await page.locator(".secret").inner_text()
                    await page.get_by_role("link", name="Intents", exact=True).click()
                    await page.get_by_role("button", name="Revoke intent", exact=True).click()
                    assert (await tool("mandate_status", {"reference": ref}))["status"] == "revoked"
                finally:
                    await browser.close()
        report = {
            "proof": "native_mcp_private_browser_payment",
            "network": "regtest",
            "actual_shielded_receipt_confirmed": True,
            "confirmed_zat": 100000,
            "mcp_stdio": True,
            "private_browser_approval_and_decryption": True,
            "wallet_and_merchant_http": True,
            "identical_retry_no_second_payment": True,
            "unauthorized_product_blocked": True,
            "revocation": True,
            "real_goods_delivered": False,
            "public_funds_moved": False,
            "tor_verified": False,
            "deployment": "same-host integration proof; no OS-isolation claim",
        }
        (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)
        merchant.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--funding-state", required=True)
    parser.add_argument("--browser")
    asyncio.run(main(parser.parse_args()))
