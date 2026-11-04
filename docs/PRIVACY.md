# Privacy contract and threat model

## Supported claim

Final selection, merchant invoice, payment metadata and redemption secret are
withheld from the model-facing API in private mode. Temporary catalog state is
cleared after completion. The trusted executor sees the selection and handles
plaintext fulfillment before encrypting it to the user's device.

The model already knows the request and returned candidates. A uniquely specified
request, a one-option search, exact completion timing, or user-provided feedback
can let it infer the selection. Chat mode explicitly reveals it. No code here
erases upstream transcripts or model-provider data.

## Boundaries

| Boundary | Control | Residual risk |
|---|---|---|
| Model → MCP | Six typed tools; mandate drafts/purchase requests, no vault, wallet, raw-fetch or approve operation | Host transcript retains requests/candidates |
| Gateway → executor | Restricted bearer key; private endpoints require separate cookie | Same-user shell or browser access breaks isolation |
| Private view | Password, CSRF, strict Origin/Host, no-store, CSP, no analytics | Device compromise, screenshots, extensions |
| Secrets at rest | Separate AES-GCM operational key; device-encrypted receipt | Trusted service memory, stolen key, backups |
| Wallet | Testnet only; shielded flags; actual proposal fee cap | ZecPy alpha, sync-server trust and metadata limits |
| Third-party HTTP | HTTPS, exact destination allowlist, socks5h, no redirects/direct fallback | Tor exits, timing, authenticated identities |
| Merchant | Structured search criteria, no full conversation or wallet history | Merchant sees its searches/orders, account, required email |
| Conversion | Live gate closed | Deposit transparency, public destination asset, operator correlation |

Do not add telemetry, semantic-model screening, arbitrary callback URLs, public
receipt hashes, address-query APIs, or model-accessible receipt viewers without
revisiting this contract. The gateway key can search, propose legacy chat choices, draft mandates and
request purchases under privately approved mandates. It cannot approve or revoke
mandates. Exact purchases retain their separate private approval path.

## Isolation deployment requirements

The agent must not have SSH, Docker admin, OS user access, private-view cookies,
browser automation, backups, or configuration access to the protected executor.
A file with mode 0600 does not protect against an agent running as its owner.
Containers alone do not isolate an agent with host Docker access. Use a separate
host or tightly constrained OS identities; the development UI is not a sandbox.

Keep Tor's SOCKS listener bound to its private network. Block executor direct WAN
egress (IPv4 and IPv6), including DNS; allow only Tor and required private services.
Wallet traffic uses ZecPy's separate isolated circuits. Merchant and conversion
clients generate fresh SOCKS credentials per HTTP operation. Tor must be configured
with `IsolateSOCKSAuth` (see `deploy/torrc`) for that circuit-isolation request to
take effect. This is not proof against timing correlation. ZecPy Tor does not proxy
the coding agent's own model-provider traffic.

No global observer or malicious-device protection is claimed. The simulator does
not test real anonymity sets or merchant anti-fraud behavior.

## Retention

- Abandoned searches/quotes expire after 15 minutes.
- Approval and quote become immutable once funds are reserved.
- On completion, temporary products and quote plaintext are removed from live
  application records; only device-encrypted receipt and minimal status remain.
- Uncertain execution keeps encrypted recovery state and its reservation.
- Financial anti-replay records remain. Never clear them just to say "forgotten".
- SQLite secure_delete is enabled, but WAL files, storage hardware, crash dumps and
  external backups invalidate any claim of physical deletion.
- Device keys are non-exportable. Receipt export is not a device-key backup.



## Bounded mandate disclosure

The hosted shopping model sees requirements, sanitized candidates and choices it
proposes. Private approval signs exact eligible product/package combinations and
limits; it does not erase those model disclosures. Merchant/order/invoice mapping
is attested by the trusted adapter. Wallet mandate verification independently
checks that mapping against signed eligibility and debit limits; it does not prove
merchant delivery. Refused purchase references are retained, uncertain reservations
are not released, and receipt recovery never re-executes a purchase.
