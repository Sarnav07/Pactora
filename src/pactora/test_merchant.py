"""Controlled test-only merchant. Detects actual shielded receipt using ZecPy.

This is not Bitrefill and its catalog cents are test accounting units, not an FX quote.
"""

import asyncio
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import Field

from .engine import Refused
from .models import StrictModel

CATALOG = [
    {
        "id": "test-voucher",
        "name": "Controlled shielded test voucher",
        "price_cents": 100,
        "country": "IN",
        "package": "one test voucher",
        "restrictions": "Test network only; not redeemable",
    },
    {
        "id": "test-attack",
        "name": "Unauthorized $40 test item",
        "price_cents": 4000,
        "country": "IN",
        "package": "unauthorized",
        "restrictions": "Must be refused",
    },
]


class InvoiceRequest(StrictModel):
    operation: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    product: str = Field(min_length=1, max_length=128)
    package: str = Field(min_length=1, max_length=256)


class TestMerchant:
    __test__ = False

    def __init__(self, wallet, directory, *, amount_zat=100000, confirmations=1):
        if wallet.network not in ("test", "regtest") or wallet.can_send:
            raise ValueError("merchant requires a test-network watch-only wallet")
        if type(amount_zat) is not int or amount_zat <= 0 or confirmations < 1:
            raise ValueError("invalid merchant payment settings")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.wallet, self.amount, self.confirmations = wallet, amount_zat, confirmations
        self.db = sqlite3.connect(directory / "orders.sqlite")
        (directory / "orders.sqlite").chmod(0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS orders (operation TEXT PRIMARY KEY, product TEXT, package TEXT, expires INTEGER)"
        )
        self.db.commit()
        self.lock = asyncio.Lock()

    def invoice(self, request):
        item = next(
            (p for p in CATALOG if p["id"] == request.product and p["package"] == request.package), None
        )
        if not item:
            raise Refused("unknown_product")
        row = self.db.execute(
            "SELECT product,package,expires FROM orders WHERE operation=?", (request.operation,)
        ).fetchone()
        if row and tuple(row[:2]) != (request.product, request.package):
            raise Refused("invoice_reference_changed")
        # Pin product identity before native invoice creation. A crash between the
        # two databases cannot let the same operation change its product/package.
        if row is None:
            expires = int(time.time()) + 900
            self.db.execute(
                "INSERT INTO orders VALUES (?,?,?,?)",
                (request.operation, request.product, request.package, expires),
            )
            self.db.commit()
        else:
            expires = row[2]
        try:
            invoice = self.wallet.invoices.by_reference(request.operation)
        except KeyError:
            invoice = self.wallet.invoices.create(self.amount, request.operation)
        return {
            "reference": request.operation,
            "product": item,
            "address": invoice.address,
            "amount_zat": invoice.amount_zat,
            "expires_at": expires,
            "network": self.wallet.network,
            "simulated": False,
            "test_only": True,
        }

    async def status(self, operation):
        async with self.lock:
            if self.db.execute("SELECT 1 FROM orders WHERE operation=?", (operation,)).fetchone() is None:
                raise Refused("unknown_invoice")
            invoice = self.wallet.invoices.by_reference(operation)
            await self.wallet.sync()
            # Update native invoice payment detection locally; no address query to server.
            self.wallet.invoices.poll(confirmations=self.confirmations)
            status = self.wallet.invoices.status(invoice)
            return {
                "reference": operation,
                "status": status.state,
                "confirmed_zat": status.confirmed_zat,
                "amount_zat": invoice.amount_zat,
                "network": self.wallet.network,
                "test_only": True,
            }


def create_merchant_app(merchant, token):
    if len(token) < 32:
        raise ValueError("merchant token required")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def auth(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + token):
            raise Refused("unauthorized")

    @app.exception_handler(Refused)
    async def refused(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=403)

    @app.get("/catalog", dependencies=[Depends(auth)])
    async def catalog():
        return {"products": CATALOG, "network": merchant.wallet.network, "test_only": True}

    @app.post("/invoices", dependencies=[Depends(auth)])
    async def invoice(body: InvoiceRequest):
        return merchant.invoice(body)

    @app.get("/invoices/{operation}", dependencies=[Depends(auth)])
    async def status(operation: str):
        return await merchant.status(operation)

    @app.middleware("http")
    async def private(request, call_next):
        if request.headers.get("origin") or request.headers.get("sec-fetch-site"):
            return JSONResponse({"error": "browser_access_forbidden"}, status_code=403)
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        return result

    return app
