"""Operator-only native dashboard integration check over real MCP stdio.

Uses a dedicated native_demo instance, not an existing personal wallet. Never
prints credentials, receipt contents, wallet balances or transaction identifiers.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pactora.crypto import unb64


async def main(args):
    headers = {"Origin": args.origin}
    async with httpx.AsyncClient(base_url=args.origin, trust_env=False, timeout=60) as client:
        login = await client.post("/api/login", headers=headers, json={"password": "demo-only-pactora-2026"})
        login.raise_for_status()
        headers["X-CSRF-Token"] = login.json()["csrf"]
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "pactora.mcp_server", "--config", str(args.gateway.resolve())]
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, body):
                    result = await session.call_tool(name, body)
                    assert not result.isError
                    value = json.loads(result.content[0].text)
                    assert not any(
                        secret in json.dumps(value)
                        for secret in ("spendable_zat", "confirmed_zat", "destination", "ciphertext")
                    )
                    return value

                search = await call(
                    "search_products",
                    {"query": "controlled test voucher", "country": "IN", "budget_cents": 100},
                )
                draft = await call(
                    "request_mandate",
                    {
                        "search_ref": search["reference"],
                        "per_purchase_cents": 100,
                        "total_cents": 100,
                        "per_purchase_zat": 200000,
                        "total_zat": 200000,
                        "max_purchases": 1,
                        "duration_seconds": 3600,
                    },
                )
                ref = draft["reference"]
                view = next(m for m in (await client.get("/api/mandates")).json() if m["reference"] == ref)
                key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
                public = (
                    key.public_key()
                    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                    .decode()
                )
                result = await client.post(
                    f"/api/mandates/{ref}/approve",
                    headers=headers,
                    json={"draft_hash": view["draft_hash"], "device_public_key": public},
                )
                result.raise_for_status()
                body = {
                    "reference": ref,
                    "search_ref": search["reference"],
                    "option": 0,
                    "purchase_ref": "native-dashboard-smoke-one",
                }
                assert (
                    await client.post("/api/control", headers=headers, json={"paused": True})
                ).status_code == 200
                paused = await call("request_purchase", body)
                assert paused["status"] == "requires_private_attention"
                assert (
                    await client.post("/api/control", headers=headers, json={"paused": False})
                ).status_code == 200
                first = await call("request_purchase", body)
                assert "reference" in first, first
                for _ in range(40):
                    status = await call("purchase_status", {"reference": first["reference"]})
                    if status["status"] == "completed":
                        break
                    await asyncio.sleep(2)
                assert status["status"] == "completed", status
                retry = await call("request_purchase", body)
                assert retry["reference"] == first["reference"] and retry["status"] == "completed"
                attack = await call(
                    "request_purchase", {**body, "option": 1, "purchase_ref": "native-dashboard-smoke-attack"}
                )
                assert attack["status"] == "requires_private_attention"
                dashboard = (await client.get("/api/dashboard")).json()
                intent = next(m for m in dashboard["intents"] if m["reference"] == ref)
                assert intent["state"] == "exhausted" and intent["usage"]["count"] == 1
                envelope = intent["receipts"][0]
                raw = key.decrypt(
                    unb64(envelope["key"]),
                    padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
                )
                receipt = json.loads(
                    AESGCM(raw).decrypt(
                        unb64(envelope["iv"]), unb64(envelope["ciphertext"]), b"veilcart-receipt-v1"
                    )
                )
                assert receipt["confirmed_zat"] == 100000 and receipt["test_only"] is True
                decisions = [d for d in dashboard["decisions"] if d["intent"] == ref]
                assert len(decisions) == 2 and any(d["state"] == "refused" for d in decisions)
                assert (await client.post(f"/api/mandates/{ref}/revoke", headers=headers)).status_code == 200
                # This check's device key is ephemeral, unlike the real browser's key.
                report = {
                    "proof": "native_dashboard_mcp_stdio",
                    "network": "regtest",
                    "receiver_confirmed": True,
                    "private_receipt_decrypted": True,
                    "retry_created_no_extra_purchase": True,
                    "unauthorized_product_refused": True,
                    "pause_resume_verified": True,
                    "claude_model_used": False,
                    "browser_visual_qa": False,
                    "bitrefill_used": False,
                }
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(report, indent=2))
                await client.post("/api/logout", headers=headers)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--origin", default="http://127.0.0.1:8876")
    p.add_argument("--gateway", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    asyncio.run(main(p.parse_args()))
