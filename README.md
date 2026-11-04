# Pactora

A shopping MCP for Codex/Claude with privately approved spending mandates,
wallet-side policy checks and device-encrypted receipts. The hosted model sees
shopping requests and proposed choices; invoice access and fulfillment stay private.

For the consolidated scope, completed work, limitations and remaining roadmap,
start with [implementation status](docs/STATUS.md).

## Executed MVP proofs

Actual shielded private-chain payments now pass both ordinary Pactora policy
signing and a separate 2-of-2 FROST signing proof. These are regtest proofs, not
public testnet/mainnet payments or real Bitrefill purchases. See the
[MVP record and remaining gate](docs/MVP.md) and [proof harnesses](tools/proofs/README.md).

## What runs today

- A real MCP stdio server with six restricted tools; no unrestricted wallet, fetch,
  history, vault-read, or approval tool.
- A separate authenticated executor and private selection UI.
- Exact quote approval, USD-cent budget reservations, replay protection, and
  persistent uncertain-operation quarantine.
- RSA-OAEP/AES-GCM receipt envelopes decrypted with a non-exportable browser key.
- An explicitly labeled simulator exercising the complete flow without money.
- Protected Bitrefill REST catalog discovery and a read-only route-inventory probe.
- A testnet/regtest-only ZecPy service that independently checks mandates and actual
  fees. A controlled test-merchant adapter connects it to invoice receipt detection;
  real Bitrefill settlement remains disabled.

**Live ZEC-to-Bitrefill purchases are disabled.** There is no verified conversion
route, funded wallet, authenticated merchant session, or end-to-end settlement
evidence in this workspace. No configuration switch or model tool can bypass this
gate. A simulator receipt is not a real merchant receipt.

See [verification gates](docs/LIVE_GATES.md) and [privacy boundaries](docs/PRIVACY.md).
The exact checked and unchecked work is recorded in [implementation status](docs/STATUS.md).

## Install and run

Python 3.11+. From this directory:

```sh
uv sync --extra dev
uv run pactora init --directory ./data
uv run pactora serve --config ./data/config.json
```

Choose a password when prompted. Open <http://127.0.0.1:8787> in a user-controlled
browser. The first command creates secrets with restricted permissions; do not
commit or share the config. `data/` is ignored by git.

If port 8787 is occupied, set `PACTORA_ORIGIN` in the private config to an unused
loopback port (for example `http://127.0.0.1:8876`) and pass `--port 8876` to `serve`.

This is a **local simulator setup**, not OS-level isolation from a coding agent
running under the same user. For the privacy claim, put the executor/config on a
separate protected host or OS identity and use a private browser the agent cannot
inspect. Do not attach the private browser to the agent's computer-use tools.

The one-time private-view password hash, storage key, and gateway key are separate.
The CLI never prints wallet material. Do not give the gateway the private config.

## Connect Codex or Claude Code

On the agent host install this package, then supply **only** the restricted
gateway key from the protected service, plus its URL:

```sh
export PACTORA_EXECUTOR_URL=http://127.0.0.1:8787
# Supply PACTORA_GATEWAY_KEY through your credential manager, outside chat.
codex mcp add pactora -- /absolute/path/to/pactora/.venv/bin/pactora-mcp
```

Remote executor URLs must use HTTPS. The gateway inherits the two variables; it
does not need Bitrefill, NEAR, device-vault, or wallet credentials.

Claude Code uses the same stdio entry point:

```sh
claude mcp add --transport stdio pactora -- /absolute/path/to/pactora/.venv/bin/pactora-mcp
```

For other MCP clients, set `command` to that executable and supply the same two
environment variables. Do not connect the raw merchant MCP alongside Pactora.

Try:

> Use Pactora to find gift cards in India under $5. Compare the options. Keep my
> final choice private and direct me to the private view for selection.

Open the private view, click **Refresh**, choose an option, inspect its exact quote,
and approve the simulated purchase. Refresh after a few seconds to reveal or
export the encrypted receipt. Ask the agent to check the reference: it gets only
generic completion, not the selected card. An example $40 substitution is included
to demonstrate the budget refusal.

### Optional chat choice

Enable **Allow choice in chat** for a pending decision in the private view. The
model can then propose an option with `choose_in_chat`. Exact approval still
happens privately. This explicitly gives up selection secrecy for that decision;
clearing temporary state does not erase the host's transcript.

## Live discovery and route inspection

The protected service can use `PACTORA_PROVIDER=bitrefill`, a `BITREFILL_TOKEN`,
`PACTORA_CHECKOUT_MODE=account` or `guest`, and a local Tor SOCKS proxy. Guest mode
requires sponsor-issued guest credentials, not an account key relabeled as guest.
Current discovery normalization is strict: it requires verified USD prices and
country metadata; unfamiliar response shapes fail closed.

```sh
uv run pactora probe-route --proxy socks5h://127.0.0.1:9050
```

This reads the NEAR asset inventory, creates no invoice/swap/deposit, and does not
verify settlement. Tor failure returns an error; it never retries directly.
No real Bitrefill invoice or purchase is created by this version, in either mode.

## Verify

```sh
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

The suite exercises the real ASGI app and MCP SDK dispatch, private-view auth/CSRF,
device decryption, tampering, the $40 rejection, aggregate budgets, timeouts,
restart quarantine, and protected HTTP failure. It makes no external purchases.

The adjacent ZecPy reference has a minimal invoice URI bug fix and regression
tests. [ZecPy patch record](docs/ZECPY.md). Omamori is a design reference, not a
vendored implementation; no Base smart-account or World ID/Jev integration is
present.

## Recovery and limits

- Do not retry an uncertain payment. Its allowance remains reserved.
- Detailed transaction context is encrypted in SQLite. Finished search state is
  logically cleared. Do not claim physical erasure of WAL files, SSDs, or backups.
- Browser private keys are non-exportable. Exported receipt ciphertext still
  requires that browser's key. Losing browser storage loses decryption access;
  cross-device key recovery is not implemented.
- One operator, one user, one process. No multi-tenant or production-readiness claim.
- Testnet TAZ cannot fund real purchases. The $5 live cap includes all fees and is
  a ceiling, not an authorization to spend outside its privately approved authorization.

Project code was created before the supplied hackathon's 11:00 IST implementation
window at the user's explicit request; do not represent it as eligible event-time
work. Reference dependencies retain their original provenance.



### Protected ZecPy wallet service

A separate testnet-only service now verifies exact Ed25519 payment approvals,
reserves a lifetime aggregate budget, journals recovery state encrypted, and
rebroadcasts only existing signed transactions. It keeps wallet authority outside
MCP. See [wallet provisioning, API and limitations](docs/WALLET_PRIVACY.md).
This is not connected to Bitrefill settlement or the shopping approval browser
view. Native regtest and network routing verification remain separate gates.


### Claude Code / Codex shopping

Use [agent setup](docs/AGENT_SETUP.md) to install the shopping skill and configure
our restricted MCP. Bounded mandates allow matching simulator purchases after one
private approval. Wallet-side policy enforcement is implemented independently.
No custom shopping CLI is planned; service/operator commands remain supported.
Live Bitrefill settlement remains disabled.
