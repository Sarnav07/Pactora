import argparse
import asyncio
import base64
import getpass
import json
import os
import secrets
from pathlib import Path

from .config import Settings
from .crypto import password_hash
from .providers import RouteProbe


def load_config(path):
    data = json.loads(Path(path).read_text())
    for k, v in data.items():
        os.environ[k] = str(v)


def main():
    parser = argparse.ArgumentParser(description="Pactora protected service (simulator by default)")
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--directory", type=Path, required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    probe = sub.add_parser("probe-route")
    probe.add_argument("--proxy", default="socks5h://127.0.0.1:9050")
    bitrefill = sub.add_parser("probe-bitrefill")
    bitrefill.add_argument("--config", type=Path, required=True)
    bitrefill.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "init":
        directory = args.directory.resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        password = getpass.getpass("Private-view password (12+ characters): ")
        data = {
            "PACTORA_DATA": str(directory / "state"),
            "PACTORA_PROVIDER": "simulator",
            "PACTORA_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
            "PACTORA_GATEWAY_KEY": secrets.token_urlsafe(32),
            "PACTORA_PASSWORD_HASH": password_hash(password),
            "PACTORA_ORIGIN": "http://127.0.0.1:8787",
        }
        path = directory / "config.json"
        with path.open("x") as f:
            os.chmod(path, 0o600)
            json.dump(data, f, indent=2)
        print(f"Simulator config created: {path}. Keep it outside the agent's filesystem.")
    elif args.action == "serve":
        load_config(args.config)
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(Settings.from_env()), host=args.host, port=args.port, access_log=False)
    elif args.action == "probe-bitrefill":
        from .bitrefill_probe import run_probe
        from .network import ProviderError

        try:
            print(json.dumps(asyncio.run(run_probe(args.config, args.output)), indent=2))
        except (ProviderError, OSError, ValueError):
            print(
                json.dumps({"safe_balance_checkout_verified": False, "error": "protected_probe_unavailable"})
            )
            raise SystemExit(1)
    else:
        from .network import ProviderError

        try:
            print(json.dumps(asyncio.run(RouteProbe(args.proxy).inspect()), indent=2))
        except ProviderError:
            print(json.dumps({"settlement_verified": False, "error": "protected_route_unavailable"}))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
