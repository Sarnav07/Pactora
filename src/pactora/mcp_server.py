"""Thin, credential-limited gateway. No wallet, vault key, or merchant token here."""

import logging
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP

from .config import env


def build_server(base_url=None, token=None, transport=None):
    base_url = base_url or env("PACTORA_EXECUTOR_URL")
    token = token or env("PACTORA_GATEWAY_KEY")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "executor")
    ):
        raise ValueError("executor requires HTTPS except in isolated local development")
    server = FastMCP(
        "Pactora",
        instructions=(
            "Private selection is the default. Search, show options, and ask the user to open the private view. "
            "Never request payment secrets. Autonomous choices require an approved bounded mandate. "
            "Legacy chat selection only works after the user "
            "enables it in that view. A completed status reveals no selected product. Simulator results are not "
            "real purchases. Poll at most once per 15 seconds. Never retry a financial action after a timeout."
        ),
    )

    async def call(method, path, body=None):
        try:
            async with httpx.AsyncClient(
                base_url=base_url, transport=transport, trust_env=False, follow_redirects=False, timeout=30
            ) as client:
                res = await client.request(
                    method, path, json=body, headers={"Authorization": "Bearer " + token}
                )
            if not res.is_success:
                return {"status": "requires_private_attention"}
            return res.json()
        except (httpx.HTTPError, ValueError):
            return {"status": "requires_private_attention"}

    @server.tool()
    async def search_products(query: str, country: str, budget_cents: int) -> dict:
        """Search with structured criteria only. Budget is integer USD cents. No unrelated chat history."""
        return await call(
            "POST",
            "/internal/search",
            {
                "query": query,
                "country": country,
                "budget_cents": budget_cents,
            },
        )

    @server.tool()
    async def purchase_status(reference: str) -> dict:
        """Generic status. Does not reveal the selected product, amount, transaction or vault contents."""
        if not _reference(reference):
            return {"status": "requires_private_attention"}
        return await call("GET", "/internal/status/" + reference)

    @server.tool()
    async def choose_in_chat(reference: str, option: int) -> dict:
        """Less-private mode. Refused unless the user explicitly enabled chat selection in the private view.

        This only proposes a selection. Exact payment still requires private-view approval.
        """
        if not _reference(reference):
            return {"status": "requires_private_attention"}
        return await call("POST", "/internal/chat-select/" + reference, {"option": option})

    @server.tool()
    async def request_mandate(
        search_ref: str,
        per_purchase_cents: int,
        total_cents: int,
        per_purchase_zat: int,
        total_zat: int,
        max_purchases: int,
        duration_seconds: int,
    ) -> dict:
        """Draft a bounded mandate. Approval happens only in the private view.

        Limits include fees. Zat limits are explicit user limits, not a model-estimated FX rate.
        """
        return await call(
            "POST",
            "/internal/mandates",
            {
                "search_ref": search_ref,
                "per_purchase_cents": per_purchase_cents,
                "total_cents": total_cents,
                "per_purchase_zat": per_purchase_zat,
                "total_zat": total_zat,
                "max_purchases": max_purchases,
                "duration_seconds": duration_seconds,
            },
        )

    @server.tool()
    async def mandate_status(reference: str) -> dict:
        """Generic authorization state only; no signatures, receipts or wallet data."""
        if not _reference(reference):
            return {"status": "requires_private_attention"}
        return await call("GET", "/internal/mandates/" + reference)

    @server.tool()
    async def request_purchase(reference: str, search_ref: str, option: int, purchase_ref: str) -> dict:
        """Request an eligible purchase. Retry with the SAME purchase_ref after uncertainty.

        A deliberate additional purchase needs a new explicit purchase_ref. No addresses,
        invoices or fulfillment secrets are accepted or returned by this tool.
        """
        if not _reference(reference) or not _reference(search_ref):
            return {"status": "requires_private_attention"}
        return await call(
            "POST",
            "/internal/mandates/" + reference + "/purchase",
            {"search_ref": search_ref, "option": option, "purchase_ref": purchase_ref},
        )

    return server


def _reference(value):
    return len(value) == 32 and all(c.isalnum() or c in "_-" for c in value)


def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Restricted Pactora MCP gateway")
    parser.add_argument("--config", help="Owner-only gateway configuration; contains no wallet secrets")
    args = parser.parse_args()
    if args.config:
        from .wallet_cli import protected_file

        cfg = json.loads(protected_file(args.config))
        build_server(cfg["executor_url"], cfg["gateway_key"]).run(transport="stdio")
    else:
        build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
