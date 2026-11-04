"""Trusted discovery-to-invoice mapping. Live settlement remains closed."""

import asyncio
import os
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field

from .crypto import b64, canonical, digest, seal_to_device, unb64, validate_device_key
from .engine import Refused
from .fulfillment import assess_delivery, new_delivery
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
        values = [
            {"reference": row[0], **self.view(row[0])}
            for row in self.store.db.execute("SELECT id FROM mandate_views")
        ]
        for value in values:
            if (
                value["state"] not in ("revoked", "approved")
                and value["document"]["expires_at"] <= time.time()
            ):
                value["state"] = "expired"
            if value["state"] == "approved":
                usage = self.book._get("mandates", value["reference"])
                value["usage"] = {k: usage[k] for k in ("cents", "zat", "count")}
                d = value["document"]
                if d["expires_at"] <= time.time():
                    value["state"] = "expired"
                elif (
                    usage["count"] >= d["max_purchases"]
                    or usage["cents"] >= d["total_cents"]
                    or usage["zat"] >= d["total_zat"]
                ):
                    value["state"] = "exhausted"
        # Expose only the status and encrypted envelope needed by the private UI.
        for value in values:
            value["deliveries"] = {
                purchase: {
                    **{
                        key: delivery[key]
                        for key in ("payment", "fulfillment", "private_delivery", "refund", "reason", "issue")
                        if key in delivery
                    },
                    "expected": {"product": delivery["expected"]["product"]},
                    "receipt": value.get("delivered", {}).get(purchase),
                }
                for purchase, delivery in value.get("deliveries", {}).items()
            }
        # Do not send signing material or backend recovery plaintext to the browser.
        return [
            {
                k: v
                for k, v in value.items()
                if k
                not in (
                    "signature",
                    "device_key",
                    "pending",
                    "recovery",
                    "delivered",
                )
            }
            for value in values
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
        if (
            value["state"] not in ("awaiting_approval", "registration_pending")
            or body.draft_hash != value["draft_hash"]
        ):
            raise Refused("draft_changed_or_used")
        if value["state"] == "registration_pending" and body.device_public_key != value["device_key"]:
            raise Refused("approval_device_changed")
        if value["document"]["expires_at"] <= int(time.time()):
            raise Refused("mandate_expired")
        validate_device_key(body.device_public_key)
        signature = b64(self.authority.sign(canonical(value["document"])))
        # Persist the user's approval before the remote wallet can activate it.
        # A lost response must remain revocable even before local installation.
        value.update(state="registration_pending", signature=signature, device_key=body.device_public_key)
        self._save(ref, value)
        if self.wallet:
            await self.wallet.call("/mandates", {"document": value["document"], "signature": signature})
        self.book.install(value["document"], signature)
        value.update(state="approved", signature=signature, device_key=body.device_public_key)
        self._save(ref, value)
        return self.status(ref)

    def status(self, ref):
        value = self.view(ref)
        if value["state"] == "revoked":
            return {"reference": ref, "status": "revoked"}
        if value["document"]["expires_at"] <= int(time.time()):
            return {"reference": ref, "status": "expired"}
        if value["state"] == "awaiting_approval":
            return {"reference": ref, "status": "awaiting_private_approval"}
        if value["state"] == "registration_pending":
            return {"reference": ref, "status": "registration_pending"}
        return self.book.status(ref)

    async def revoke(self, ref):
        value = self.view(ref)
        if value["state"] == "awaiting_approval":
            value["state"] = "revoked"
        else:
            # Do not report revocation complete until the signing boundary has persisted it.
            if self.wallet:
                if value["state"] == "registration_pending":
                    await self.wallet.call(
                        "/mandates", {"document": value["document"], "signature": value["signature"]}
                    )
                await self.wallet.call("/mandates/" + ref + "/revoke")
            self.book.install(value["document"], value["signature"])
            self.book.revoke(ref)
            value["state"] = "revoked"
        self._save(ref, value)
        return {"reference": ref, "status": "revoked"}

    def recover_receipts(self, ref):
        value = self.view(ref)
        delivered = value.setdefault("delivered", {})
        for purchase, result in value.get("recovery", {}).items():
            if purchase not in delivered:
                delivery = value.get("deliveries", {}).get(purchase)
                if delivery is None:
                    # Older stored results predate expected-deliverable binding.
                    # Keep their recovery data for private operator reconciliation.
                    continue
                if delivery.get("reason") == "delivery_timeout_review_existing_order":
                    continue
                state, reason = assess_delivery(delivery["expected"], result)
                delivery.update(fulfillment=state, reason=reason)
                if state not in ("simulator_issued", "not_applicable"):
                    self.book.finish(purchase, "requires_private_attention")
                    continue
                delivered[purchase] = seal_to_device(result, value["device_key"])
                delivery["private_delivery"] = "encrypted_stored"
        value["receipts"] = list(delivered.values())
        # Save delivery before clearing recovery; restarting never calls the merchant again.
        self._save(ref, value)
        for purchase in delivered:
            status = (
                "requires_private_attention"
                if value.get("deliveries", {}).get(purchase, {}).get("issue")
                else "completed"
            )
            self.book.finish(purchase, status)
            for decision in self.store.decisions():
                if decision.get("purchase_key") == purchase:
                    self.store.decision(
                        decision["id"],
                        {
                            "state": status,
                            "reason": (
                                "Simulated purchase completed"
                                if self.engine.settings.provider == "simulator"
                                else "Shielded test payment confirmed by receiver"
                            )
                            if status == "completed"
                            else "requires_private_attention",
                        },
                    )
        value["recovery"] = {
            purchase: result
            for purchase, result in value.get("recovery", {}).items()
            if purchase not in delivered
        }
        self._save(ref, value)
        return {"reference": ref, "status": "delivery_recovered"}

    def delivery_action(self, ref, purchase, action):
        value = self.view(ref)
        delivery = value.get("deliveries", {}).get(purchase)
        if delivery is None:
            raise Refused("unknown_delivery")
        if action in ("accessible", "acknowledged"):
            if purchase not in value.get("delivered", {}):
                raise Refused("delivery_not_stored")
            if action == "acknowledged" and delivery["private_delivery"] not in (
                "accessible",
                "acknowledged",
            ):
                raise Refused("decrypt_receipt_first")
            if delivery["private_delivery"] != "acknowledged":
                delivery["private_delivery"] = action
        else:
            delivery["issue"] = {"reason": action, "reported_at": int(time.time())}
            delivery["refund"] = "operator_review_required"
            self.book.finish(purchase, "requires_private_attention")
        self._save(ref, value)
        return {"status": "recorded"}

    async def reconcile_deliveries(self, ref):
        """Bounded reads of existing operations only; never checkout or execute."""
        value = self.view(ref)
        now = int(time.time())
        for purchase, delivery in value.get("deliveries", {}).items():
            if delivery["fulfillment"] != "pending" or delivery["next_poll"] > now:
                continue
            if now >= delivery["deadline"] or delivery["attempts"] >= 12:
                delivery.update(
                    fulfillment="private_attention", reason="delivery_timeout_review_existing_order"
                )
                continue
            delivery["attempts"] += 1
            delivery["next_poll"] = now + min(300, 15 * 2 ** min(delivery["attempts"], 5))
            # Commit the attempt first so restarts cannot produce a polling storm.
            self._save(ref, value)
            try:
                result = await self.engine.provider.reconcile(
                    Quote.model_validate(delivery["quote"]), delivery["expected"]["operation"]
                )
                if result is not None:
                    value.setdefault("recovery", {})[purchase] = result
            except Exception:
                delivery["reason"] = "provider_reconciliation_unavailable"
        self._save(ref, value)
        return self.recover_receipts(ref)

    async def tick(self):
        await self.poll_confirmations()
        async with self.lock:
            for item in self.views():
                ref = item["reference"]
                try:
                    await self.reconcile_deliveries(ref)
                except Exception:
                    # Preserve encrypted context and all reservations for private recovery.
                    continue

    async def loop(self):
        while True:
            try:
                await self.tick()
            except Exception:
                pass  # A transient observer failure must not stop future reconciliation.
            await asyncio.sleep(2)

    async def purchase(self, ref, request):
        decision = digest({"mandate": ref, **request.model_dump()})
        item = {
            "intent": ref,
            "state": "pending",
            "reason": "Checking approved limits",
            "purchase_key": digest({"mandate": ref, "purchase": request.purchase_ref}),
        }
        try:
            job = self.engine.private_job(request.search_ref)
            product = job["details"]["products"][request.option]
            item.update(product=product["name"], cents=product["price_cents"])
        except (Refused, KeyError, IndexError):
            item.update(product="Unavailable selection")
        self.store.decision(decision, item)
        try:
            result = await self._purchase(ref, request)
        except Exception as exc:
            # Codes are private and allowlisted; never persist arbitrary exception text.
            reason = str(exc) if isinstance(exc, Refused) else "requires_private_attention"
            known = {
                "signing_paused",
                "mandate_not_approved",
                "mandate_expired",
                "mandate_revoked",
                "mandate_limit_exceeded",
                "mandate_binding_changed",
                "mandate_product_not_eligible",
                "selection_changed",
                "selection_unavailable",
                "global_cap_exceeded",
                "requires_private_attention",
                "product_not_permitted",
                "mandate_or_quote_inactive",
                "mandate_binding_mismatch",
                "purchase_reference_changed",
            }
            self.store.decision(
                decision,
                {
                    "state": "attention"
                    if reason not in known or reason == "requires_private_attention"
                    else "refused",
                    "reason": reason if reason in known else "requires_private_attention",
                },
            )
            raise
        self.store.decision(
            decision,
            {
                "state": result["status"],
                "operation": result["reference"],
                "reason": "Simulated purchase completed"
                if self.engine.settings.provider == "simulator"
                else (
                    "Shielded test payment confirmed by receiver"
                    if result["status"] == "completed"
                    else "Waiting for receiver confirmation"
                ),
            },
        )
        return result

    async def _purchase(self, ref, request):
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
            if self.store.paused():
                raise Refused("signing_paused")
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
            if product.model_dump() not in value["products"]:
                self.book.refuse(ref, request.purchase_ref, selection)
                raise Refused("product_not_permitted")
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
                value.setdefault("deliveries", {})[record["reference"]] = new_delivery(
                    quote, record["operation"]
                )
                self._save(ref, value)
                with self.store.transaction() as db:
                    spent = db.execute("SELECT value FROM meta WHERE key='spent_cents'").fetchone()[0]
                    reserved = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs").fetchone()[0]
                    if spent + reserved + quote.total_cents > self.engine.settings.live_cap_cents:
                        raise Refused("global_cap_exceeded")
                    db.execute("UPDATE meta SET value=value+? WHERE key='spent_cents'", (quote.total_cents,))
                result = await self.engine.provider.execute(quote, record["operation"])
                # Save recovery plaintext encrypted before device encryption (never re-execute).
                value = self.view(ref)
                value["deliveries"][record["reference"]]["payment"] = "simulated"
                value.setdefault("recovery", {})[record["reference"]] = result
                self._save(ref, value)
                self.recover_receipts(ref)
            except (Exception, asyncio.CancelledError) as exc:
                value = self.view(ref)
                delivery = value.get("deliveries", {}).get(record["reference"])
                if delivery and not value.get("recovery", {}).get(record["reference"]):
                    delivery.update(payment="uncertain", reason="review_existing_operation_do_not_pay_again")
                    self._save(ref, value)
                self.book.finish(record["reference"], "requires_private_attention")
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise Refused("requires_private_attention") from None
            return {
                "reference": record["operation"],
                "status": self.book.lookup(ref, request.purchase_ref, selection)["status"],
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
        if product.model_dump() not in value["products"]:
            self.book.refuse(ref, request.purchase_ref, selection)
            raise Refused("product_not_permitted")
        # Avoid even disclosing an unauthorized choice to the merchant.
        self.book.check_candidate(
            ref,
            merchant="test_merchant",
            wallet_id=self.engine.settings.wallet_id,
            network=self.engine.settings.wallet_network,
            product=product.id,
            package=product.package,
            quote_expires=value["document"]["expires_at"],
        )
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
            value.setdefault("deliveries", {})[record["reference"]] = new_delivery(quote, operation)
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

    async def recover_test_payments(self, ref, *, scheduled=False):
        if self.engine.settings.provider != "test_merchant":
            return
        if not self.wallet:
            raise Refused("protected_wallet_required")
        value = self.view(ref)
        for purchase, pending in list(value.get("pending", {}).items()):
            delivery = value.get("deliveries", {}).get(purchase)
            if delivery is None:
                continue
            now = int(time.time())
            if delivery["attempts"] >= 12 or now >= delivery["deadline"]:
                delivery.update(
                    fulfillment="private_attention", reason="delivery_timeout_review_existing_order"
                )
                self._save(ref, value)
                self.book.finish(purchase, "requires_private_attention")
                continue
            if scheduled and delivery["next_poll"] > now:
                continue
            delivery["attempts"] += 1
            delivery["next_poll"] = now + min(300, 15 * 2 ** min(delivery["attempts"], 5))
            self._save(ref, value)
            # This reuses the identical wallet envelope. The wallet is the durable
            # idempotency authority, including after a lost HTTP response or restart.
            result = await self.wallet.call("/mandates/" + ref + "/purchase", pending["payload"])
            wallet_ref = result.get("reference")
            pending["wallet_ref"] = wallet_ref
            pending["wallet_state"] = result.get("state")
            self._save(ref, value)
            if result.get("state") == "signed":
                await self.wallet.call("/operations/" + wallet_ref + "/recover")
            if result.get("state") not in ("signed", "broadcast"):
                self.book.finish(purchase, "requires_private_attention")
                continue
            value["deliveries"][purchase]["payment"] = result["state"]
            receipt = await self.engine.provider.confirmed(Quote.model_validate(pending["quote"]))
            if receipt is None:
                self._save(ref, value)
                self.book.finish(purchase, "awaiting_test_confirmation")
                continue
            value["deliveries"][purchase]["payment"] = "confirmed"
            value.setdefault("recovery", {})[purchase] = receipt
            del value["pending"][purchase]
            self._save(ref, value)
            self.recover_receipts(ref)
            value = self.view(ref)

    async def poll_confirmations(self):
        """Observe existing payments only. Never create, sign or rebroadcast from polling."""
        if self.engine.settings.provider != "test_merchant" or not self.wallet:
            return
        async with self.lock:
            for view in self.views():
                ref = view["reference"]
                value = self.view(ref)
                for purchase, pending in list(value.get("pending", {}).items()):
                    if pending.get("wallet_state") != "broadcast":
                        continue
                    receipt = await self.engine.provider.confirmed(Quote.model_validate(pending["quote"]))
                    if receipt is None:
                        continue
                    if purchase in value.get("deliveries", {}):
                        value["deliveries"][purchase]["payment"] = "confirmed"
                    value.setdefault("recovery", {})[purchase] = receipt
                    del value["pending"][purchase]
                    self._save(ref, value)
                    self.recover_receipts(ref)
                    value = self.view(ref)
                    status = self.book.operation_status(pending["operation"])["status"]
                    for decision in self.store.decisions():
                        if decision.get("operation") == pending["operation"]:
                            self.store.decision(
                                decision["id"],
                                {
                                    "state": status,
                                    "reason": "Shielded test payment confirmed by receiver"
                                    if status == "completed"
                                    else "requires_private_attention",
                                },
                            )
