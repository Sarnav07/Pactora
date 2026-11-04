"""Operator-only native regtest dashboard rehearsal. No mainnet or real goods.

Creates fresh demo wallets, funds them from an existing private regtest miner,
then runs merchant, wallet and private dashboard as separate loopback processes.
This single-host harness is NOT production isolation. Never run it from a shopping agent.
"""

import argparse
import asyncio
import contextlib
import getpass
import json
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

from regtest_rpc import rpc, wait_for_node

from pactora.crypto import b64, password_hash
from pactora.wallet_cli import protected_file

ROOT = Path(__file__).resolve().parents[2]
SERVER = "http://127.0.0.1:19067"
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


def save(path, value):
    with path.open("x") as output:
        path.chmod(0o600)
        output.write(json.dumps(value, indent=2) if isinstance(value, dict) else value)


def check_container(node_state):
    info = json.loads(
        subprocess.run(["docker", "inspect", "pactora-regtest"], capture_output=True, check=True).stdout
    )[0]
    if info["Config"].get("Labels", {}).get("dev.pactora.proof") != "regtest":
        raise RuntimeError("Only the owned pactora-regtest container may be used")
    if 'network = "Regtest"' not in (node_state / "zebrad.toml").read_text():
        raise RuntimeError("Private regtest configuration required")
    if not info["State"]["Running"]:
        subprocess.run(["docker", "start", "pactora-regtest"], check=True, capture_output=True)


async def provision(args, state):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from zecpy import Wallet

    if state.exists():
        raise RuntimeError("State already exists. Use --resume; never erase a payment journal to retry")
    await wait_for_node()
    state.mkdir(parents=True, mode=0o700)
    funding = Path(args.funding_state).resolve()
    miner = Wallet.open(
        funding / "miner", server=SERVER, mnemonic=protected_file(funding / "miner.mnemonic"), tor=False
    )
    await miner.sync()
    sender, phrase = await Wallet.create(
        state / "sender", network="regtest", server=SERVER, tor=False, regtest_heights=HEIGHTS
    )
    save(state / "sender.mnemonic", phrase.reveal())
    await miner.send_proposal(miner.propose(sender.address(), 2000000))
    rpc("generate", [20])
    await sender.sync()
    receiver, phrase = await Wallet.create(
        state / "receiver", network="regtest", server=SERVER, tor=False, regtest_heights=HEIGHTS
    )
    del sender, receiver, miner, phrase
    authority = Ed25519PrivateKey.generate()
    save(state / "authority.key", b64(authority.private_bytes_raw()))
    wallet_token, merchant_token, gateway_token = (secrets.token_urlsafe(32) for _ in range(3))
    save(state / "wallet.token", wallet_token)
    save(state / "merchant.token", merchant_token)
    save(
        state / "wallet.json",
        {
            "wallet_directory": str(state / "sender"),
            "mnemonic_file": str(state / "sender.mnemonic"),
            "state_directory": str(state / "signer"),
            "server": SERVER,
            "regtest_local": True,
            "encryption_key": b64(secrets.token_bytes(32)),
            "approval_public_key": b64(authority.public_key().public_bytes_raw()),
            "aggregate_cap_zat": 1000000,
            "wallet_id": "demo-regtest-wallet",
            "api_token": wallet_token,
        },
    )
    save(
        state / "merchant.json",
        {
            "wallet_directory": str(state / "receiver"),
            "state_directory": str(state / "merchant"),
            "server": SERVER,
            "regtest_local": True,
            "api_token": merchant_token,
        },
    )
    password = (
        "demo-only-pactora-2026"
        if args.demo_password
        else getpass.getpass("Private-view password (12+ characters): ")
    )
    if len(password) < 12:
        raise RuntimeError(
            "Password must have at least 12 characters. State retained; do not fund again blindly"
        )
    origin = "http://127.0.0.1:" + str(args.port)
    save(
        state / "backend.json",
        {
            "PACTORA_DATA": str(state / "commerce"),
            "PACTORA_MASTER_KEY": b64(secrets.token_bytes(32)),
            "PACTORA_GATEWAY_KEY": gateway_token,
            "PACTORA_PASSWORD_HASH": password_hash(password),
            "PACTORA_ORIGIN": origin,
            "PACTORA_PROVIDER": "test_merchant",
            "PACTORA_WALLET_NETWORK": "regtest",
            "PACTORA_WALLET_ID": "demo-regtest-wallet",
            "PACTORA_WALLET_URL": "http://127.0.0.1:" + str(args.wallet_port),
            "PACTORA_WALLET_TOKEN_FILE": str(state / "wallet.token"),
            "PACTORA_TEST_MERCHANT_URL": "http://127.0.0.1:" + str(args.merchant_port),
            "PACTORA_TEST_MERCHANT_TOKEN_FILE": str(state / "merchant.token"),
            "PACTORA_MANDATE_KEY_FILE": str(state / "authority.key"),
        },
    )
    save(state / "gateway.json", {"executor_url": origin, "gateway_key": gateway_token})
    save(
        state / "launcher.json",
        {"port": args.port, "wallet_port": args.wallet_port, "merchant_port": args.merchant_port},
    )


