"""Provision the existing ZecPy regtest test fixture from the private proof miner.

Only reads a generated regtest mnemonic from an ignored directory; never prints it.
"""

import argparse
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--funding-state", required=True)
    parser.add_argument("--devtool", required=True)
    parser.add_argument("--devnet-home", required=True)
    parser.add_argument("--activation-heights", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(args.devnet_home).resolve()
    (root / "bin").mkdir(parents=True, exist_ok=True, mode=0o700)
    wallets = root / "wallets"
    wallets.mkdir(exist_ok=True, mode=0o700)
    binary = Path(args.devtool).resolve()
    link = root / "bin/zcash-devtool"
    if not link.exists():
        link.symlink_to(binary)
    if (wallets / "miner").exists():
        raise SystemExit("miner fixture already exists; refusing to overwrite")
    phrase = (Path(args.funding_state) / "miner.mnemonic").read_text()
    command = [
        str(binary),
        "wallet",
        "-w",
        "miner",
        "init",
        "--name",
        "miner",
        "-i",
        "miner.age",
        "-n",
        "regtest",
        "--activation-heights",
        str(Path(args.activation_heights).resolve()),
        "--birthday",
        "2",
        "-s",
        "127.0.0.1:19067",
    ]
    result = subprocess.run(
        command, input=phrase + "\n", text=True, capture_output=True, cwd=wallets, timeout=120
    )
    (wallets / "provision.log").write_text(result.stderr)
    if result.returncode:
        raise SystemExit("fixture provisioning failed; inspect private provision.log")
    print("Provisioned private regtest miner fixture; mnemonic never printed")


if __name__ == "__main__":
    main()
