from types import SimpleNamespace

import pytest

from pactora.engine import Refused
from pactora.wallet import ZecPyWallet


class FakeWallet:
    network = "test"
    calls = 0
    fee = 10_000

    def propose(self, destination, amount, **flags):
        assert flags == {"allow_transparent": False, "allow_pool_crossing": False}
        return SimpleNamespace(paying_out=amount, fee=self.fee, crossing_value=0, canonical_crossing=False)

    async def send_proposal(self, proposal):
        self.calls += 1
        return "test-only-txid"


def test_fee_cap_includes_wallet_fee():
    adapter = ZecPyWallet(FakeWallet())
    with pytest.raises(Refused, match="fee_cap"):
        adapter.prepare("test-only-address", 100_000, 100_000)


def test_mainnet_is_closed():
    wallet = FakeWallet()
    wallet.network = "main"
    with pytest.raises(Refused, match="mainnet"):
        ZecPyWallet(wallet)


async def test_exact_proposal_only_once_with_durable_claim():
    wallet = FakeWallet()
    adapter = ZecPyWallet(wallet)
    plan = adapter.prepare("test-only-address", 100_000, 110_000)
    claimed = set()

    def claim(reference, approval_hash):
        if reference in claimed:
            return False
        claimed.add(reference)
        return True

    with pytest.raises(Refused):
        await adapter.execute(plan, approved_hash="forged", durable_claim=claim)
    await adapter.execute(plan, approved_hash=plan.approval_hash, durable_claim=claim)
    with pytest.raises(Refused):
        await adapter.execute(plan, approved_hash=plan.approval_hash, durable_claim=claim)
    assert wallet.calls == 1


async def test_refused_claim_never_signs():
    wallet = FakeWallet()
    adapter = ZecPyWallet(wallet)
    plan = adapter.prepare("test-only-address", 100_000, 110_000)
    with pytest.raises(Refused):
        await adapter.execute(plan, approved_hash=plan.approval_hash, durable_claim=lambda *args: False)
    assert wallet.calls == 0


@pytest.mark.parametrize(
    "server,regtest",
    [
        ("http://remote.example:80", False),
        ("http://127.0.0.1:19067", False),
        ("https://remote.example", True),
        ("https://user:password@remote.example", False),
    ],
)
def test_endpoint_policy_before_native_import(server, regtest):
    with pytest.raises(Refused):
        ZecPyWallet.open("unused", mnemonic="unused", server=server, regtest_local=regtest)