async def main(args):
    os.umask(0o077)
    state = Path(args.state).resolve()
    check_container(Path(args.node_state).resolve())
    if not args.resume:
        await provision(args, state)
    else:
        cfg = json.loads(protected_file(state / "launcher.json"))
        args.port, args.wallet_port, args.merchant_port = (
            cfg[k] for k in ("port", "wallet_port", "merchant_port")
        )
        await wait_for_node()
    # Prevent duplicate launchers and accidental second writers.
    import fcntl

    lock = (state / "launcher.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    children, logs = [], []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        specs = [
            ("pactora.merchant_cli", "merchant.json", args.merchant_port),
            ("pactora.wallet_cli", "wallet.json", args.wallet_port),
            ("pactora.cli", "backend.json", args.port),
        ]
        for module, filename, port in specs:
            log = (state / (module.rsplit(".", 1)[-1] + ".log")).open("a")
            logs.append(log)
            command = [sys.executable, "-m", module]
            if module == "pactora.cli":
                command.append("serve")
            command += ["--config", str(state / filename), "--port", str(port)]
            children.append(subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log))
        import httpx

        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            ready = False
            for _ in range(60):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A demo service exited; inspect owner-only logs privately")
                try:
                    h = await client.get(f"http://127.0.0.1:{args.port}/health")
                    w = await client.get(
                        f"http://127.0.0.1:{args.wallet_port}/overview",
                        headers={"Authorization": "Bearer " + protected_file(state / "wallet.token")},
                    )
                    m = await client.get(
                        f"http://127.0.0.1:{args.merchant_port}/catalog",
                        headers={"Authorization": "Bearer " + protected_file(state / "merchant.token")},
                    )
                    ready = h.status_code == w.status_code == m.status_code == 200
                    if ready:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
            if not ready:
                raise RuntimeError("Demo services did not become ready. State retained for recovery")
        print(f"Native regtest dashboard: http://127.0.0.1:{args.port}/app", flush=True)
        print(f"Gateway configuration path (do not display contents): {state / 'gateway.json'}", flush=True)
        print(
            "Test funds only. No real goods, Bitrefill settlement, FROST integration or Tor proof.",
            flush=True,
        )
        if args.demo_password:
            print("Public test-only password: demo-only-pactora-2026", flush=True)
        print(
            "Operator block generation enabled."
            if args.mine_confirmations
            else "Mine confirmations manually from the operator terminal.",
            flush=True,
        )
        while not stop.is_set():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A demo service stopped. State retained; no payment will be replayed")
            if args.mine_confirmations:
                await asyncio.to_thread(rpc, "generate", [1])
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5)
    finally:
        for child in reversed(children):
            child.terminate()
        for child in children:
            try:
                await asyncio.to_thread(child.wait, timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait)
        for log in logs:
            log.close()
        lock.close()
        print(
            "Demo services stopped. Wallets and payment journals preserved. Regtest node left running.",
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--node-state", default="proof-state/regtest")
    parser.add_argument("--funding-state", default="proof-state/native-payment-2")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--wallet-port", type=int, default=8790)
    parser.add_argument("--merchant-port", type=int, default=8791)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--demo-password", action="store_true", help="Public test-only password; no real funds"
    )
    parser.add_argument(
        "--mine-confirmations",
        action="store_true",
        help="Operator mines a private regtest block every 5 seconds",
    )
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
