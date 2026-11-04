"""Operator-only loopback RPC and bounded read-only readiness checks."""

import asyncio
import http.client
import json
import time
import urllib.error
import urllib.request


def rpc(method, params=None, *, timeout=600):
    request = urllib.request.Request(
        "http://127.0.0.1:18232",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode(),
        {"content-type": "application/json"},
    )
    # Never inherit proxy environment variables for private regtest RPC.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError("regtest RPC is not ready or refused the request")
    return result["result"]


async def wait_for_node(seconds=60, *, request=rpc):
    deadline = time.monotonic() + seconds
    while True:
        try:
            height = await asyncio.to_thread(request, "getblockcount", timeout=2)
            if type(height) is not int or height < 0:
                raise ValueError("invalid block height")
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 19067), 2)
            writer.close()
            await writer.wait_closed()
            return height
        except (OSError, http.client.HTTPException, urllib.error.URLError, RuntimeError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Regtest RPC/gRPC not ready. Start pactora-regtest and retry before creating proof state."
                ) from None
            await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
