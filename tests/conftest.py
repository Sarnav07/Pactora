import base64
import secrets

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pactora.app import create_app
from pactora.config import Settings
from pactora.crypto import password_hash
from pactora.providers import Simulator

PASSWORD = "test-private-password-2026"


@pytest.fixture(scope="session")
def device():
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, pem


@pytest.fixture(scope="session")
def hashed_password():
    return password_hash(PASSWORD)


@pytest.fixture
def settings(tmp_path, hashed_password):
    return Settings(
        data_dir=tmp_path / "data",
        master_key=base64.b64encode(secrets.token_bytes(32)).decode(),
        gateway_key=secrets.token_urlsafe(32),
        password_hash=hashed_password,
    )


@pytest.fixture
def provider():
    return Simulator()


@pytest.fixture
def app(settings, provider):
    instance = create_app(settings, provider, run_worker=False)
    yield instance
    instance.state.engine.store.db.close()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
    ) as c:
        yield c


@pytest.fixture
def gateway(settings):
    return {"Authorization": "Bearer " + settings.gateway_key}


@pytest.fixture
async def private(client):
    r = await client.post(
        "/api/login", headers={"Origin": "http://127.0.0.1:8787"}, json={"password": PASSWORD}
    )
    assert r.status_code == 200
    return {"Origin": "http://127.0.0.1:8787", "X-CSRF-Token": r.json()["csrf"]}


async def new_job(client, gateway, budget=500):
    r = await client.post(
        "/internal/search",
        headers=gateway,
        json={"query": "gift cards", "country": "IN", "budget_cents": budget},
    )
    assert r.status_code == 200, r.text
    return r.json()["reference"]


async def select_and_approve(client, gateway, private, device, option=0):
    job = await new_job(client, gateway)
    r = await client.post(f"/api/jobs/{job}/select", headers=private, json={"option": option})
    assert r.status_code == 200
    item = next(j for j in (await client.get("/api/jobs")).json() if j["reference"] == job)
    approval = {"quote_hash": item["quote_hash"], "device_public_key": device[1]}
    return job, approval
