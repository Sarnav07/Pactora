import asyncio
import secrets
import time

from .crypto import digest, seal_to_device, validate_device_key
from .fulfillment import assess_delivery, expected_delivery
from .models import Product, Quote


class Refused(Exception):
    """Only sanitized codes may cross the model boundary."""


class Engine:
    def __init__(self, store, provider, settings):
        self.store, self.provider, self.settings = store, provider, settings
        self.worker_lock = asyncio.Lock()

    async def search(self, request):
        self.store.cleanup()
        products = await self.provider.search(request.query, request.country)
        job = secrets.token_urlsafe(24)
        now = int(time.time())
        details = {"request": request.model_dump(), "products": [p.model_dump() for p in products]}
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO jobs(id,state,expires,details,created) VALUES (?,?,?,?,?)",
                (
                    job,
                    "awaiting_selection",
                    now + self.settings.session_ttl,
                    self.store.cipher.encrypt(details, job + ":details"),
                    now,
                ),
            )
        return {
            "reference": job,
            "private_url": self.settings.origin + "/",
            "environment": self.provider.name,
            "options": [
                {
                    "option": i,
                    "name": p.name,
                    "price_cents": p.price_cents,
                    "country": p.country,
                    "package": p.package,
                    "restrictions": p.restrictions,
                }
                for i, p in enumerate(products)
            ],
        }

    def _row(self, job):
        row = self.store.get(job)
        if row is None:
            raise Refused("not_found")
        return row

    def private_job(self, job):
        row = self._row(job)
        result = {
            "reference": job,
            "state": row["state"],
            "chat_enabled": bool(row["chat"]),
            "environment": self.provider.name,
        }
        if row["state"] in ("awaiting_selection", "awaiting_approval"):
            result["details"] = self.store.cipher.decrypt(row["details"], job + ":details")
        if row["quote"]:
            result["quote"] = self.store.cipher.decrypt(row["quote"], job + ":quote")
            result["quote_hash"] = row["quote_hash"]
        if row["vault"]:
            result["vault"] = self.store.cipher.decrypt(row["vault"], job + ":vault")
        return result

    async def select(self, job, option, *, from_chat=False):
        row = self._row(job)
        if from_chat and not row["chat"]:
            raise Refused("private_selection_required")
        if row["state"] not in ("awaiting_selection", "awaiting_approval") or row["expires"] <= time.time():
            raise Refused("selection_expired_or_locked")
        details = self.store.cipher.decrypt(row["details"], job + ":details")
        if option < 0 or option >= len(details["products"]):
            raise Refused("invalid_option")
        product = Product.model_validate(details["products"][option])
        if product.price_cents > min(details["request"]["budget_cents"], self.settings.live_cap_cents):
            raise Refused("budget_exceeded")
        quote = await self.provider.quote(product, self.settings.checkout_mode)
        self.validate_quote(quote, details)
        raw = quote.model_dump()
        with self.store.transaction() as db:
            updated = db.execute(
                """UPDATE jobs SET state='awaiting_approval',quote=?,quote_hash=?
                WHERE id=? AND state IN ('awaiting_selection','awaiting_approval') AND expires>?""",
                (self.store.cipher.encrypt(raw, job + ":quote"), digest(raw), job, time.time()),
            )
            if updated.rowcount != 1:
                raise Refused("selection_locked")
        return {"status": "requires_private_attention", "reference": job}

    def validate_quote(self, quote, details):
        limit = min(details["request"]["budget_cents"], self.settings.live_cap_cents)
        if quote.total_cents > limit or quote.total_cents < quote.product.price_cents:
            raise Refused("budget_exceeded")
        if quote.product.model_dump() not in details["products"]:
            raise Refused("product_changed")
        if quote.checkout_mode != self.settings.checkout_mode or quote.expires_at <= time.time():
            raise Refused("quote_expired_or_changed")
        if quote.source_zat + quote.fee_zat > quote.max_debit_zat:
            raise Refused("fee_cap_exceeded")
        if quote.simulated != (self.settings.provider == "simulator"):
            raise Refused("environment_mismatch")

    def approve(self, job, approval):
        validate_device_key(approval.device_public_key)
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None or row["state"] != "awaiting_approval" or row["expires"] <= time.time():
                raise Refused("approval_expired_or_used")
            if row["quote_hash"] != approval.quote_hash:
                raise Refused("quote_changed")
            quote = Quote.model_validate(self.store.cipher.decrypt(row["quote"], job + ":quote"))
            details = self.store.cipher.decrypt(row["details"], job + ":details")
            if digest(quote.model_dump()) != approval.quote_hash:
                raise Refused("quote_changed")
            self.validate_quote(quote, details)
            spent = db.execute("SELECT value FROM meta WHERE key='spent_cents'").fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(reservation),0) FROM jobs").fetchone()[0]
            if spent + reserved + quote.total_cents > self.settings.live_cap_cents:
                raise Refused("aggregate_budget_exceeded")
            db.execute(
                "UPDATE jobs SET state='approved', reservation=?, device_key=? WHERE id=?",
                (quote.total_cents, approval.device_public_key, job),
            )
        return {"status": "approved"}

    def enable_chat(self, job, enabled):
        with self.store.transaction() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None or row[0] != "awaiting_selection":
                raise Refused("selection_locked")
            db.execute("UPDATE jobs SET chat=? WHERE id=?", (int(enabled), job))

    def public_status(self, job):
        row = self._row(job)
        state = row["state"]
        status = (
            "completed"
            if state == "completed"
            else "failed"
            if state in ("failed", "expired")
            else "requires_private_attention"
            if state in ("awaiting_selection", "awaiting_approval", "uncertain")
            else "pending"
        )
        # No chosen SKU, invoice, amount, errors, txid or vault handle.
        return {"reference": job, "status": status, "environment": self.provider.name}

    def complete(self, job, result):
        """Persist before device sealing; recovery never requires another purchase."""
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None or row["state"] == "completed":
                return
            db.execute(
                "UPDATE jobs SET result=? WHERE id=?",
                (self.store.cipher.encrypt(result, job + ":result"), job),
            )
        quote = Quote.model_validate(self.store.cipher.decrypt(row["quote"], job + ":quote"))
        state, _ = assess_delivery(expected_delivery(quote, job), result)
        if state not in ("simulator_issued", "not_applicable"):
            raise Refused("fulfillment_requires_private_attention")
        sealed = seal_to_device(result, row["device_key"])
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if current["state"] == "completed":
                return
            db.execute("UPDATE meta SET value=value+? WHERE key='spent_cents'", (current["reservation"],))
            db.execute(
                """UPDATE jobs SET state='completed',reservation=0,vault=?,details=?,
                quote=NULL,quote_hash=NULL,device_key=NULL,result=NULL WHERE id=?""",
                (
                    self.store.cipher.encrypt(sealed, job + ":vault"),
                    self.store.cipher.encrypt({}, job + ":details"),
                    job,
                ),
            )

    async def tick(self):
        async with self.worker_lock:
            self.store.cleanup()
            # An executing operation left by process death cannot be executed again.
            for row in self.store.jobs():
                if row["state"] == "executing":
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE jobs SET state='uncertain' WHERE id=? AND state='executing'", (row["id"],)
                        )
            for row in self.store.jobs():
                if row["state"] == "uncertain":
                    try:
                        if row["result"]:
                            result = self.store.cipher.decrypt(row["result"], row["id"] + ":result")
                        else:
                            quote = Quote.model_validate(
                                self.store.cipher.decrypt(row["quote"], row["id"] + ":quote")
                            )
                            result = await self.provider.reconcile(quote, row["id"])
                        if result is not None:
                            self.complete(row["id"], result)
                    except Exception:
                        pass  # Keep the reservation and encrypted recovery context.
                    continue
                if row["state"] != "approved" or self.store.paused():
                    continue
                job = row["id"]
                with self.store.transaction() as db:
                    changed = db.execute(
                        "UPDATE jobs SET state='executing' WHERE id=? AND state='approved'", (job,)
                    )
                    if changed.rowcount != 1:
                        continue
                try:
                    quote = Quote.model_validate(self.store.cipher.decrypt(row["quote"], job + ":quote"))
                    if quote.expires_at <= time.time():
                        with self.store.transaction() as db:
                            db.execute("UPDATE jobs SET state='failed',reservation=0 WHERE id=?", (job,))
                        continue
                    if digest(quote.model_dump()) != row["quote_hash"]:
                        raise Refused("quote_changed")
                    details = self.store.cipher.decrypt(row["details"], job + ":details")
                    self.validate_quote(quote, details)
                    result = await self.provider.execute(quote, job)
                    self.complete(job, result)
                except (Exception, asyncio.CancelledError):
                    # Do not release reserved funds when an external action may have happened.
                    with self.store.transaction() as db:
                        db.execute("UPDATE jobs SET state='uncertain' WHERE id=?", (job,))
                    # Cancellation must still terminate shutdown.
                    if asyncio.current_task().cancelling():
                        raise

    async def loop(self):
        while True:
            await self.tick()
            await asyncio.sleep(2)
