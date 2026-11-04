import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import select_and_approve

from pactora.crypto import seal_to_device


async def test_restart_after_payment_before_device_delivery(
    client, app, gateway, private, device, provider, monkeypatch
):
    import pactora.engine as module

    job, approval = await select_and_approve(client, gateway, private, device)
    await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)
    real_seal = module.seal_to_device

    def unavailable(*args):
        raise RuntimeError("device envelope failed")

    monkeypatch.setattr(module, "seal_to_device", unavailable)
    await app.state.engine.tick()
    row = app.state.engine.store.get(job)
    assert row["state"] == "uncertain" and row["result"] is not None
    assert provider.executions == 1
    monkeypatch.setattr(module, "seal_to_device", real_seal)
    await app.state.engine.tick()
    await app.state.engine.tick()
    assert provider.executions == 1
    row = app.state.engine.store.get(job)
    assert row["state"] == "completed" and row["result"] is None
    with app.state.engine.store.lock:
        spent = app.state.engine.store.db.execute(
            "SELECT value FROM meta WHERE key='spent_cents'"
        ).fetchone()[0]
    assert spent == 210


def test_browser_webcrypto_compatible_envelope():
    """Cross-check browser-standard WebCrypto through Node, without UI automation."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node WebCrypto unavailable")
    script = """
      const {webcrypto:c}=require('node:crypto');
      (async()=>{
        const keys=await c.subtle.generateKey({name:'RSA-OAEP',modulusLength:3072,
          publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt']);
        const der=Buffer.from(await c.subtle.exportKey('spki',keys.publicKey));
        process.stdout.write(JSON.stringify({public:der.toString('base64'),extractable:keys.privateKey.extractable})+'\\n');
        let input=''; for await (const x of process.stdin) input+=x;
        const e=JSON.parse(input),d=x=>Buffer.from(x,'base64');
        const raw=await c.subtle.decrypt({name:'RSA-OAEP'},keys.privateKey,d(e.key));
        const k=await c.subtle.importKey('raw',raw,'AES-GCM',false,['decrypt']);
        const plain=await c.subtle.decrypt({name:'AES-GCM',iv:d(e.iv),
          additionalData:new TextEncoder().encode('veilcart-receipt-v1')},k,d(e.ciphertext));
        process.stdout.write(new TextDecoder().decode(plain));
      })().catch(()=>process.exit(1));
    """
    proc = subprocess.Popen([node, "-e", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    first = json.loads(proc.stdout.readline())
    assert first["extractable"] is False
    encoded = first["public"]
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(encoded[i : i + 64] for i in range(0, len(encoded), 64))
        + "\n-----END PUBLIC KEY-----\n"
    )
    envelope = seal_to_device({"private_sku": "ONLY-IN-VAULT", "code": "CANARY-SECRET"}, pem)
    output, _ = proc.communicate(json.dumps(envelope), timeout=15)
    assert proc.returncode == 0
    assert json.loads(output)["code"] == "CANARY-SECRET"


def test_patched_zecpy_invoice_regressions_without_native_extension():
    """Loads only the pure invoice module; does not pretend to test the Rust wallet."""
    repo = Path(__file__).resolve().parents[2] / "zecpy"
    if not repo.exists():
        pytest.skip("adjacent ZecPy reference absent")
    source = repo / "python/zecpy/invoices.py"
    import importlib.util
    import sys
    from decimal import Decimal
    from urllib.parse import parse_qs, urlsplit

    spec = importlib.util.spec_from_file_location("zecpy_invoice_regression", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for amount in (1, 150_000, 100_000_000, 1_000_000_000, 2_000_000_000, 10_000_000_000):
        uri = module.Invoice(1, "test", amount, "utest1-test", 0).uri
        assert Decimal(parse_qs(urlsplit(uri).query)["amount"][0]) * 100_000_000 == amount
