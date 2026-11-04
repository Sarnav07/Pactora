"""Real MCP stdio + loopback simulator. No native wallet or funds."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parameters = StdioServerParameters(
        command=str(Path(__file__).resolve().parents[1] / ".venv/bin/pactora-mcp"),
        env={
            **os.environ,
            "PACTORA_EXECUTOR_URL": "http://127.0.0.1:8876",
            "PACTORA_GATEWAY_KEY": "QA-ONLY-GATEWAY-TOKEN-NO-REAL-ACCESS-2026",
        },
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.isError
                return json.loads(result.content[0].text)

            found = await call(
                "search_products", {"query": "gift cards", "country": "IN", "budget_cents": 500}
            )
            draft = await call(
                "request_mandate",
                {
                    "search_ref": found["reference"],
                    "per_purchase_cents": 250,
                    "total_cents": 500,
                    "per_purchase_zat": 300000,
                    "total_zat": 600000,
                    "max_purchases": 2,
                    "duration_seconds": 600,
                },
            )
            ref = draft["reference"]
            assert draft["status"] == "awaiting_private_approval"
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8876", trust_env=False) as private:
                origin = {"Origin": "http://127.0.0.1:8876"}
                response = await private.post(
                    "/api/login", headers=origin, json={"password": "demo-only-pactora-2026"}
                )
                response.raise_for_status()
                headers = {**origin, "X-CSRF-Token": response.json()["csrf"]}
                view = next(v for v in (await private.get("/api/mandates")).json() if v["reference"] == ref)
                key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
                pem = (
                    key.public_key()
                    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                    .decode()
                )
                response = await private.post(
                    f"/api/mandates/{ref}/approve",
                    headers=headers,
                    json={"draft_hash": view["draft_hash"], "device_public_key": pem},
                )
                response.raise_for_status()
                assert (await call("mandate_status", {"reference": ref}))["status"] == "approved"
                args = {
                    "reference": ref,
                    "search_ref": found["reference"],
                    "option": 0,
                    "purchase_ref": "one",
                }
                first = await call("request_purchase", args)
                assert first["status"] == "completed"
                assert await call("request_purchase", args) == first
                second = await call("request_purchase", {**args, "purchase_ref": "two"})
                assert second["status"] == "completed"
                assert (await call("request_purchase", {**args, "purchase_ref": "three"}))[
                    "status"
                ] == "requires_private_attention"
                assert (await call("purchase_status", {"reference": first["reference"]}))[
                    "status"
                ] == "completed"
                receipts = next(
                    v for v in (await private.get("/api/mandates")).json() if v["reference"] == ref
                )["receipts"]
                assert len(receipts) == 2
                assert all(
                    secret not in json.dumps([first, second])
                    for secret in ("SIM-CODE", "SIM-INVOICE", "signature", "txid")
                )
    print(
        "PASS: real MCP stdio; one private mandate, two simulated purchases, safe retry, cap refusal, private receipts"
    )


if __name__ == "__main__":
    asyncio.run(main())
