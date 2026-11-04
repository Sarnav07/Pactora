"""All third-party HTTP is proxied. There is no retry using a direct transport."""

import secrets
from urllib.parse import urlsplit, urlunsplit

import httpx


class ProviderError(Exception):
    pass


class ProtectedHTTP:
    ALLOWED = frozenset({"api.bitrefill.com", "1click.chaindefuser.com"})

    def __init__(self, proxy: str):
        u = urlsplit(proxy)
        if u.scheme != "socks5h" or u.hostname not in ("127.0.0.1", "localhost", "tor"):
            raise ValueError("a trusted socks5h proxy is required")
        self.proxy = proxy

    def isolated_proxy(self):
        """Tor must enable IsolateSOCKSAuth; unique credentials isolate each call."""
        u = urlsplit(self.proxy)
        auth = secrets.token_hex(16) + ":" + secrets.token_hex(16)
        host = u.hostname + (":" + str(u.port) if u.port else "")
        return urlunsplit((u.scheme, auth + "@" + host, "", "", ""))

    async def request(self, method: str, url: str, **kwargs):
        u = urlsplit(url)
        if (
            u.scheme != "https"
            or u.hostname not in self.ALLOWED
            or u.username
            or u.password
            or u.port not in (None, 443)
            or u.fragment
        ):
            raise ProviderError("destination refused")
        try:
            async with httpx.AsyncClient(
                proxy=self.isolated_proxy(), trust_env=False, follow_redirects=False, timeout=20.0
            ) as client:
                r = await client.request(method, url, **kwargs)
            if not 200 <= r.status_code < 300:
                raise ProviderError("provider request failed")
            if len(r.content) > 1_000_000:
                raise ProviderError("provider response too large")
            return r.json()
        except (httpx.HTTPError, ValueError):
            # Never forward provider bodies, URLs or headers to a model or log.
            raise ProviderError("provider unavailable on the protected route") from None
