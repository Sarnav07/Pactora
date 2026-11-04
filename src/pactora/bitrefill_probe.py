"""Read-only MCP contract inspection; never calls buy-products or signs payment."""

import json
from pathlib import Path

from .network import ProtectedHTTP, ProviderError
from .wallet_cli import protected_file

READ_ONLY = frozenset({"search-products", "get-product-details", "get-balances"})


class BitrefillProbe:
    def __init__(self, proxy, token_file):
        self.http = ProtectedHTTP(proxy)
        self.token_file = token_file
        self.sequence = 0

    async def rpc(self, method, params=None):
        if method not in ("initialize", "tools/list", "tools/call"):
            raise ProviderError("probe_method_forbidden")
        if method == "tools/call" and (params or {}).get("name") not in READ_ONLY:
            raise ProviderError("probe_tool_forbidden")
        self.sequence += 1
        request_id = self.sequence
        body = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        raw = await self.http.request(
            "POST",
            "https://api.bitrefill.com/mcp",
            json=body,
            headers={
                "Authorization": "Bearer " + protected_file(self.token_file),
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
        )
        if raw.get("id") != request_id or raw.get("error") or "result" not in raw:
            raise ProviderError("bitrefill_rpc_failed")
        if raw["result"].get("isError"):
            raise ProviderError("bitrefill_tool_refused")
        return raw["result"]

    async def inspect(self):
        await self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pactora-readiness", "version": "0.1.0"},
            },
        )
        result = await self.rpc("tools/list")
        tools = {tool["name"]: tool for tool in result.get("tools", [])}
        # Do not treat a preview as an atomic price guarantee. Sponsor/API contract
        # confirmation is required before implementing an account-debit operation.
        buy = tools.get("buy-products", {}).get("inputSchema", {})
        return {
            "reachable_through_protected_route": True,
            "catalog_tools_available": all(
                name in tools for name in ("search-products", "get-product-details")
            ),
            "account_tools_available": "get-balances" in tools,
            "buy_argument_names": sorted(buy.get("properties", {}).keys()),
            "safe_balance_checkout_verified": False,
            "funds_moved": False,
            "blockers": [
                "credentials_and_dedicated_funds_must_be_provisioned",
                "atomic_maximum_debit_or_reserved_quote_contract_not_verified",
                "invoice_reconciliation_after_lost_response_not_verified",
            ],
        }


async def run_probe(config, output):
    cfg = json.loads(protected_file(config))
    report = await BitrefillProbe(cfg["tor_proxy"], cfg["token_file"]).inspect()
    target = Path(output)
    # The report deliberately contains no token, raw tool output, balances or invoice data.
    target.write_text(json.dumps(report, indent=2) + "\n")
    return report
