"""Separate real FROST shielded regtest payment. No Pactora mandate enforcement claim.

Use successful 2-of-2 DKG state, a private regtest miner and the official tools.
The proof coordinator/participants share one host; this is not host isolation.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tomllib
from pathlib import Path

from native_payment import HEIGHTS, SERVER, rpc
from zecpy import Wallet
from zecpy.cold import WatchBundle

from pactora.test_merchant import InvoiceRequest, TestMerchant


async def main(args):
    os.umask(0o077)
    state = Path(args.state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    dkg = Path(args.dkg).resolve()
    if not json.loads((dkg / "report.json").read_text()).get("distributed_key_generation"):
        raise RuntimeError("successful DKG proof required")
    tools = Path(args.tools).resolve()
    helper = Path(args.view_helper).resolve()
    configs = {p: tomllib.loads((dkg / (p + ".toml")).read_text()) for p in ("alice", "bob")}
    group = next(iter(configs["alice"]["group"]))
    if group not in configs["bob"]["group"]:
        raise RuntimeError("group mismatch")
    generated = subprocess.run(
        [str(tools / "zcash-sign"), "generate", "--ak", group, "-n", "test"],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r'Unified Full Viewing Key: "([^"]+)"', generated.stdout)
    if not match:
        raise RuntimeError("FROST view generation did not produce expected output")
    (state / "test.ufvk").write_text(match.group(1))
    subprocess.run([str(helper), "ufvk", str(state / "test.ufvk"), str(state / "regtest.ufvk")], check=True)
    # Group-derived identifier is watch-account metadata, not a recoverable seed.
    bundle = WatchBundle(
        "regtest", (state / "regtest.ufvk").read_text(), hashlib.sha256(bytes.fromhex(group)).hexdigest(), 0
    )
    watch = await Wallet.watch(state / "watch", bundle, server=SERVER, tor=False, regtest_heights=HEIGHTS)
    funding = Path(args.funding_state).resolve()
    miner = Wallet.open(
        funding / "miner", server=SERVER, mnemonic=(funding / "miner.mnemonic").read_text(), tor=False
    )
    await miner.sync()
    await miner.send_proposal(miner.propose(watch.address(), 2000000))
    rpc("generate", [20])
    await watch.sync()
    receiver, phrase = await Wallet.create(
        state / "receiver", network="regtest", server=SERVER, regtest_heights=HEIGHTS, tor=False
    )
    (state / "receiver.mnemonic").write_text(phrase.reveal())
    del receiver
    receiver = Wallet.open(state / "receiver", server=SERVER, tor=False)
    merchant = TestMerchant(receiver, state / "merchant", amount_zat=100000)
    invoice = merchant.invoice(
        InvoiceRequest(
            operation=secrets.token_urlsafe(24), product="test-voucher", package="one test voucher"
        )
    )
    unsigned = state / "unsigned.pczt"
    unsigned.write_bytes(watch.propose_cold(invoice["address"], 100000))
    signed = state / "signed.pczt"
    env = {
        **os.environ,
        "SSL_CERT_FILE": str(dkg / "trust.pem"),
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
    }
    processes = []
    logs = []

    def start(name, cmd, **kwargs):
        log = open(state / (name + ".log"), "wb")
        logs.append(log)
        proc = subprocess.Popen(cmd, stderr=log, stdout=log, env=env, cwd=state, **kwargs)
        processes.append(proc)
        return proc

    try:
        server = start(
            "server",
            [
                str(tools / "frostd"),
                "--ip",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--tls-cert",
                str(dkg / "tls.pem"),
                "--tls-key",
                str(dkg / "tls.key"),
            ],
        )
        for _ in range(30):
            if server.poll() is not None:
                raise RuntimeError("FROST server failed")
            try:
                with socket.create_connection(("127.0.0.1", args.port), timeout=1):
                    break
            except OSError:
                await asyncio.sleep(0.2)
        error_log = open(state / "zcash-sign.log", "wb")
        logs.append(error_log)
        signer = subprocess.Popen(
            [str(tools / "zcash-sign"), "sign", "-n", "test", "--tx-plan", str(unsigned), "-o", str(signed)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error_log,
            text=True,
            env=env,
        )
        processes.append(signer)
        sighash = None
        randomizers = []
        while True:
            line = signer.stdout.readline()
            if not line:
                raise RuntimeError("PCZT signing compatibility failed; inspect private logs")
            if line.startswith("SIGHASH:"):
                sighash = bytes.fromhex(line.split(":", 1)[1].strip())
            if line.startswith("Randomizer #"):
                randomizers.append(bytes.fromhex(line.split(":", 1)[1].strip()))
            if line.startswith("Input hex-encoded signature"):
                break
        if sighash is None or not randomizers:
            raise RuntimeError("missing real spend signing data")
        client = str(tools / "frost-client")
        coord = [
            client,
            "coordinator",
            "-c",
            str(dkg / "alice.toml"),
            "--server-url",
            f"127.0.0.1:{args.port}",
            "--group",
            group,
            "-S",
            ",".join(configs[p]["communication_key"]["pubkey"] for p in ("alice", "bob")),
        ]
        signatures = []
        for i, randomizer in enumerate(randomizers):
            message = state / f"message-{i}"
            message.write_bytes(sighash)
            alpha = state / f"alpha-{i}"
            alpha.write_bytes(randomizer)
            signature = state / f"signature-{i}"
            signatures.append(signature)
            coord.extend(["-m", str(message), "-r", str(alpha), "-o", str(signature)])
        coordinator = start("coordinator", coord, stdin=subprocess.DEVNULL)
        await asyncio.sleep(1)
        alice = start(
            "participant-alice",
            [
                client,
                "participant",
                "-c",
                str(dkg / "alice.toml"),
                "--server-url",
                f"127.0.0.1:{args.port}",
                "--group",
                group,
            ],
            stdin=subprocess.PIPE,
        )
        await asyncio.sleep(2)
        if coordinator.poll() is not None or any(p.exists() for p in signatures):
            raise RuntimeError("unexpected signature before second participant")
        bob = start(
            "participant-bob",
            [
                client,
                "participant",
                "-c",
                str(dkg / "bob.toml"),
                "--server-url",
                f"127.0.0.1:{args.port}",
                "--group",
                group,
            ],
            stdin=subprocess.PIPE,
        )
        # Test participants approve only the exact sighash extracted from this PCZT.
        # This is not an autonomous production policy signer.
        for participant, process in (("alice", alice), ("bob", bob)):
            log_file = state / ("participant-" + participant + ".log")
            for _ in range(1800):
                content = log_file.read_text()
                messages = re.findall(r"Message to be signed \(hex-encoded\):\s*([0-9a-f]+)", content)
                if messages:
                    if any(message != sighash.hex() for message in messages):
                        raise RuntimeError("participant received an unexpected transaction digest")
                    process.stdin.write(("y\n" * len(randomizers)).encode())
                    process.stdin.flush()
                    break
                if process.poll() is not None:
                    raise RuntimeError("participant exited before digest confirmation")
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("participant confirmation did not arrive")
        for process in (coordinator, alice, bob):
            if process.wait(timeout=180) != 0:
                raise RuntimeError("threshold signing failed; inspect private logs")
        values = [p.read_bytes() for p in signatures]
        if any(len(value) != 64 for value in values):
            raise RuntimeError("invalid signature length")
        signer.communicate("".join(value.hex() + "\n" for value in values), timeout=120)
        if signer.returncode != 0:
            raise RuntimeError("transaction signature application failed")
        # Native extraction verifies the completed transaction and stores it before broadcast.
        txid = await watch.broadcast_signed(signed.read_bytes())
        (state / "transaction-id").write_text(txid)
        rpc("generate", [1])
        receipt = await merchant.status(invoice["reference"])
        if receipt["status"] != "paid":
            raise RuntimeError("threshold payment not confirmed")
        report = {
            "proof": "frost_shielded_payment",
            "network": "regtest",
            "threshold": 2,
            "participants": 2,
            "dkg_used": True,
            "single_participant_did_not_complete_session": True,
            "threshold_signatures_applied_and_verified": True,
            "actual_shielded_receipt_confirmed": True,
            "confirmed_zat": receipt["confirmed_zat"],
            "policy_enforced_by_frost": False,
            "bitrefill_used": False,
            "public_funds_moved": False,
            "tor_verified": False,
            "notice": "separate single-host threshold protocol proof, not deployed signer isolation",
        }
        (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in logs:
            log.close()
        merchant.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--dkg", required=True)
    parser.add_argument("--tools", required=True)
    parser.add_argument("--funding-state", required=True)
    parser.add_argument("--view-helper", required=True)
    parser.add_argument("--port", type=int, default=2744)
    asyncio.run(main(parser.parse_args()))
