"""Simulator is explicit. Live discovery does not imply live settlement readiness."""

import secrets
import time
from decimal import Decimal

from .models import Product, Quote
from .network import ProtectedHTTP, ProviderError


class GateClosed(ProviderError):
    pass


class Simulator:
    name = "SIMULATOR — no real product, ZEC, or merchant payment"

    def __init__(self):
        self.executions = 0

    async def search(self, query, country):
        return [
            Product(
                id=f"demo-{n}",
                name=name,
                price_cents=price,
                country=country,
                package="one demonstration voucher",
                restrictions="Test data; cannot be redeemed",
            )
            for n, (name, price) in enumerate(
                [
                    ("Demo dining voucher", 200),
                    ("Demo travel voucher", 350),
                    ("Demo book voucher", 450),
                    ("Malicious $40 substitution", 4000),
                ]
            )
        ]

    async def quote(self, product, mode):
        return Quote(
            invoice_id="SIM-INVOICE-" + secrets.token_hex(12),
            product=product,
            total_cents=product.price_cents + 10,
            deposit_address="utest1-SIMULATED-NOT-AN-ADDRESS",
            source_zat=product.price_cents * 1000,
            fee_zat=10_000,
            max_debit_zat=product.price_cents * 1000 + 10_000,
            expires_at=int(time.time()) + 300,
            destination_asset="SIMULATED-USDC",
            destination_address="SIMULATED-MERCHANT",
            checkout_mode=mode,
            simulated=True,
        )

    async def execute(self, quote, operation):
        self.executions += 1
        return {
            "product": quote.product.model_dump(),
            "code": "SIM-CODE-" + secrets.token_hex(12),
            "invoice": quote.invoice_id,
            "transaction": "SIM-TX-" + operation,
            "total_cents": quote.total_cents,
            "simulated": True,
        }

    async def reconcile(self, quote, operation):
        # A real adapter must query its existing operation. Never re-execute.
        return None


class Bitrefill:
    """Account and guest credentials stay behind the trusted service boundary.

    REST is used for typed discovery. The public MCP is intentionally not connected
    directly to the model. Live execution remains closed until independently verified.
    """

    name = "Bitrefill live discovery — settlement gate closed"

    def __init__(self, settings):
        self.settings = settings
        self.http = ProtectedHTTP(settings.tor_proxy)

    def headers(self):
        if not self.settings.bitrefill_token:
            raise GateClosed("Bitrefill credentials required")
        return {"Authorization": "Bearer " + self.settings.bitrefill_token}

    async def search(self, query, country):
        raw = await self.http.request(
            "GET",
            "https://api.bitrefill.com/v2/products/search",
            headers=self.headers(),
            params={"q": query, "country": country, "currency": "USD"},
        )
        items = raw.get("data")
        if isinstance(items, dict):
            items = items.get("products")
        if not isinstance(items, list):
            raise ProviderError("unverified catalog schema")
        result = []
        for item in items[:20]:
            if not isinstance(item, dict) or item.get("country_code", item.get("country")) != country:
                continue
            # Deliberately no guessed conversion of crypto prices to USD. A schema
            # mismatch stops the adapter instead of displaying an invented quote.
            for package in item.get("packages", []):
                if package.get("currency") != "USD" or "price" not in package:
                    continue
                price = Decimal(str(package["price"])) * 100
                if price != price.to_integral_value() or price <= 0:
                    continue
                result.append(
                    Product(
                        id=str(item["id"]),
                        name=str(item["name"])[:120],
                        price_cents=int(price),
                        country=country,
                        package=str(package["value"])[:100],
                        restrictions="Check current merchant restrictions in private view",
                    )
                )
        if not result:
            raise ProviderError("no verified USD-priced packages in this catalog response")
        return result[:20]

    async def quote(self, product, mode):
        raise GateClosed(
            "Live ZEC-funded Bitrefill settlement has not been verified; no invoice or payment created"
        )

    async def execute(self, quote, operation):
        raise GateClosed("Live payment disabled")

    async def reconcile(self, quote, operation):
        return None


class RouteProbe:
    """Read-only inventory; does not create a swap, deposit address, or invoice."""

    def __init__(self, proxy):
        self.http = ProtectedHTTP(proxy)

    async def inspect(self):
        raw = await self.http.request("GET", "https://1click.chaindefuser.com/v0/tokens")
        if not isinstance(raw, list):
            raise ProviderError("invalid token inventory")
        assets = [
            {
                "asset_id": t.get("assetId"),
                "symbol": t.get("symbol"),
                "chain": t.get("blockchain"),
                "decimals": t.get("decimals"),
            }
            for t in raw
            if t.get("symbol") in ("ZEC", "USDC")
        ]
        return {
            "assets": assets,
            "settlement_verified": False,
            "unresolved": [
                "shielded ZEC deposit",
                "exact output to invoice",
                "fees and minimum",
                "invoice expiry",
                "refund address and recovery",
                "real transfer evidence",
            ],
        }
