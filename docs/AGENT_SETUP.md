# Claude Code / Codex shopping setup

The shopping interface is Claude Code or Codex. There is no custom shopping CLI
or local model runtime in this scope. Existing `pactora`, `pactora-wallet`,
`pactora-wallet-approve` commands are service/operator tools and remain supported.

## Skills and client configuration

Install **only** `skills/pactora-shopping` into the shopping workspace's
`.claude/skills/pactora-shopping` for Claude Code or
`.agents/skills/pactora-shopping` for Codex. Copy the whole directory. Invoke
`/pactora-shopping` in Claude Code or `$pactora-shopping` in Codex. Both skills
use standard SKILL.md frontmatter; automatic discovery remains enabled.

The optional `skills/pactora-wallet-setup` belongs only in a separate operator
workspace/account. It provides provisioning guidance, not automated secret
handling. Neither skill contains credentials or signs payments.

Install Pactora's Python package into its virtual environment. On the gateway
host create an owner-only regular JSON file, owned by its OS identity, with
`executor_url` and the limited `gateway_key`. Provision its value in a trusted
terminal outside model tool sessions; never paste the key into a chat. That key
is distinct from the wallet token and approval key. No wallet credential belongs
on the gateway host. Environment-based gateway configuration remains compatible.

Register the following stdio server using the client's MCP configuration:

```json
{
  "mcpServers": {
    "pactora": {
      "command": "/absolute/path/pactora/.venv/bin/pactora-mcp",
      "args": ["--config", "/protected/gateway.json"]
    }
  }
}
```

That is Claude Code's JSON shape. The corresponding Codex TOML entry is:

```toml
[mcp_servers.pactora]
command = "/absolute/path/pactora/.venv/bin/pactora-mcp"
args = ["--config", "/protected/gateway.json"]
```

The gateway must be able to reach the protected executor through HTTPS or a
protected loopback tunnel. The shopping agent must have no access to executor or
wallet files, shell, SSH, Docker administration, private browser session or secret
configuration. Running all services as the same unrestricted OS user is not a
privacy boundary. Do not add the public Bitrefill MCP directly to this client.

## One approval, bounded shopping

1. `search_products` returns sanitized options. The hosted model sees these and
   the user's request. It also knows any option it proposes; no forgetting is promised.
2. `request_mandate` takes the search reference, per-purchase and aggregate USD
   cents and ZEC zatoshis, purchase count and duration (maximum one hour). The
   model must obtain explicit ZEC limits from the user, never invent an FX rate.
3. The private view shows all eligible product/package combinations, merchant,
   wallet/network, monetary limits and expiry. Catalog-priced candidates above the
   per-purchase limit are excluded. Final invoice prices including fees are checked
   again; a catalog price within the limit does not guarantee checkout fits.
4. The human approves there. The private backend signs an immutable Ed25519
   mandate. MCP can create drafts and check generic state, never approve or revoke.
5. `request_purchase` takes the mandate reference, search reference, option and an
   explicit `purchase_ref`. The server resolves the invoice; the model cannot supply
   a recipient. Retry with identical contents and the same reference. An additional
   purchase requires a new reference and available authorization.
6. Read receipts or revoke in the private view. Unknown execution retains reserved
   budget/count. Receipt recovery only delivers an already stored result; it never
   calls the merchant again. Signed wallet recovery rebroadcasts the same transaction.

The simulator demonstrates this whole flow. Its authority key is created and
persisted owner-only under the simulator state directory. It is NOT a production
key provisioning workflow. Total simulated spending is still bounded by the
existing global 500-cent maximum, including legacy exact-payment reservations.
A rejected purchase reference cannot be changed and rerolled. Ledger reservations
are conservative and not released automatically after uncertainty or failure.

## Wallet authority and bridge

See WALLET_PRIVACY.md for the dedicated testnet wallet service and native ZecPy
build. Set `PACTORA_MANDATE_KEY_FILE` to an owner-only file containing the base64
raw Ed25519 approval private key in the trusted backend. The wallet configuration
contains only its public key. Set matching `PACTORA_WALLET_ID` / wallet `wallet_id`.
The commerce mandate network is `test`; regtest wallet tests install their own
explicitly signed `regtest` mandates.

Optional backend-only bridge settings:

* `PACTORA_WALLET_URL`: HTTPS wallet API URL or a protected loopback tunnel.
* `PACTORA_WALLET_TOKEN_FILE`: owner-only file containing the wallet API bearer token.

When configured, private approval registers the signed mandate at the wallet
boundary before local activation. Revocation must be acknowledged there before
reporting success. The wallet independently verifies signatures and atomically
reserves its own mandate budget/count before signing. This bridge does NOT enable
live shopping settlement. Real invoice resolution and ZEC conversion are closed.

Wallet internal API additions: `POST /mandates` with `document` and `signature`;
`POST /mandates/{reference}/revoke`; and
`POST /mandates/{reference}/purchase` with `purchase_ref`, `binding`, `package`,
`total_cents`, `quote_expires`. `binding` is the exact PaymentBinding from
WALLET_PRIVACY.md. Only the trusted merchant executor may call this API. It attests
invoice authenticity and product-to-recipient mapping; the wallet enforces the
signed product/package allowlist, network/wallet/merchant, expiry and debit limits.
The independent native fee determines ZEC debit, never an agent-supplied fee.
A live adapter must establish that dollar totals include all conversion/network
costs with a verified expiring quote before it can be enabled. No live FX/conversion
verification is implemented in this release.

## Verification and limits

Run `pytest`, Ruff and the simulator smoke against `tests/serve_demo.py` using
`tests/stdio_mandate_smoke.py`. The smoke uses real MCP stdio and HTTP, not a hosted
Claude/Codex session. Actual interactive installation in those two clients remains
unverified. Skills were parsed/checked locally; no model-behavior evaluation was run.

Native test: `zecpy/tests/test_devnet_mandates.py` requires the modified ZecPy
extension, installed Pactora and the local regtest chain. It is separate from
fake-wallet tests. Tor packet-capture/failure testing remains required. Browser
visual QA has not been completed for the mandate view. Mainnet stays closed; no
funds moved. A Zcash test merchant is not proof of real Bitrefill fulfillment.


## Pactora rename compatibility

The Python package/distribution, skills and preferred commands are now `pactora`.
`PACTORA_*` environment variables take precedence over legacy `VEILCART_*` names.
Legacy `veilcart` operator command aliases remain available. Encryption AAD,
signed-document domains, session cookie names and IndexedDB identifiers retain
legacy values so existing records and browser keys remain usable. They are wire
format compatibility identifiers, not the project branding. The repository may
remain checked out in a directory called `veilcart`; examples use placeholder
absolute paths to your actual checkout.
