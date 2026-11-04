"""Actual Zcash test-network invoices; never a live goods merchant or FX service."""

import secrets
from urllib.parse import urlsplit

import httpx

from .models import Product, Quote
from .network import ProtectedHTTP, ProviderError
from .wallet_cli import protected_file


class ControlledMerchant:
    name = "CONTROLLED ZCASH TEST MERCHANT — test funds, no redeemable goods"

    def __init__(self, settings):
        self.settings = settings
        u = urlsplit(settings.test_merchant_url)
        if not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
            raise ValueError("invalid controlled merchant endpoint")
        self.local = u.hostname in ("127.0.0.1", "localhost", "::1")
        if self.local:
            if settings.wallet_network != "regtest" or u.scheme != "http":
                raise ValueError("direct loopback merchant is regtest-only")
        elif u.scheme != "https":
            raise ValueError("remote merchant requires HTTPS through protected transport")
        self.http = ProtectedHTTP(settings.tor_proxy, allowed_hosts={u.hostname}) if not self.local else None

    async def request(self, method, path, body=None):
        token = protected_file(self.settings.test_merchant_token_file)
        kwargs = {"headers": {"Authorization": "Bearer " + token}}
        if body is not None:
            kwargs["json"] = body
        url = self.settings.test_merchant_url.rstrip("/") + path
        if self.http:
            return await self.http.request(method, url, **kwargs)
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=60) as client:
                response = await client.request(method, url, **kwargs)
            if response.status_code != 200:
                raise ProviderError("test_merchant_unavailable")
            return response.json()
        except (ValueError, httpx.HTTPError):
            raise ProviderError("test_merchant_unavailable") from None

    async def search(self, query, country):
        raw = await self.request("GET", "/catalog")
        if raw.get("network") != self.settings.wallet_network or raw.get("test_only") is not True:
            raise ProviderError("test_merchant_network_mismatch")
        return [Product.model_validate(p) for p in raw["products"] if p["country"] == country]

    async def quote(self, product, mode):
        return await self.quote_for(product, secrets.token_urlsafe(24))

    async def quote_for(self, product, operation):
        raw = await self.request(
            "POST", "/invoices", {"operation": operation, "product": product.id, "package": product.package}
        )
        amount = raw.get("amount_zat")
        if (
            raw.get("reference") != operation
            or raw.get("product") != product.model_dump()
            or raw.get("network") != self.settings.wallet_network
            or raw.get("test_only") is not True
            or type(amount) is not int
            or amount <= 0
        ):
            raise ProviderError("test_invoice_binding_changed")
        return Quote(
            invoice_id=operation,
            product=product,
            total_cents=product.price_cents,
            deposit_address=raw["address"],
            source_zat=amount,
            fee_zat=self.settings.test_fee_ceiling_zat,
            max_debit_zat=amount + self.settings.test_fee_ceiling_zat,
            expires_at=raw["expires_at"],
            destination_asset="TEST-ZEC",
            destination_address=raw["address"],
            checkout_mode="controlled_test",
            simulated=False,
        )

    async def confirmed(self, quote):
        raw = await self.request("GET", "/invoices/" + quote.invoice_id)
        if (
            raw.get("reference") != quote.invoice_id
            or raw.get("network") != self.settings.wallet_network
            or raw.get("amount_zat") != quote.source_zat
            or raw.get("test_only") is not True
        ):
            raise ProviderError("test_receipt_binding_changed")
        if raw.get("status") != "paid" or raw.get("confirmed_zat", 0) < quote.source_zat:
            return None
        return {
            "invoice": quote.invoice_id,
            "product": quote.product.model_dump(),
            "confirmed_zat": raw["confirmed_zat"],
            "test_only": True,
            "simulated": False,
            "notice": "Actual shielded test-network receipt; no real goods delivered",
        }

    async def execute(self, quote, operation):
        raise ProviderError("test_payment_requires_mandate_wallet_path")

    async def reconcile(self, quote, operation):
        return await self.confirmed(quote)
