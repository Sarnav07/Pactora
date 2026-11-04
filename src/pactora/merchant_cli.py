"""Operator-only controlled test merchant launcher."""

import argparse
import json
import os

from .test_merchant import TestMerchant, create_merchant_app
from .wallet import ZecPyWallet
from .wallet_cli import protected_file, protected_wallet_directory


def main():
    parser = argparse.ArgumentParser(description="Pactora watch-only controlled Zcash test merchant")
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    cfg = json.loads(protected_file(args.config))
    os.umask(0o077)
    protected_wallet_directory(cfg["wallet_directory"])
    adapter = ZecPyWallet.open(
        cfg["wallet_directory"],
        mnemonic=None,
        server=cfg["server"],
        regtest_local=cfg.get("regtest_local", False),
    )
    merchant = TestMerchant(
        adapter._wallet,
        cfg["state_directory"],
        amount_zat=cfg.get("amount_zat", 100000),
        confirmations=cfg.get("confirmations", 1),
    )
    import uvicorn

    uvicorn.run(
        create_merchant_app(merchant, cfg["api_token"]),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="critical",
    )


if __name__ == "__main__":
    main()
