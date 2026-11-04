"""Browser/MCP QA fixture. Public test credentials; loopback and simulator ONLY.

Never point this script at a real wallet or merchant account.
"""

import asyncio
import base64
import secrets
import tempfile
from pathlib import Path

import uvicorn

from pactora.app import create_app
from pactora.config import Settings
from pactora.crypto import password_hash
from pactora.models import Search

settings = Settings(
    origin="http://127.0.0.1:8876",
    data_dir=Path(tempfile.mkdtemp(prefix="pactora-browser-qa-")),
    master_key=base64.b64encode(secrets.token_bytes(32)).decode(),
    gateway_key="QA-ONLY-GATEWAY-TOKEN-NO-REAL-ACCESS-2026",
    password_hash=password_hash("demo-only-pactora-2026"),
)
app = create_app(settings)
asyncio.run(app.state.engine.search(Search(query="Indian gift cards", country="IN", budget_cents=500)))
uvicorn.run(app, host="127.0.0.1", port=8876, access_log=False)
