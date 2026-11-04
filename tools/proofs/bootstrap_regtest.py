"""Start a dedicated loopback regtest using verified/local binaries and cached images.

No public-chain wallet is opened. Never replaces an existing container or state.
Run the native-payment proof afterward; it provisions its own miner before mining.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import time
import tomllib
from pathlib import Path

from native_payment import rpc

ROOT = Path(__file__).resolve().parents[2]


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout


def main(args):
    os.umask(0o077)
    state = Path(args.state).resolve()
    for port in (18232, 19067):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"port {port} is occupied; refusing to replace another runtime") from None
    for name in ("pactora-regtest", "pactora-regtest-lwd"):
        found = docker("ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.Names}}")
        if found.strip():
            raise SystemExit("existing proof container found; inspect/reuse it instead of overwriting")
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    (state / "zebra").mkdir(mode=0o700)
    (state / "lwd").mkdir(mode=0o700)
    tools = Path(args.tools).resolve()
    config = tomllib.loads((Path(args.dkg) / "alice.toml").read_text())
    group = next(iter(config["group"]))
    generated = subprocess.run(
        [str(tools / "zcash-sign"), "generate", "--ak", group, "-n", "test"],
        capture_output=True,
        text=True,
        check=True,
    )
    address = re.search(r'Orchard-only unified address: "([^"]+)"', generated.stdout)
    if address is None:
        raise RuntimeError("bootstrap address generation failed")
    source, destination = state / "bootstrap-test.address", state / "bootstrap-regtest.address"
    source.write_text(address.group(1))
    subprocess.run(
        [str(tools / "pactora-proof-view-network"), "address", str(source), str(destination)], check=True
    )
    template = (ROOT / ".tools/zecpy/devnet/zebrad.toml.in").read_text()
    for key, value in {
        "MINER": destination.read_text().strip(),
        "STATE": "/proof-state/zebra",
        "P2P": "127.0.0.1:18233",
        "RPC": "127.0.0.1:18232",
    }.items():
        template = template.replace("@" + key + "@", value)
    (state / "zebrad.toml").write_text(template)
    common = [
        "--network",
        "host",
        "--label",
        "dev.pactora.proof=regtest",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]
    docker(
        "run",
        "-d",
        "--name",
        "pactora-regtest",
        *common,
        "--mount",
        f"type=bind,src={state},dst=/proof-state",
        "--mount",
        f"type=bind,src={ROOT / '.tools/zebra/zebrad'},dst=/proof-tools/zebrad,readonly",
        "--entrypoint",
        "/proof-tools/zebrad",
        args.node_image,
        "-c",
        "/proof-state/zebrad.toml",
        "start",
    )
    for _ in range(60):
        try:
            rpc("getblockcount")
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("node startup failed; inspect the dedicated container privately")
    rpc("generate", [3])
    docker(
        "run",
        "-d",
        "--name",
        "pactora-regtest-lwd",
        *common,
        "--mount",
        f"type=bind,src={state / 'lwd'},dst=/proof-lwd",
        "--entrypoint",
        "/usr/local/bin/lightwalletd",
        args.lwd_image,
        "--rpchost",
        "127.0.0.1",
        "--rpcport",
        "18232",
        "--rpcuser",
        "devnet",
        "--rpcpassword",
        "devnet",
        "--grpc-bind-addr",
        "127.0.0.1:19067",
        "--http-bind-addr",
        "127.0.0.1:19068",
        "--no-tls-very-insecure",
        "--data-dir",
        "/proof-lwd",
        "--log-file",
        "/proof-lwd/server.log",
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", 19067), timeout=1):
                break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError("lightwalletd startup failed; inspect its private logs")
    report = {
        "network": "regtest",
        "loopback_only": True,
        "public_funds_moved": False,
        "node_image": args.node_image,
        "lwd_image": args.lwd_image,
    }
    (state / "bootstrap-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--dkg", required=True)
    parser.add_argument("--tools", default=".tools/native-target/debug")
    parser.add_argument("--node-image", default="ghcr.io/zcashlabs/thus-spoke-zakura-app:0.4.1")
    parser.add_argument("--lwd-image", default="ghcr.io/zcashlabs/thus-spoke-zakura-lightwalletd:0.4.1")
    main(parser.parse_args())
