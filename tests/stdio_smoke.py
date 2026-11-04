"""Run against tests/serve_demo.py. Exercises the real MCP wire protocol."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pactora.crypto import unb64


async def main():
    command = str(Path(__file__).resolve().parents[1] / ".venv/bin/pactora-mcp")
    parameters = StdioServerParameters(
        command=command,
        env={
            **os.environ,
            "PACTORA_EXECUTOR_URL": "http://127.0.0.1:8876",
            "PACTORA_GATEWAY_KEY": "QA-ONLY-GATEWAY-TOKEN-NO-REAL-ACCESS-2026",
        },
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {
                "search_products",
                "purchase_status",
                "choose_in_chat",
                "request_mandate",
                "mandate_status",
                "request_purchase",
            }
            result = await session.call_tool(
                "search_products",
                {
                    "query": "gift cards",
                    "country": "IN",
                    "budget_cents": 500,
                },
            )
            assert not result.isError
            value = json.loads(result.content[0].text)
            assert "SIMULATOR" in value["environment"]
            status = await session.call_tool("purchase_status", {"reference": value["reference"]})
            public = json.loads(status.content[0].text)
            assert set(public) == {"reference", "status", "environment"}
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            pem = (
                key.public_key()
                .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                .decode()
            )
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8876", trust_env=False) as private:
                origin = {"Origin": "http://127.0.0.1:8876"}
                login = await private.post(
                    "/api/login", headers=origin, json={"password": "demo-only-pactora-2026"}
                )
                login.raise_for_status()
                headers = {**origin, "X-CSRF-Token": login.json()["csrf"]}
                reference = value["reference"]
                choice = await private.post(
                    f"/api/jobs/{reference}/select", headers=headers, json={"option": 0}
                )
                choice.raise_for_status()
                jobs = (await private.get("/api/jobs")).json()
                job = next(j for j in jobs if j["reference"] == reference)
                approved = await private.post(
                    f"/api/jobs/{reference}/approve",
                    headers=headers,
                    json={"quote_hash": job["quote_hash"], "device_public_key": pem},
                )
                approved.raise_for_status()
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    result = await session.call_tool("purchase_status", {"reference": reference})
                    public = json.loads(result.content[0].text)
                    if public["status"] == "completed":
                        break
                assert public["status"] == "completed"
                assert set(public) == {"reference", "status", "environment"}
                jobs = (await private.get("/api/jobs")).json()
                envelope = next(j for j in jobs if j["reference"] == reference)["vault"]
                secret = key.decrypt(
                    unb64(envelope["key"]),
                    padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
                )
                receipt = json.loads(
                    AESGCM(secret).decrypt(
                        unb64(envelope["iv"]), unb64(envelope["ciphertext"]), b"veilcart-receipt-v1"
                    )
                )
                assert receipt["product"]["id"] == "demo-0"
                assert receipt["code"] not in json.dumps(public)
            print(
                "MCP stdio → search → private approval → background execution → encrypted receipt passed (simulator)."
            )


if __name__ == "__main__":
    asyncio.run(main())
