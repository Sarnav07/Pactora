"""Start a loopback-only private chain using the verified official Zebra binary.

The base image supplies Linux/glibc only; its normal database entrypoint is not run.
Requires Docker Desktop. No wallets or public-chain funds are accessed.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--tools", default=".tools")
    parser.add_argument("--base-image", default="postgres:15")
    args = parser.parse_args()
    state = Path(args.state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    tools = Path(args.tools).resolve()
    downloads = tools / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    arch = "aarch64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    archive_name = f"zebrad-7.0.0-{arch}-unknown-linux-gnu.tar.gz"
    base = "https://github.com/ZcashFoundation/zebra/releases/download/v7.0.0/"
    for name in ("SHA256SUMS", archive_name):
        path = downloads / name
        if not path.exists():
            with urllib.request.urlopen(base + name, timeout=120) as response:
                path.write_bytes(response.read())
    expected = next(
        line.split()[0]
        for line in (downloads / "SHA256SUMS").read_text().splitlines()
        if line.split()[-1].lstrip("*") == archive_name
    )
    if hashlib.sha256((downloads / archive_name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Zebra release checksum mismatch")
    binary = tools / "zebra-linux"
    binary.mkdir(exist_ok=True)
    with tarfile.open(downloads / archive_name) as archive:
        archive.extractall(binary, filter="data")
    existing = subprocess.run(["docker", "inspect", "pactora-regtest"], capture_output=True)
    if existing.returncode == 0:
        raise RuntimeError("pactora-regtest already exists; refusing to replace it")
    (state / "zebra").mkdir()
    (state / "zebrad.toml").write_text("""[network]
network = "Regtest"
listen_addr = "0.0.0.0:18344"
[network.testnet_parameters.activation_heights]
Canopy = 1
NU5 = 1
NU6 = 1
"NU6.1" = 1
"NU6.2" = 1
"NU6.3" = 1
[mining]
miner_address = "tmJymvcUCn1ctbghvTJpXBwHiMEB8P6wxNV"
[rpc]
listen_addr = "0.0.0.0:18232"
lightwalletd_listen_addr = "0.0.0.0:19067"
enable_cookie_auth = false
[state]
cache_dir = "/state/zebra"
[tracing]
use_color = false
""")
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "pactora-regtest",
            "--label",
            "dev.pactora.proof=regtest",
            "--entrypoint",
            "/proof/zebrad",
            "--mount",
            f"type=bind,src={binary},dst=/proof,readonly",
            "--mount",
            f"type=bind,src={state},dst=/state",
            "-p",
            "127.0.0.1:18232:18232",
            "-p",
            "127.0.0.1:19067:19067",
            args.base_image,
            "-c",
            "/state/zebrad.toml",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    info = json.loads(
        subprocess.run(["docker", "inspect", "pactora-regtest"], check=True, capture_output=True).stdout
    )[0]
    report = {
        "validator": "Zebra 7.0.0",
        "archive_sha256": expected,
        "base_image_id": info["Image"],
        "network": "regtest",
        "rpc_host": "127.0.0.1:18232",
        "grpc_host": "127.0.0.1:19067",
        "lightwallet_service": "Zebra built-in gRPC",
        "public_funds_moved": False,
    }
    (state / "node-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
