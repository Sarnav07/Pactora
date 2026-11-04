"""Signed deterministic mandates and a conservative durable purchase ledger."""

import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from .crypto import canonical, digest, unb64
from .engine import Refused
from .models import StrictModel


class Mandate(StrictModel):
    domain: str = Field(pattern="^veilcart-mandate-v1$")
    reference: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    version: int = Field(ge=1, le=1)
    wallet_id: str = Field(min_length=1, max_length=128)
    network: str = Field(pattern="^(test|regtest)$")
    merchant: str = Field(min_length=1, max_length=128)
    # Canonical product/package fingerprints, created from trusted discovery results.
    eligible: list[str] = Field(min_length=1, max_length=20)
    per_purchase_cents: int = Field(gt=0)
    total_cents: int = Field(gt=0)
    per_purchase_zat: int = Field(gt=0)
    total_zat: int = Field(gt=0)
    max_purchases: int = Field(gt=0, le=100)
    expires_at: int = Field(gt=0)


def product_key(product, package):
    return digest({"product": product, "package": package})


class MandateBook:
    def __init__(self, directory, cipher, public_key):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.cipher = cipher
        self.authority = Ed25519PublicKey.from_public_bytes(unb64(public_key))
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            directory / "mandates.sqlite", check_same_thread=False, isolation_level=None
        )
        os.chmod(directory / "mandates.sqlite", 0o600)
        self.db.executescript("""
            PRAGMA synchronous=FULL;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS mandates(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS purchases(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def _get(self, table, reference):
        row = self.db.execute(f"SELECT payload FROM {table} WHERE id=?", (reference,)).fetchone()
        if row is None:
            raise Refused("unknown_reference")
        return self.cipher.decrypt(row[0], table + reference)

    def _put(self, table, reference, value):
        self.db.execute(
            f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
            (reference, self.cipher.encrypt(value, table + reference)),
        )

    def install(self, document, signature):
        mandate = Mandate.model_validate(document)
        try:
            self.authority.verify(unb64(signature), canonical(document))
        except (InvalidSignature, ValueError, TypeError):
            raise Refused("mandate_signature_invalid") from None
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.db.execute(
                    "SELECT id FROM mandates WHERE id=?", (mandate.reference,)
                ).fetchone()
                if existing:
                    old = self._get("mandates", mandate.reference)
                    if old["document"] != document:
                        raise Refused("mandate_immutable")
                    # Never reset reservations or undo revocation on repeated registration.
                else:
                    self._put(
                        "mandates",
                        mandate.reference,
                        {"document": document, "revoked": False, "cents": 0, "zat": 0, "count": 0},
                    )
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return mandate.reference

    def status(self, reference):
        with self.lock:
            value = self._get("mandates", reference)
            state = (
                "revoked"
                if value["revoked"]
                else ("expired" if value["document"]["expires_at"] <= int(time.time()) else "approved")
            )
            return {"reference": reference, "status": state}

    def revoke(self, reference):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                value = self._get("mandates", reference)
                value["revoked"] = True
                self._put("mandates", reference, value)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def lookup(self, mandate_ref, purchase_ref, selection):
        reference = digest({"mandate": mandate_ref, "purchase": purchase_ref})
        with self.lock:
            row = self.db.execute("SELECT id FROM purchases WHERE id=?", (reference,)).fetchone()
            if not row:
                return None
            value = self._get("purchases", reference)
            if value["selection"] != selection:
                raise Refused("purchase_reference_changed")
            return value

    def reserve(
        self,
        mandate_ref,
        purchase_ref,
        selection,
        *,
        merchant,
        wallet_id,
        network,
        product,
        package,
        cents,
        zat,
        quote_expires,
        operation=None,
    ):
        if not purchase_ref or len(purchase_ref) > 128:
            raise Refused("purchase_reference_required")
        reference = digest({"mandate": mandate_ref, "purchase": purchase_ref})
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                previous = self.lookup(mandate_ref, purchase_ref, selection)
                if previous:
                    self.db.execute("COMMIT")
                    return previous, False
                value = self._get("mandates", mandate_ref)
                m = Mandate.model_validate(value["document"])
                now = int(time.time())
                if value["revoked"] or m.expires_at <= now or quote_expires <= now:
                    raise Refused("mandate_or_quote_inactive")
                if (m.wallet_id, m.network, m.merchant) != (wallet_id, network, merchant):
                    raise Refused("mandate_binding_mismatch")
                if product_key(product, package) not in m.eligible:
                    raise Refused("product_not_permitted")
                if type(cents) is not int or type(zat) is not int or cents <= 0 or zat <= 0:
                    raise Refused("invalid_total")
                if (
                    cents > m.per_purchase_cents
                    or zat > m.per_purchase_zat
                    or value["cents"] + cents > m.total_cents
                    or value["zat"] + zat > m.total_zat
                    or value["count"] >= m.max_purchases
                ):
                    raise Refused("mandate_limit_exceeded")
                value["cents"] += cents
                value["zat"] += zat
                value["count"] += 1
                record = {
                    "reference": reference,
                    "operation": operation or secrets.token_urlsafe(24),
                    "selection": selection,
                    "status": "reserved",
                }
                self._put("mandates", mandate_ref, value)
                self._put("purchases", reference, record)
                self.db.execute("COMMIT")
                return record, True
            except BaseException as exc:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                if isinstance(exc, Refused) and not self.lookup(mandate_ref, purchase_ref, selection):
                    self._put(
                        "purchases",
                        reference,
                        {
                            "reference": reference,
                            "operation": operation or secrets.token_urlsafe(24),
                            "selection": selection,
                            "status": "refused",
                        },
                    )
                raise

    def operation_status(self, operation):
        with self.lock:
            for (ref,) in self.db.execute("SELECT id FROM purchases"):
                value = self._get("purchases", ref)
                if value["operation"] == operation:
                    status = value["status"]
                    return {
                        "reference": operation,
                        "status": ("requires_private_attention" if status == "reserved" else status),
                    }
        raise Refused("unknown_operation")

    def finish(self, reference, status):
        with self.lock:
            value = self._get("purchases", reference)
            value["status"] = status
            self._put("purchases", reference, value)
