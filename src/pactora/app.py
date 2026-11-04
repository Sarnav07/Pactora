import asyncio
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from .config import Settings
from .crypto import PrivateStoreCipher, verify_password
from .engine import Engine, Refused
from .mandate_commerce import MandateApproval, MandateCommerce, MandateRequest, PurchaseRequest
from .models import Approve, PrivateSelection, Search, StrictModel
from .network import ProviderError
from .providers import Bitrefill, Simulator
from .store import Store

STATIC = Path(__file__).parent / "static"


class Login(StrictModel):
    password: str = Field(min_length=1, max_length=512)


class ChatMode(StrictModel):
    enabled: bool


def create_app(settings: Settings, provider=None, *, run_worker=True):
    store = Store(settings.data_dir, PrivateStoreCipher(settings.master_key))
    engine = Engine(
        store,
        provider or (Simulator() if settings.provider == "simulator" else Bitrefill(settings)),
        settings,
    )

    mandates = MandateCommerce(engine)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(engine.loop()) if run_worker else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if mandates.book:
            mandates.book.close()
        store.db.close()

    app = FastAPI(
        title="Pactora private executor", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.engine = engine
    app.state.mandates = mandates
    # Global login throttle; no IP or raw password logging. Single-user MVP.
    attempts = []
    allowed_host = urlsplit(settings.origin).netloc

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.headers.get("host") != allowed_host:
            return JSONResponse({"error": "host_refused"}, 400)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 32_768:
            return JSONResponse({"error": "request_too_large"}, 413)
        if request.method not in ("GET", "HEAD") and not request.url.path.startswith("/internal/"):
            if request.headers.get("origin") != settings.origin:
                return JSONResponse({"error": "origin_refused"}, 403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            }
        )
        if settings.secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(Refused)
    async def refused(request, exc):
        # Private view can see reason codes. Agent never receives selected-item reasons.
        reason = "requires_private_attention" if request.url.path.startswith("/internal/") else str(exc)
        return JSONResponse({"error": reason}, 409)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"error": "provider_unavailable_or_live_gate_closed"}, 503)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({"error": "private_attention_required"}, 500)

    def gateway(request: Request):
        expected = "Bearer " + settings.gateway_key
        if not hmac.compare_digest(request.headers.get("authorization", ""), expected):
            raise HTTPException(401, "unauthorized")

    def session(request: Request):
        token = request.cookies.get("veilcart_session", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with store.lock:
            row = store.db.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires>?", (token_hash, int(time.time()))
            ).fetchone()
        if row is None:
            raise HTTPException(401, "sign_in_required")
        if request.method not in ("GET", "HEAD"):
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
                raise HTTPException(403, "csrf_refused")
        return row

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{name}")
    async def asset(name: str):
        if name not in ("app.js", "app.css"):
            raise HTTPException(404)
        return FileResponse(STATIC / name)

    @app.get("/health")
    async def health():
        return {"ok": True, "environment": settings.provider, "live_spending_enabled": False}

    @app.post("/api/login")
    async def login(body: Login, response: Response):
        now = time.monotonic()
        attempts[:] = [t for t in attempts if now - t < 60]
        if len(attempts) >= 5:
            raise HTTPException(429, "try_later")
        attempts.append(now)
        valid = await asyncio.to_thread(verify_password, body.password, settings.password_hash)
        if not valid:
            raise HTTPException(401, "sign_in_failed")
        attempts.clear()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with store.transaction() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), csrf, int(time.time()) + 3600),
            )
        response.set_cookie(
            "veilcart_session",
            token,
            httponly=True,
            secure=settings.secure_cookie,
            samesite="strict",
            max_age=3600,
        )
        return {"csrf": csrf, "environment": engine.provider.name}

    @app.get("/api/session", dependencies=[Depends(session)])
    async def current_session(request: Request):
        return {"csrf": session(request)["csrf"], "environment": engine.provider.name}

    @app.post("/api/logout", dependencies=[Depends(session)])
    async def logout(request: Request, response: Response):
        token_hash = hashlib.sha256(request.cookies["veilcart_session"].encode()).hexdigest()
        with store.transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        response.delete_cookie("veilcart_session")
        return {"ok": True}

    @app.get("/api/jobs", dependencies=[Depends(session)])
    async def jobs():
        store.cleanup()
        return [engine.private_job(r["id"]) for r in store.jobs()]

    @app.post("/api/jobs/{job}/select", dependencies=[Depends(session)])
    async def select(job: str, body: PrivateSelection):
        return await engine.select(job, body.option)

    @app.post("/api/jobs/{job}/chat", dependencies=[Depends(session)])
    async def chat_mode(job: str, body: ChatMode):
        engine.enable_chat(job, body.enabled)
        return {"enabled": body.enabled}

    @app.post("/api/jobs/{job}/approve", dependencies=[Depends(session)])
    async def approve(job: str, body: Approve):
        return engine.approve(job, body)

    @app.get("/api/mandates", dependencies=[Depends(session)])
    async def private_mandates():
        return mandates.views()

    @app.post("/api/mandates/{reference}/approve", dependencies=[Depends(session)])
    async def approve_mandate(reference: str, body: MandateApproval):
        async with mandates.lock:
            return await mandates.approve(reference, body)

    @app.post("/api/mandates/{reference}/recover", dependencies=[Depends(session)])
    async def recover_mandate(reference: str):
        async with mandates.lock:
            return mandates.recover_receipts(reference)

    @app.post("/api/mandates/{reference}/revoke", dependencies=[Depends(session)])
    async def revoke_mandate(reference: str):
        async with mandates.lock:
            return await mandates.revoke(reference)

    @app.post("/internal/mandates", dependencies=[Depends(gateway)])
    async def request_mandate(body: MandateRequest):
        return mandates.draft(body)

    @app.get("/internal/mandates/{reference}", dependencies=[Depends(gateway)])
    async def mandate_status(reference: str):
        return mandates.status(reference)

    @app.post("/internal/mandates/{reference}/purchase", dependencies=[Depends(gateway)])
    async def mandate_purchase(reference: str, body: PurchaseRequest):
        return await mandates.purchase(reference, body)

    @app.post("/internal/search", dependencies=[Depends(gateway)])
    async def search(body: Search):
        return await engine.search(body)

    @app.get("/internal/status/{job}", dependencies=[Depends(gateway)])
    async def status(job: str):
        store.cleanup()
        if store.get(job) is not None:
            return engine.public_status(job)
        if not mandates.book:
            raise Refused("unknown_operation")
        return {**mandates.book.operation_status(job), "environment": engine.provider.name}

    @app.post("/internal/chat-select/{job}", dependencies=[Depends(gateway)])
    async def chat_select(job: str, body: PrivateSelection):
        return await engine.select(job, body.option, from_chat=True)

    return app
