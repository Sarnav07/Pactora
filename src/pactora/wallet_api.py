"""Internal backend-to-wallet API. Never publish this listener or its credential to MCP."""

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .engine import Refused
from .mandates import Mandate
from .wallet_service import PaymentBinding


class Authorization(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    signature: str = Field(min_length=1, max_length=128)


class SignedMandate(Authorization):
    document: Mandate


class MandatedPurchase(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    purchase_ref: str = Field(min_length=1, max_length=128)
    binding: PaymentBinding
    package: str = Field(min_length=1, max_length=256)
    total_cents: int = Field(gt=0)
    quote_expires: int = Field(gt=0)


def create_wallet_app(service, token):
    if len(token) < 32:
        raise ValueError("wallet API credential must contain at least 32 characters")

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    async def authenticated(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + token):
            raise Refused("unauthorized")

    @app.middleware("http")
    async def private_response(request: Request, call_next):
        # Reject browser requests, including localhost cross-origin calls.
        if request.headers.get("origin") or request.headers.get("sec-fetch-site"):
            return JSONResponse({"error": "browser_access_forbidden"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Refused)
    async def refused(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})

    # Validation errors must not echo destinations, signatures or other request values.
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.post("/mandates", dependencies=[Depends(authenticated)])
    async def install(body: SignedMandate):
        ref = service.mandates.install(body.document.model_dump(), body.signature)
        return service.mandates.status(ref)

    @app.post("/mandates/{reference}/revoke", dependencies=[Depends(authenticated)])
    async def revoke_mandate(reference: str):
        async with service.lock:
            service.mandates.revoke(reference)
        return service.mandates.status(reference)

    @app.post("/mandates/{reference}/purchase", dependencies=[Depends(authenticated)])
    async def mandated_purchase(reference: str, body: MandatedPurchase):
        return await service.purchase_under_mandate(
            reference, **body.model_dump(exclude={"binding"}), binding=body.binding
        )

    @app.post("/sync", dependencies=[Depends(authenticated)])
    async def sync():
        return await service.sync()

    @app.post("/prepare", dependencies=[Depends(authenticated)])
    async def prepare(binding: PaymentBinding):
        return await service.prepare(binding)

    @app.post("/operations/{reference}/execute", dependencies=[Depends(authenticated)])
    async def execute(reference: str, approval: Authorization):
        return await service.execute(reference, approval.signature)

    @app.post("/operations/{reference}/recover", dependencies=[Depends(authenticated)])
    async def recover(reference: str):
        return await service.recover(reference)

    @app.post("/operations/{reference}/revoke", dependencies=[Depends(authenticated)])
    async def revoke(reference: str):
        return await service.revoke(reference)

    @app.get("/operations/{reference}", dependencies=[Depends(authenticated)])
    async def status(reference: str):
        return service.status(reference)

    return app
