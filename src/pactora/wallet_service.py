"""Private, testnet-only signing boundary. This module is never imported by MCP."""

import asyncio
import fcntl
import os
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from .crypto import PrivateStoreCipher, canonical, digest, unb64
from .engine import Refused
from .mandates import MandateBook
from .wallet import ZecPyWallet


class PaymentBinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    merchant: str = Field(min_length=1, max_length=256)
    invoice: str = Field(min_length=1, max_length=256)
    product: str = Field(min_length=1, max_length=256)
    destination: str = Field(min_length=1, max_length=512)
    network: str = Field(pattern="^(test|regtest)$")
    amount_zat: int = Field(gt=0, le=2_100_000_000_000_000)
    max_debit_zat: int = Field(gt=0, le=2_100_000_000_000_000)
    expires_at: int = Field(gt=0)


class WalletService:
    """Single-process owner, encrypted journal, one-time Ed25519 approvals.

    Callers are trusted backend processes, never the model. The authority's private
    approval key must live outside both this service and the agent.
    """

    def __init__(
        self,
        wallet,
        directory,
        encryption_key,
        approval_public_key,
        aggregate_cap_zat,
        wallet_id="test-wallet",
    ):
        if type(aggregate_cap_zat) is not int or aggregate_cap_zat <= 0:
            raise ValueError("positive aggregate cap required")
        self.adapter = ZecPyWallet(wallet)
        if not all(callable(getattr(wallet, m, None)) for m in ("sign_proposal", "rebroadcast_transaction")):
            raise Refused("native_recovery_api_required")
        self.cap = aggregate_cap_zat
        self.authority = Ed25519PublicKey.from_public_bytes(unb64(approval_public_key))
        self.cipher = PrivateStoreCipher(encryption_key)
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid():
            raise ValueError("wallet state must be owned by service user")
        directory.chmod(0o700)
        self.owner = open(directory / "owner.lock", "a+")
        os.chmod(directory / "owner.lock", 0o600)
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            raise Refused("wallet_service_already_running") from None
        self.db = sqlite3.connect(directory / "journal.sqlite")
        os.chmod(directory / "journal.sqlite", 0o600)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, state TEXT, payload TEXT)"
        )
        # RAM proposals cannot be reconstructed safely; in-flight signing may have succeeded.
        self.db.execute("UPDATE operations SET state='quarantined' WHERE state IN ('prepared','signing')")
        self.db.commit()
        self.wallet_id = wallet_id
        self.mandates = MandateBook(directory / "mandates", self.cipher, approval_public_key)
        self.plans = {}
        self.lock = asyncio.Lock()

    def close(self):
        self.mandates.close()
        self.db.close()
        self.owner.close()

    def _load(self, reference):
        row = self.db.execute("SELECT state,payload FROM operations WHERE id=?", (reference,)).fetchone()
        if not row:
            raise Refused("unknown_operation")
        return row[0], self.cipher.decrypt(row[1], reference)

    def _save(self, reference, state, data):
        self.db.execute(
            "INSERT OR REPLACE INTO operations VALUES (?,?,?)",
            (reference, state, self.cipher.encrypt(data, reference)),
        )
        self.db.commit()

    async def sync(self):
        async with self.lock:
            try:
                await self.adapter.sync()
            except Exception:
                raise Refused("protected_wallet_sync_unavailable") from None
            return {"state": "synced", "environment": self.adapter._wallet.network}

    async def prepare(self, binding: PaymentBinding):
        async with self.lock:
            if binding.network != self.adapter._wallet.network or binding.expires_at <= int(time.time()):
                raise Refused("network_or_expiry_invalid")
            plan = self.adapter.prepare(binding.destination, binding.amount_zat, binding.max_debit_zat)
            # The service uses its own reference and authenticated full binding, not adapter hashes.
            reference = secrets.token_urlsafe(32)
            approval = {
                "domain": "veilcart-wallet-approval-v1",
                "reference": reference,
                **binding.model_dump(),
                "fee_zat": plan.fee_zat,
                "total_zat": plan.amount_zat + plan.fee_zat,
            }
            self.plans[reference] = plan
            self.adapter._plans.pop(plan.reference)
            self._save(reference, "prepared", {"approval": approval})
            return approval

    def _verify(self, approval, signature):
        try:
            self.authority.verify(unb64(signature), canonical(approval))
        except (InvalidSignature, ValueError, TypeError):
            raise Refused("approval_invalid") from None

    def _reserved(self):
        total = 0
        for reference, state, payload in self.db.execute("SELECT id,state,payload FROM operations"):
            data = self.cipher.decrypt(payload, reference)
            if data.get("reserved"):
                total += data["approval"]["total_zat"]
        return total

    async def execute(self, reference, signature):
        async with self.lock:
            state, data = self._load(reference)
            self._verify(data["approval"], signature)
            if state != "prepared":
                raise Refused("approval_invalid_or_used")
            if data["approval"]["expires_at"] <= int(time.time()):
                raise Refused("approval_expired")
            # Verify protected connectivity and refresh notes before entering signing.
            try:
                await self.adapter.sync()
            except Exception:
                raise Refused("protected_wallet_sync_unavailable") from None
            if data["approval"]["expires_at"] <= int(time.time()):
                raise Refused("approval_expired")
            if self._reserved() + data["approval"]["total_zat"] > self.cap:
                raise Refused("aggregate_cap_exceeded")
            plan = self.plans.pop(reference, None)
            if plan is None:
                raise Refused("proposal_unavailable")
            data["reserved"] = True
            self._save(reference, "signing", data)
            return await self._sign_and_broadcast(reference, data, plan)

    async def _sign_and_broadcast(self, reference, data, plan):
        try:
            txid = await self.adapter._wallet.sign_proposal(plan.proposal)
            data["txid"] = txid
            self._save(reference, "signed", data)
        except BaseException:
            self._save(reference, "quarantined", data)
            raise Refused("signing_outcome_uncertain") from None
        await self._broadcast(reference, data)
        return self.status(reference)

    async def purchase_under_mandate(
        self, mandate_ref, purchase_ref, binding, package, total_cents, quote_expires
    ):
        # Invoice/product/recipient mapping is attested by the authenticated trusted
        # merchant adapter, never by an MCP caller. The wallet enforces the mandate.
        selection = digest(
            {
                "binding": binding.model_dump(),
                "package": package,
                "cents": total_cents,
                "quote_expires": quote_expires,
            }
        )
        async with self.lock:
            old = self.mandates.lookup(mandate_ref, purchase_ref, selection)
            if old:
                try:
                    return self.status(old["operation"])
                except Refused:
                    return {"reference": old["operation"], "state": "quarantined"}
            if binding.network != self.adapter._wallet.network:
                raise Refused("network_invalid")
            try:
                await self.adapter.sync()
            except Exception:
                raise Refused("protected_wallet_sync_unavailable") from None
            if binding.expires_at <= int(time.time()):
                raise Refused("approval_expired")
            plan = self.adapter.prepare(binding.destination, binding.amount_zat, binding.max_debit_zat)
            self.adapter._plans.pop(plan.reference)
            total = plan.amount_zat + plan.fee_zat
            if self._reserved() + total > self.cap:
                raise Refused("aggregate_cap_exceeded")
            record, fresh = self.mandates.reserve(
                mandate_ref,
                purchase_ref,
                selection,
                merchant=binding.merchant,
                wallet_id=self.wallet_id,
                network=binding.network,
                product=binding.product,
                package=package,
                cents=total_cents,
                zat=total,
                quote_expires=min(quote_expires, binding.expires_at),
                operation=plan.reference,
            )
            if not fresh:
                raise Refused("purchase_already_reserved")
            data = {
                "approval": {**binding.model_dump(), "fee_zat": plan.fee_zat, "total_zat": total},
                "reserved": True,
                "mandate": mandate_ref,
                "purchase": record["reference"],
            }
            self._save(plan.reference, "signing", data)
            return await self._sign_and_broadcast(plan.reference, data, plan)

    async def _broadcast(self, reference, data):
        try:
            result = await self.adapter._wallet.rebroadcast_transaction(data["txid"])
            if result != data["txid"]:
                raise ValueError("transaction changed")
        except Exception:
            self._save(reference, "signed", data)
            return
        self._save(reference, "broadcast", data)

    async def recover(self, reference):
        async with self.lock:
            state, data = self._load(reference)
            if state != "signed":
                raise Refused("operation_not_rebroadcastable")
            await self._broadcast(reference, data)
            return self.status(reference)

    async def revoke(self, reference):
        async with self.lock:
            state, data = self._load(reference)
            if state != "prepared":
                raise Refused("already_signed_or_unavailable")
            self.plans.pop(reference, None)
            self._save(reference, "revoked", data)
            return self.status(reference)

    def status(self, reference):
        state, _ = self._load(reference)
        return {"reference": reference, "state": state, "environment": self.adapter._wallet.network}

    def private_record(self, reference):
        """Trusted private UI/operator only; deliberately not an HTTP or MCP operation."""
        return self._load(reference)

    @staticmethod
    def approval_fingerprint(approval):
        return digest(approval)
