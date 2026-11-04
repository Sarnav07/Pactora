"""Real MCP + Chromium simulator proof. Uses public fake credentials and no wallet.

Run with the project Python and Playwright installed. Screenshots contain only
simulator data. Does not connect a browser to a protected or funded service.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def verify(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PACTORA_DEMO_PORT": str(port)}
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "tests/serve_demo.py")], env=env, stdout=log, stderr=log
        )
        try:
            async with httpx.AsyncClient(base_url=origin, trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("simulator failed to start")
                    try:
                        if (await client.get("/health")).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("simulator startup timed out")
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "pactora.mcp_server"],
                env={
                    **os.environ,
                    "PACTORA_EXECUTOR_URL": origin,
                    "PACTORA_GATEWAY_KEY": "QA-ONLY-GATEWAY-TOKEN-NO-REAL-ACCESS-2026",
                },
            )
            async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
                await session.initialize()

                async def tool(name, arguments):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError
                    return json.loads(result.content[0].text)

                found = await tool(
                    "search_products", {"query": "gift cards", "country": "IN", "budget_cents": 500}
                )
                draft = await tool(
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
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(executable_path=args.browser, headless=True)
                    context = await browser.new_context(viewport={"width": 1440, "height": 1050})
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(origin + "/app")
                    await page.get_by_label("Private-view password").fill("demo-only-pactora-2026")
                    await page.get_by_role("button", name="Unlock private view").click()
                    await page.get_by_role("button", name="Approve intent", exact=True).wait_for()
                    await page.screenshot(path=str(output / "approval-desktop.png"), full_page=True)
                    await page.get_by_role("button", name="Approve intent", exact=True).click()
                    await page.get_by_role("button", name="Approve intent", exact=True).wait_for(
                        state="detached"
                    )
                    assert (await tool("mandate_status", {"reference": ref}))["status"] == "approved"
                    purchase = {
                        "reference": ref,
                        "search_ref": found["reference"],
                        "option": 0,
                        "purchase_ref": "demo-one",
                    }
                    first = await tool("request_purchase", purchase)
                    assert first["status"] == "completed"
                    assert await tool("request_purchase", purchase) == first
                    assert (
                        await tool("request_purchase", {**purchase, "option": 3, "purchase_ref": "attack"})
                    )["status"] == "requires_private_attention"
                    await page.get_by_role("link", name="Live", exact=False).click()
                    await page.get_by_role("button", name="Refresh", exact=True).click()
                    await page.get_by_role("button", name="Reveal / hide mandate receipt", exact=True).click()
                    await page.locator(".secret").filter(has_text="SIM-CODE-").wait_for()
                    # Reload retains the non-exportable key in IndexedDB, but clears visible plaintext.
                    await page.reload()
                    await page.get_by_role("button", name="Reveal / hide mandate receipt", exact=True).click()
                    await page.locator(".secret").filter(has_text="SIM-CODE-").wait_for()
                    await page.get_by_role("button", name="I checked this receipt", exact=True).click()
                    await page.get_by_text("acknowledged", exact=True).wait_for()
                    await page.screenshot(path=str(output / "receipt-desktop.png"), full_page=True)
                    await page.set_viewport_size({"width": 390, "height": 844})
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    await page.screenshot(path=str(output / "receipt-mobile.png"), full_page=True)
                    await page.get_by_role("button", name="Request private review", exact=True).click()
                    await page.get_by_text("operator review required", exact=True).wait_for()
                    assert (await tool("purchase_status", {"reference": first["reference"]}))[
                        "status"
                    ] == "requires_private_attention"
                    await page.get_by_role("link", name="Intents", exact=True).click()
                    await page.get_by_role("button", name="Revoke intent", exact=True).click()
                    assert (await tool("mandate_status", {"reference": ref}))["status"] == "revoked"
                    await page.get_by_role("button", name="Lock view", exact=True).click()
                    await page.get_by_label("Private-view password").wait_for()
                    assert await page.locator(".secret").count() == 0
                    assert not errors, errors
                    await browser.close()
            report = {
                "environment": "simulator",
                "real_funds_moved": False,
                "real_goods_delivered": False,
                "mcp_stdio": True,
                "private_browser_approval": True,
                "safe_retry": True,
                "unauthorized_option_refused": True,
                "browser_decryption": True,
                "indexeddb_key_survives_reload": True,
                "device_acknowledgement": True,
                "private_issue_reporting": True,
                "revocation": True,
                "logout_clears_receipts": True,
                "mobile_no_horizontal_overflow": True,
                "browser_page_errors": 0,
                "hosted_codex_or_claude_session": False,
            }
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional installed Chromium executable")
    parser.add_argument("--output", default="artifacts/demo-verification")
    asyncio.run(verify(parser.parse_args()))
