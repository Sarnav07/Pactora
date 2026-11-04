---
name: pactora-agent-setup
description: Connect Claude Code or Codex to an already provisioned Pactora shopping MCP gateway and diagnose the connection without exposing credentials. Does not provision or fund wallets.
---

Use this for agent connection only. The operator provisions Pactora and its wallet separately.
Never open wallet configuration, seed files, receipt storage or backend configuration.
Never ask for tokens in chat or print the gateway file. Never automate the private approval view.

1. Locate the user's installed Pactora Python and an operator-provided, owner-only
   gateway JSON path. The file has only `executor_url` and `gateway_key`.
   Ask for paths if absent; do not search their disk for secrets.
2. Register a local stdio MCP process using the installed interpreter:
   - Claude Code: `claude mcp add --scope local pactora -- /absolute/path/.venv/bin/python -m pactora.mcp_server --config /protected/path/gateway.json`
   - Codex: `codex mcp add pactora -- /absolute/path/.venv/bin/python -m pactora.mcp_server --config /protected/path/gateway.json`
   Use the user's requested client. This edits that client's MCP configuration;
   connection setup authorizes the registration, not wallet access or spending.
   Do not overwrite a conflicting existing entry; explain the conflict.
3. Run `scripts/doctor.py` with that interpreter and `--gateway-config` pointing
   to the supplied file. It emits only booleans and the environment label.
   A complete result requires all six permitted tools and no additional tools.
4. Ask the user to reconnect/restart their client when necessary. Verify tools
   in the new session. Use `pactora-shopping` for discovery and purchases.
   An unavailable connection is not permission to read secrets or bypass MCP.

Explain: hosted models see prompts, candidates and proposed choices. Wallet data,
private approval and receipt contents stay outside the tool responses. Client
transcripts and memory hooks can retain whatever the model receives. A separate
working directory alone is not filesystem or browser isolation.
