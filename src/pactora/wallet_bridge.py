"""Backend-only connection to the independently protected wallet service."""

from urllib.parse import urlsplit

import httpx

from .engine import Refused
from .wallet_cli import protected_file


class WalletBridge:
    def __init__(self, url, token_file):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("invalid wallet endpoint")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        ):
            raise ValueError("wallet bridge requires HTTPS or a protected loopback tunnel")
        self.url = url
        self.token_file = token_file

    async def call(self, path, body=None, *, method="POST"):
        try:
            token = protected_file(self.token_file)
            async with httpx.AsyncClient(
                base_url=self.url, trust_env=False, follow_redirects=False, timeout=30
            ) as client:
                response = await client.request(
                    method, path, json=body, headers={"Authorization": "Bearer " + token}
                )
            if response.status_code != 200:
                raise Refused("wallet_bridge_unavailable")
            return response.json()
        except (OSError, ValueError, httpx.HTTPError):
            raise Refused("wallet_bridge_unavailable") from None
