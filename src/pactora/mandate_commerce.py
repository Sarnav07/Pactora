"""Trusted discovery-to-invoice mapping. Live settlement remains closed."""

import asyncio
import os
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field

from .crypto import b64, canonical, digest, seal_to_device, unb64, validate_device_key
from .engine import Refused
from .mandates import Mandate, MandateBook, product_key
from .models import Product, Quote, StrictModel
from .providers import GateClosed
from .wallet_bridge import WalletBridge
from .wallet_cli import protected_file


class MandateRequest(StrictModel):
    search_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    per_purchase_cents: int = Field(gt=0, le=500)
    total_cents: int = Field(gt=0, le=500)
    per_purchase_zat: int = Field(gt=0)
    total_zat: int = Field(gt=0)
    max_purchases: int = Field(gt=0, le=100)
    duration_seconds: int = Field(gt=0, le=3600)


class MandateApproval(StrictModel):
    draft_hash: str = Field(pattern="^[a-f0-9]{64}$")
    device_public_key: str = Field(min_length=100, max_length=8192)


class PurchaseRequest(StrictModel):
    search_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    option: int = Field(ge=0, le=19)
    purchase_ref: str = Field(min_length=1, max_length=128)


class MandateCommerce:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        self.lock = asyncio.Lock()
        self.authority = None
        cfg = engine.settings
        self.wallet = (
            WalletBridge(cfg.wallet_service_url, cfg.wallet_api_token_file)
            if cfg.wallet_service_url
            else None
        )
        if cfg.mandate_signing_key_file:
            self.authority = Ed25519PrivateKey.from_private_bytes(
                unb64(protected_file(cfg.mandate_signing_key_file))
            )
        elif cfg.provider == "simulator":
            path = cfg.data_dir / "simulator-approval-key"
            if not path.exists():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    output.write(b64(Ed25519PrivateKey.generate().private_bytes_raw()))
            self.authority = Ed25519PrivateKey.from_private_bytes(unb64(protected_file(path)))
        self.book = (
            MandateBook(
                cfg.data_dir / "mandates",
                self.store.cipher,
                b64(self.authority.public_key().public_bytes_raw()),
            )
            if self.authority
            else None
        )
        self.store.db.execute("CREATE TABLE IF NOT EXISTS mandate_views(id TEXT PRIMARY KEY, payload TEXT)")

    def _require(self):
        if not self.authority:
            raise Refused("mandate_authority_not_provisioned")

    def _save(self, ref, value):
        with self.store.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO mandate_views VALUES (?,?)",
                (ref, self.store.cipher.encrypt(value, "mandate-view" + ref)),
            )

    def view(self, ref):
        row = self.store.db.execute("SELECT payload FROM mandate_views WHERE id=?", (ref,)).fetchone()
        if row is None:
            raise Refused("unknown_mandate")
        return self.store.cipher.decrypt(row[0], "mandate-view" + ref)

    def views(self):
        return [
            {"reference": row[0], **self.view(row[0])}
            for row in self.store.db.execute("SELECT id FROM mandate_views")
        ]

    def draft(self, request):
        self._require()
        job = self.engine.private_job(request.search_ref)
        if "details" not in job:
            raise Refused("search_unavailable")
        if request.total_cents > self.engine.settings.live_cap_cents:
            raise Refused("aggregate_cap_exceeded")
        products = [p for p in job["details"]["products"] if p["price_cents"] <= request.per_purchase_cents]
        if not products:
            raise Refused("no_eligible_products")
        ref = secrets.token_urlsafe(24)
        document = Mandate(
            domain="veilcart-mandate-v1",
            reference=ref,
            version=1,
            wallet_id=self.engine.settings.wallet_id,
            network=self.engine.settings.wallet_network,
            merchant=self.engine.settings.provider,
            eligible=[product_key(p["id"], p["package"]) for p in products],
            per_purchase_cents=request.per_purchase_cents,
            total_cents=request.total_cents,
            per_purchase_zat=request.per_purchase_zat,
            total_zat=request.total_zat,
            max_purchases=request.max_purchases,
            expires_at=int(time.time()) + request.duration_seconds,
        ).model_dump()
        self._save(
            ref,
            {
                "document": document,
                "products": products,
                "state": "awaiting_approval",
                "draft_hash": digest(document),
                "receipts": [],
            },
        )
        return {
            "reference": ref,
            "status": "awaiting_private_approval",
            "private_url": self.engine.settings.origin + "/",
        }

    async def approve(self, ref, body):
        self._require()
        value = self.view(ref)
        if value["state"] != "awaiting_approval" or body.draft_hash != value["draft_hash"]:
            raise Refused("draft_changed_or_used")
        if value["document"]["expires_at"] <= int(time.time()):
            raise Refused("mandate_expired")
        validate_device_key(body.device_public_key)
        signature = b64(self.authority.sign(canonical(value["document"])))
        if self.wallet:
            await self.wallet.call("/mandates", {"document": value["document"], "signature": signature})
        self.book.install(value["document"], signature)
        value.update(state="approved", signature=signature, device_key=body.device_public_key)
        self._save(ref, value)
        return self.status(ref)

    def status(self, ref):
        value = self.view(ref)
        if value["state"] == "awaiting_approval":
            return {"reference": ref, "status": "awaiting_private_approval"}
        if value["state"] == "revoked":
            return {"reference": ref, "status": "revoked"}
        return self.book.status(ref)

    async def revoke(self, ref):
        value = self.view(ref)
        if value["state"] == "awaiting_approval":
            value["state"] = "revoked"
        else:
            # Do not report revocation complete until the signing boundary has persisted it.
            if self.wallet:
                await self.wallet.call("/mandates/" + ref + "/revoke")
            self.book.revoke(ref)
            value["state"] = "revoked"
        self._save(ref, value)
        return {"reference": ref, "status": "revoked"}

    def recover_receipts(self, ref):
        value = self.view(ref)
        delivered = value.setdefault("delivered", {})
        for purchase, result in value.get("recovery", {}).items():
            if purchase not in delivered:
                delivered[purchase] = seal_to_device(result, value["device_key"])
        value["receipts"] = list(delivered.values())
        # Save delivery before clearing recovery; restarting never calls the merchant again.
        self._save(ref, value)
        for purchase in delivered:
            self.book.finish(purchase, "completed")
        value["recovery"] = {}
        self._save(ref, value)
        return {"reference": ref, "status": "delivery_recovered"}

    async def purchase(self, ref, request):
        async with self.lock:
            self._require()
            # Never permit direct model-supplied invoices or recipients.
            selection = digest(request.model_dump(exclude={"purchase_ref"}))
            previous = self.book.lookup(ref, request.purchase_ref, selection)
            if previous:
                return {
                    "reference": previous["operation"],
                    "status": previous["status"],
                    "environment": self.engine.provider.name,
                }
            if self.engine.settings.provider == "test_merchant":
                return await self._purchase_test(ref, request, selection)
            if self.engine.settings.provider != "simulator":
                raise GateClosed("live_mandate_settlement_disabled")
            value = self.view(ref)
            if value["state"] != "approved":
                raise Refused("mandate_not_approved")
            job = self.engine.private_job(request.search_ref)
            try:
                product = Product.model_validate(job["details"]["products"][request.option])
            except (KeyError, IndexError):
                raise Refused("selection_unavailable") from None
            quote = await self.engine.provider.quote(product, self.engine.settings.checkout_mode)
            # Quotes are trusted typed adapter output. Refuse a substituted item or stale route.
            if quote.product != product or not quote.simulated or quote.destination_asset != "SIMULATED-USDC":
                raise Refused("quote_binding_changed")
            record, fresh = self.book.reserve(
                ref,
                request.purchase_ref,
                selection,
                merchant="simulator",
                wallet_id=self.engine.settings.wallet_id,
                network="test",
                product=product.id,
                package=product.package,
                cents=quote.total_cents,
                zat=quote.max_debit_zat,
                quote_expires=quote.expires_at,
            )
            if not fresh:
                raise Refused("purchase_already_reserved")
            try:
                with self.store.transaction() as db:
                    spent = db.execute("SELECT value FROM meta WHERE key='spent_cents'").fetchone()[0]
                    reserved = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs").fetchone()[0]
                    if spent + reserved + quote.total_cents > self.engine.settings.live_cap_cents:
                        raise Refused("global_cap_exceeded")
                    db.execute("UPDATE meta SET value=value+? WHERE key='spent_cents'", (quote.total_cents,))
                result = await self.engine.provider.execute(quote, record["operation"])
                # Save recovery plaintext encrypted before device encryption (never re-execute).
                value = self.view(ref)
                value.setdefault("recovery", {})[record["reference"]] = result
                self._save(ref, value)
                self.recover_receipts(ref)
            except BaseException:
                self.book.finish(record["reference"], "requires_private_attention")
                raise Refused("requires_private_attention") from None
            return {
                "reference": record["operation"],
                "status": "completed",
                "environment": self.engine.provider.name,
            }

    async def _purchase_test(self, ref, request, selection):
        if not self.wallet:
            raise Refused("protected_wallet_required")
        value = self.view(ref)
        if value["state"] != "approved":
            raise Refused("mandate_not_approved")
        job = self.engine.private_job(request.search_ref)
        try:
            product = Product.model_validate(job["details"]["products"][request.option])
        except (KeyError, IndexError):
            raise Refused("selection_unavailable") from None
        operation = secrets.token_urlsafe(24)
        quote = await self.engine.provider.quote_for(product, operation)
        record, fresh = self.book.reserve(
            ref,
            request.purchase_ref,
            selection,
            merchant="test_merchant",
            wallet_id=self.engine.settings.wallet_id,
            network=self.engine.settings.wallet_network,
            product=product.id,
            package=product.package,
            cents=quote.total_cents,
            zat=quote.max_debit_zat,
            quote_expires=quote.expires_at,
            operation=operation,
        )
        if not fresh:
            raise Refused("purchase_already_reserved")
        try:
            with self.store.transaction() as db:
                spent = db.execute("SELECT value FROM meta WHERE key='spent_cents'").fetchone()[0]
                reserved = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs").fetchone()[0]
                if spent + reserved + quote.total_cents > self.engine.settings.live_cap_cents:
                    raise Refused("global_cap_exceeded")
                db.execute("UPDATE meta SET value=value+? WHERE key='spent_cents'", (quote.total_cents,))
            payload = {
                "purchase_ref": request.purchase_ref,
                "package": product.package,
                "total_cents": quote.total_cents,
                "quote_expires": quote.expires_at,
                "binding": {
                    "merchant": "test_merchant",
                    "invoice": quote.invoice_id,
                    "product": product.id,
                    "destination": quote.deposit_address,
                    "network": self.engine.settings.wallet_network,
                    "amount_zat": quote.source_zat,
                    "max_debit_zat": quote.max_debit_zat,
                    "expires_at": min(quote.expires_at, value["document"]["expires_at"]),
                },
            }
            # Persist exact retry envelope before contacting the signing boundary.
            value.setdefault("pending", {})[record["reference"]] = {
                "quote": quote.model_dump(),
                "payload": payload,
                "operation": operation,
            }
            self._save(ref, value)
            await self.recover_test_payments(ref)
        except Exception:
            self.book.finish(record["reference"], "requires_private_attention")
            raise Refused("requires_private_attention") from None
        current = self.book.lookup(ref, request.purchase_ref, selection)
        return {"reference": operation, "status": current["status"], "environment": self.engine.provider.name}

    async def recover_test_payments(self, ref):
        if self.engine.settings.provider != "test_merchant":
            return
        if not self.wallet:
            raise Refused("protected_wallet_required")
        value = self.view(ref)
        for purchase, pending in list(value.get("pending", {}).items()):
            # This reuses the identical wallet envelope. The wallet is the durable
            # idempotency authority, including after a lost HTTP response or restart.
            result = await self.wallet.call("/mandates/" + ref + "/purchase", pending["payload"])
            wallet_ref = result.get("reference")
            if result.get("state") == "signed":
                await self.wallet.call("/operations/" + wallet_ref + "/recover")
            if result.get("state") not in ("signed", "broadcast"):
                self.book.finish(purchase, "requires_private_attention")
                continue
            receipt = await self.engine.provider.confirmed(Quote.model_validate(pending["quote"]))
            if receipt is None:
                self.book.finish(purchase, "awaiting_test_confirmation")
                continue
            value.setdefault("recovery", {})[purchase] = receipt
            del value["pending"][purchase]
            self._save(ref, value)
            self.recover_receipts(ref)
            value = self.view(ref)
