"""Protected wallet runner. Configuration and mnemonic files belong to the service user."""

import argparse
import json
import os
import stat
from pathlib import Path

from .wallet import ZecPyWallet
from .wallet_api import create_wallet_app
from .wallet_service import WalletService


def protected_file(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("secret file must be regular, owner-only and owned by service user")
    return path.read_text().strip()


def protected_wallet_directory(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("wallet directory must be owner-only and owned by service user")


def main():
    parser = argparse.ArgumentParser(description="Pactora protected testnet wallet service")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    cfg = json.loads(protected_file(args.config))
    os.umask(0o077)
    protected_wallet_directory(cfg["wallet_directory"])
    wallet = ZecPyWallet.open(
        cfg["wallet_directory"],
        mnemonic=protected_file(cfg["mnemonic_file"]),
        server=cfg["server"],
        regtest_local=cfg.get("regtest_local", False),
    )
    service = WalletService(
        wallet._wallet,
        cfg["state_directory"],
        cfg["encryption_key"],
        cfg["approval_public_key"],
        cfg["aggregate_cap_zat"],
        wallet_id=cfg.get("wallet_id", "test-wallet"),
    )
    import uvicorn

    uvicorn.run(
        create_wallet_app(service, cfg["api_token"]),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="critical",
    )


if __name__ == "__main__":
    main()
