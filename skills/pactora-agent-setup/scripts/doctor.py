"""Redacted connection check. Never emits config, headers, exception text or tool data."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

EXPECTED = {
    "search_products",
    "purchase_status",
    "choose_in_chat",
    "request_mandate",
    "mandate_status",
    "request_purchase",
}


async def check(path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from pactora.wallet_cli import protected_file

    # Validate without displaying its contents. Never load backend/wallet configs.
    cfg = json.loads(protected_file(path))
    if set(cfg) != {"executor_url", "gateway_key"}:
        raise ValueError("gateway-only config required")
    from urllib.parse import urlsplit

    endpoint = urlsplit(cfg["executor_url"])
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("invalid endpoint")
    if endpoint.scheme != "https" and not (
        endpoint.scheme == "http" and endpoint.hostname in ("127.0.0.1", "localhost")
    ):
        raise ValueError("HTTPS required")
    import httpx

    result = {"configuration_valid": True, "service_reachable": False, "restricted_tools_verified": False}
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=5) as client:
        response = await client.get(cfg["executor_url"].rstrip("/") + "/health")
        response.raise_for_status()
        health = response.json()
        result["service_reachable"] = health.get("ok") is True
        result["environment"] = (
            health["environment"]
            if health.get("environment") in ("simulator", "test_merchant", "bitrefill")
            else "unknown"
        )
        # Read-only authenticated request: a random unknown operation must produce
        # a generic 409. A 401 means the gateway credential is not accepted.
        response = await client.get(
            cfg["executor_url"].rstrip("/") + "/internal/status/" + "A" * 32,
            headers={"Authorization": "Bearer " + cfg["gateway_key"]},
        )
        result["gateway_authenticated"] = response.status_code == 409
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "pactora.mcp_server", "--config", str(path)]
    )
    import os

    with open(os.devnull, "w") as errors:
        async with stdio_client(params, errlog=errors) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result["restricted_tools_verified"] = {
                    t.name for t in (await session.list_tools()).tools
                } == EXPECTED
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-config", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(asyncio.wait_for(check(args.gateway_config.resolve()), timeout=20))
    except BaseException:
        print(
            json.dumps(
                {"connection_verified": False, "error": "connection_unavailable_or_invalid_configuration"}
            )
        )
        return 1
    ok = all(
        result.get(k)
        for k in (
            "configuration_valid",
            "service_reachable",
            "gateway_authenticated",
            "restricted_tools_verified",
        )
    )
    print(json.dumps({"connection_verified": ok, **result}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
