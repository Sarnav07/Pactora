import httpx
import pytest

from pactora.mcp_server import build_server
from pactora.models import Product
from pactora.network import ProtectedHTTP, ProviderError
from pactora.providers import Bitrefill, GateClosed


async def test_no_direct_fallback(monkeypatch):
    calls = []

    class BrokenClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            raise httpx.ConnectError("Tor is down")

    monkeypatch.setattr(httpx, "AsyncClient", BrokenClient)
    with pytest.raises(ProviderError):
        await ProtectedHTTP("socks5h://127.0.0.1:9050").request("GET", "https://api.bitrefill.com/v2/ping")
    assert len(calls) == 1 and calls[0]["proxy"].startswith("socks5h:")
    assert calls[0]["trust_env"] is False and calls[0]["follow_redirects"] is False


def test_tor_stream_isolation_credentials_are_fresh():
    from urllib.parse import urlsplit

    protected = ProtectedHTTP("socks5h://127.0.0.1:9050")
    a, b = urlsplit(protected.isolated_proxy()), urlsplit(protected.isolated_proxy())
    assert a.username and a.password and a.username != b.username
    assert a.hostname == b.hostname == "127.0.0.1"
    assert a.port == b.port == 9050


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bitrefill.com/",
        "https://127.0.0.1/",
        "https://evil.example/",
        "https://api.bitrefill.com.evil.example/",
        "https://key@api.bitrefill.com/",
    ],
)
async def test_arbitrary_destinations_refused(url):
    with pytest.raises(ProviderError):
        await ProtectedHTTP("socks5h://127.0.0.1:9050").request("GET", url)


async def test_live_gate_cannot_be_enabled_by_model(settings):
    provider = Bitrefill(settings)
    product = Product(
        id="anything", name="Anything", price_cents=100, country="IN", package="1", restrictions=""
    )
    for mode in ("guest", "account"):
        with pytest.raises(GateClosed):
            await provider.quote(product, mode)


async def test_mcp_tools_have_no_vault_or_payment_backdoor(app, settings):
    server = build_server("http://127.0.0.1:8787", settings.gateway_key, httpx.ASGITransport(app=app))
    tools = await server.list_tools()
    assert {t.name for t in tools} == {
        "search_products",
        "purchase_status",
        "choose_in_chat",
        "request_mandate",
        "mandate_status",
        "request_purchase",
    }
    # Exercise the SDK's real tool dispatch, not a duplicate test helper.
    result = await server.call_tool(
        "search_products", {"query": "gift cards", "country": "IN", "budget_cents": 500}
    )
    text = str(result)
    assert "Demo dining voucher" in text and "SIMULATOR" in text
    assert "SIM-INVOICE" not in text and "SIM-CODE" not in text


async def test_mcp_reference_cannot_escape_path(app, settings):
    server = build_server("http://127.0.0.1:8787", settings.gateway_key, httpx.ASGITransport(app=app))
    result = await server.call_tool("purchase_status", {"reference": "../api/jobs"})
    assert "requires_private_attention" in str(result)
