"""Testnet-only ZecPy adapter; never imported by the model-facing MCP process.

Live commerce intentionally cannot activate this adapter until the conversion
route is verified. Pending/uncertain sends must never be reconstructed as new sends.
"""

import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .crypto import digest
from .engine import Refused


@dataclass(frozen=True)
class PreparedPayment:
    reference: str
    approval_hash: str
    amount_zat: int
    fee_zat: int
    max_debit_zat: int
    proposal: object = field(repr=False, compare=False)


class ZecPyWallet:
    def __init__(self, wallet):
        if wallet.network not in ("test", "regtest"):
            raise Refused("mainnet_wallet_gate_closed")
        self._wallet = wallet
        self._plans = {}

    @classmethod
    def open(cls, path, *, mnemonic, server="https://testnet.zec.rocks:443", regtest_local=False):
        parsed = urlsplit(server)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Refused("wallet_endpoint_invalid")
        if local and not regtest_local:
            raise Refused("loopback_requires_regtest_mode")
        if not local and (regtest_local or parsed.scheme != "https" or not parsed.hostname):
            raise Refused("wallet_endpoint_invalid")
        # Optional native dependency: installed only on the protected wallet host.
        from zecpy import Wallet

        adapter = cls(Wallet.open(path, mnemonic=mnemonic, server=server, tor=True))
        if regtest_local and adapter._wallet.network != "regtest":
            raise Refused("loopback_requires_regtest_mode")
        return adapter

    async def sync(self):
        await self._wallet.sync()

    def prepare(self, destination, amount_zat, max_debit_zat):
        if type(amount_zat) is not int or type(max_debit_zat) is not int or amount_zat <= 0:
            raise Refused("invalid_amount")
        proposal = self._wallet.propose(
            destination, amount_zat, allow_transparent=False, allow_pool_crossing=False
        )
        if proposal.paying_out != amount_zat or proposal.fee < 0:
            raise Refused("proposal_changed")
        if proposal.crossing_value:
            raise Refused("public_pool_crossing")
        if amount_zat + proposal.fee > max_debit_zat:
            raise Refused("fee_cap_exceeded")
        reference = secrets.token_urlsafe(24)
        approval_hash = digest(
            {
                "reference": reference,
                "destination": destination,
                "amount_zat": amount_zat,
                "fee_zat": proposal.fee,
                "max_debit_zat": max_debit_zat,
                "network": self._wallet.network,
            }
        )
        plan = PreparedPayment(reference, approval_hash, amount_zat, proposal.fee, max_debit_zat, proposal)
        self._plans[reference] = plan
        return plan

    async def execute(self, plan, *, approved_hash, durable_claim):
        """Legacy in-process adapter, not an independent authorization boundary.

        Production backend callers must use WalletService, which verifies signed
        approvals and owns its durable journal. This method is not exposed by that API.
        `durable_claim` must commit a once-only operation BEFORE signing begins.

        Caller persists encrypted recovery context and later txid. On broadcast
        uncertainty the claim stays consumed; restart never recreates the payment.
        """
        current = self._plans.get(plan.reference)
        if current is not plan or approved_hash != plan.approval_hash:
            raise Refused("approval_invalid_or_used")
        if not durable_claim(plan.reference, plan.approval_hash):
            raise Refused("approval_invalid_or_used")
        del self._plans[plan.reference]
        return await self._wallet.send_proposal(plan.proposal)
