import asyncio
import time

from conftest import new_job, select_and_approve

from pactora.crypto import digest


async def test_40_dollar_attack_blocked_under_15_and_5_caps(client, app, gateway, private, provider):
    job = await new_job(client, gateway, budget=1500)
    r = await client.post(f"/api/jobs/{job}/select", headers=private, json={"option": 3})
    assert r.status_code == 409 and r.json()["error"] == "budget_exceeded"
    assert provider.executions == 0
    assert app.state.engine.store.get(job)["quote"] is None


async def test_quote_binding_and_replay(client, app, gateway, private, device, provider):
    job, approval = await select_and_approve(client, gateway, private, device)
    bad = {**approval, "quote_hash": "a" * 64}
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=bad)).status_code == 409
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)).status_code == 200
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)).status_code == 409
    assert (
        await client.post(f"/api/jobs/{job}/select", headers=private, json={"option": 1})
    ).status_code == 409
    await asyncio.gather(app.state.engine.tick(), app.state.engine.tick())
    assert provider.executions == 1


async def test_parallel_approvals_cannot_exceed_aggregate_cap(client, app, gateway, private, device):
    a, approval_a = await select_and_approve(client, gateway, private, device, option=1)
    b, approval_b = await select_and_approve(client, gateway, private, device, option=1)
    results = await asyncio.gather(
        *[
            client.post(f"/api/jobs/{j}/approve", headers=private, json=body)
            for j, body in ((a, approval_a), (b, approval_b))
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    await app.state.engine.tick()
    with app.state.engine.store.lock:
        spent = app.state.engine.store.db.execute(
            "SELECT value FROM meta WHERE key='spent_cents'"
        ).fetchone()[0]
    assert spent == 360


async def test_ambiguous_payment_is_not_retried(client, app, gateway, private, device, provider):
    job, approval = await select_and_approve(client, gateway, private, device)

    async def timeout(*args):
        provider.executions += 1
        raise TimeoutError("sensitive-provider-url-and-token")

    provider.execute = timeout
    await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)
    await app.state.engine.tick()
    await app.state.engine.tick()
    assert provider.executions == 1
    row = app.state.engine.store.get(job)
    assert row["state"] == "uncertain" and row["reservation"] == 210
    status = (await client.get(f"/internal/status/{job}", headers=gateway)).text
    assert "token" not in status and "requires_private_attention" in status


async def test_restarted_executing_operation_is_quarantined(client, app, gateway, private, device, provider):
    job, approval = await select_and_approve(client, gateway, private, device)
    await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)
    with app.state.engine.store.transaction() as db:
        db.execute("UPDATE jobs SET state='executing' WHERE id=?", (job,))
    await app.state.engine.tick()
    assert provider.executions == 0
    assert app.state.engine.store.get(job)["state"] == "uncertain"


async def test_fee_overrun_and_expired_quote(client, app, gateway, private, device):
    job, approval = await select_and_approve(client, gateway, private, device)
    row = app.state.engine.store.get(job)
    raw = app.state.engine.store.cipher.decrypt(row["quote"], job + ":quote")
    raw["max_debit_zat"] = raw["source_zat"]
    with app.state.engine.store.transaction() as db:
        db.execute(
            "UPDATE jobs SET quote=?,quote_hash=? WHERE id=?",
            (app.state.engine.store.cipher.encrypt(raw, job + ":quote"), digest(raw), job),
        )
    approval["quote_hash"] = digest(raw)
    r = await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)
    assert r.status_code == 409 and r.json()["error"] == "fee_cap_exceeded"


async def test_changed_fields_do_not_match_approval(client, app, gateway, private, device):
    job, approval = await select_and_approve(client, gateway, private, device)
    row = app.state.engine.store.get(job)
    raw = app.state.engine.store.cipher.decrypt(row["quote"], job + ":quote")
    raw["destination_address"] = "ATTACKER"
    with app.state.engine.store.transaction() as db:
        db.execute(
            "UPDATE jobs SET quote=? WHERE id=?",
            (app.state.engine.store.cipher.encrypt(raw, job + ":quote"), job),
        )
    assert (await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)).status_code == 409


async def test_quote_expiry_prevents_execution(client, app, gateway, private, device, provider):
    job, approval = await select_and_approve(client, gateway, private, device)
    await client.post(f"/api/jobs/{job}/approve", headers=private, json=approval)
    row = app.state.engine.store.get(job)
    raw = app.state.engine.store.cipher.decrypt(row["quote"], job + ":quote")
    raw["expires_at"] = int(time.time()) - 1
    with app.state.engine.store.transaction() as db:
        db.execute(
            "UPDATE jobs SET quote=? WHERE id=?",
            (app.state.engine.store.cipher.encrypt(raw, job + ":quote"), job),
        )
    await app.state.engine.tick()
    assert provider.executions == 0
    assert app.state.engine.store.get(job)["state"] == "failed"
