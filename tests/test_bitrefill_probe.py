import pytest

from pactora.bitrefill_probe import BitrefillProbe
from pactora.network import ProviderError


@pytest.mark.parametrize(
    "method,params",
    [("tools/call", {"name": "buy-products"}), ("tools/call", {"name": "update-order"}), ("anything", {})],
)
async def test_probe_never_debits(method, params):
    probe = BitrefillProbe("socks5h://127.0.0.1:9050", "unused")
    with pytest.raises(ProviderError, match="forbidden"):
        await probe.rpc(method, params)
