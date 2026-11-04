# Pactora — project context, work checklist and implementation handoff

Snapshot: 4 November 2026. Prepared from the current application source, parent-thread verification outputs and the completed local proof reports. This is a planning/status document, not a claim that every checklist item is implemented.

**Read this first:** Pactora has a working simulator, software-enforced spending mandates and a confirmed native shielded **regtest** payment. FROST **key generation** has passed. A FROST-signed payment, real Bitrefill fulfillment, public-testnet payment and observed Tor routing are not established by the inspected evidence.

The project branding and Python package are **Pactora / `pactora`**. The current checkout directory is named `Factora/`; this directory name does not rename the product. Some historical documents and compatibility identifiers still use VeilCart. Existing `docs/STATUS.md` contains older milestone snapshots that predate the latest native proof.

## 1. What we are building and why

Pactora lets a Claude Code or Codex shopping agent discover products and request purchases under a mandate the user approves privately. The agent receives purchasing capability without receiving wallet keys, unrestricted signing authority or access to redemption secrets.

The problem has three distinct parts:

1. **Authorization:** a budget alone does not prevent buying an unrelated product. We must verify the approved product/package, merchant, invoice, recipient, network, fees, expiry and purchase count before signing.
2. **Privacy:** ordinary chat checkout can expose wallet history, invoices, payment links and redemption codes. We keep sensitive execution and fulfillment information in protected services and the private user interface.
3. **Completion:** payment success does not establish delivery. We must verify that the correct deliverable was issued and privately accessible, or explicitly show an unresolved fulfillment problem.

The intended workflow is:

1. User gives a shopping request to Claude/Codex.
2. The shopping skill uses restricted Pactora MCP tools to discover and compare candidates.
3. The user privately approves a concrete eligible product/package set, merchant, budgets, count and expiry.
4. The agent requests an eligible purchase using an explicit purchase reference.
5. The trusted adapter resolves and checks the invoice. The policy service and wallet verify authorization.
6. Payment is signed and submitted through the permitted payment path.
7. A fulfillment verifier follows the existing order, validates the expected deliverable and stores it encrypted.
8. The private interface shows the receipt and deliverable. The agent receives generic status only.
9. Retries reconcile an existing operation; they never silently buy again.

Steps 7–8 are only partially implemented today. The test merchant proves receipt of test funds, not delivery of real goods.

## 2. Current MVP decision and scope

The agreed basic MVP has **three separately labeled proofs**:

| Proof | Success criterion | Current evidence |
| --- | --- | --- |
| Zcash policy payment | Actual shielded test-network payment, receiver confirmation, unauthorized purchase refusal and safe retry | Confirmed on private regtest |
| FROST signing | A real shielded transaction completed by two signing participants; one alone cannot complete the session | DKG passed; payment/signature proof still unverified |
| Bitrefill purchase | Agent discovers a product, purchases through an accepted supported payment path and privately delivers the actual product | No completed live purchase |

These may use different payment paths. A Bitrefill purchase paid from a separate account/balance does not prove that ZEC funded it. Native regtest tokens cannot buy real goods. ZEC-to-Bitrefill conversion is a separate unresolved integration.

### Included

- Claude Code/Codex interface, shopping skill and restricted MCP.
- Private approval, bounded mandates, replay protection and durable recovery.
- Dedicated protected ZecPy wallet and a watch-only controlled receiver.
- Separate FROST protocol/payment demonstration.
- A narrow Bitrefill integration once funding and safety prerequisites are satisfied.
- Explicit payment-versus-fulfillment status and private receipts.

### Outside this MVP

- A custom conversational CLI or local-model shopping worker.
- General agent shell/browser control on the protected hosts.
- Arbitrary smart-contract execution on Zcash.
- Guaranteed anonymity, guaranteed refunds or trustless delivery of off-chain goods.
- Production multi-user custody and unrestricted mainnet spending.
- An integrated FROST-funded ZEC conversion and Bitrefill purchase until separately proven.

Administrative service commands remain useful and should not be deleted merely because the custom shopping CLI direction was removed.

## 3. Architecture and trust boundaries

| Component | Responsibility | Must not expose to the shopping agent |
| --- | --- | --- |
| `pactora-shopping` skill | Explain discovery, mandate and purchase workflow | Instructions to bypass approval, read credentials or handle redemption secrets |
| Restricted MCP | Search, draft mandates, request eligible purchases, generic status | Approval/revocation authority, raw wallet or receipt access |
| Private backend/UI | Authenticate user approval, sign mandates, show receipts and recovery | Approval keys, private cookies, invoice tokens and plaintext fulfillment |
| Merchant adapter | Verify product-to-invoice/recipient mapping and reconcile orders | Raw merchant payloads, arbitrary URLs or merchant-authenticated capabilities |
| Mandate ledger | Durable eligibility, budget/count reservations and purchase-reference binding | Resettable allowance or changed retry contents |
| ZecPy service | Local scan, proposal checks, signing and same-transaction rebroadcast | Mnemonic, spending/viewing keys and unrestricted signing API |
| Controlled test merchant | Derive invoice-specific receiver addresses and detect shielded receipt | Any claim of usable gift-card/eSIM delivery |
| FROST participants | Joint signing with separate key shares | Shares, signing nonces and participant authentication secrets |
| Optional operator skill | Explain provisioning in a separate trusted environment | Secret files or key material loaded into model context |

**Current enforcement is software policy.** Zcash validates the transaction and signatures, not Pactora product categories or dollar budgets. The existing full-key service can sign alone if compromised. FROST can require multiple participants, but each policy restriction still needs an honest enforcing signer. The current production signing path is not converted to threshold custody.

A separate process under the same unrestricted OS user is not a reliable isolation boundary. The agent must not have filesystem, SSH, debugging, Docker-administrator or private-browser access to the protected services. Keeping two shares on one host demonstrates the threshold protocol, not protection against compromise of that host.

The trusted merchant adapter currently attests invoice authenticity and product-to-recipient mapping. Wallet-side mandate checks do not independently prove that the merchant will deliver.

## 4. Status legend and evidence rules

- **Verified:** a specific executed check or completed evidence report supports the claim.
- **Implemented:** code exists; this alone does not prove native, live or deployment behavior.
- **To do:** required work not completed.
- **Blocked:** a named external prerequisite is missing.
- **Deferred:** deliberately outside the current MVP.

Checked boxes below mean the stated item is done at the explicitly stated level. An implemented checkbox is not a verified live-integration claim.

### Verification records available at this snapshot

| Record | What it establishes | What it does not establish |
| --- | --- | --- |
| Historical full application suite: 82 passing tests | Earlier committed application baseline and rename compatibility | Coverage of all subsequently added code |
| Later full application run: 91 passing tests | Application state at that point in the parent thread | A fresh full run after the final eligibility regression and proof-script edits |
| Controlled merchant/probe targeted run: 10 passing tests | Mocked merchant/policy/confirmation behavior in that targeted run | Actual on-chain transfer in those mocked tests |
| ZecPy native unit run: 37 passing tests | Executed native wallet/invoice/audit unit checks | Public-testnet transfers or network anonymity |
| Earlier real MCP stdio + HTTP simulator smoke | One private approval, two simulated purchases, retry and cap refusal | Hosted Claude/Codex behavior or real merchant fulfillment |
| `proof-state/native-payment-3/report.json` | Actual 100,000-zatoshi shielded regtest receipt, no additional transaction for identical retry, unauthorized product blocked | FROST, Bitrefill, public testnet or Tor verification |
| `proof-state/frost-dkg-3/report.json` | Two-participant, threshold-two RedPallas DKG with matching group | A threshold signature or payment; its report explicitly marks those false |

`proof-state/` is ignored private runtime state. Do not commit it, inspect/share wallet secrets from it, or publish raw logs containing shares/viewing material. Its reports can be reviewed locally and sanitized evidence copied deliberately. Presence of `tools/proofs/frost_payment.py` is not evidence it completed successfully.

## 5. Workstream A — agent, skills and private interface

### Done

- [x] Shopping skill and separately packaged operator setup skill exist.
- [x] Six restricted MCP tools are implemented: search, generic purchase status, legacy opt-in chat choice, mandate draft, mandate status and mandated purchase request.
- [x] Private authentication, approval/revocation routes and receipt interface are implemented.
- [x] Simulator MCP stdio workflow has been exercised with a real MCP client.
- [x] Pactora package/commands are implemented with legacy command/environment compatibility.

### To do

- [ ] Install and exercise the shopping skill in an actual Claude Code session.
- [ ] Repeat in Codex; do not infer cross-client behavior from a stdio smoke alone.
- [ ] Check browser login, approval, revocation, IndexedDB/device keys, receipt reveal and recovery.
- [ ] Complete visual QA and accessibility/error-state checks.
- [ ] Show active/expired/revoked mandate status accurately in the private view.
- [ ] Clearly label simulator, controlled regtest merchant and real Bitrefill modes.
- [ ] Ensure agent-visible instructions never imply that selecting in chat can be forgotten.

Acceptance: a user can approve one bounded mandate privately, the agent can request permitted purchases without another approval, and sensitive execution/fulfillment details do not appear in model responses.

## 6. Workstream B — mandates, authorization and recovery

### Done

- [x] Signed immutable mandates bind wallet/network, merchant, product/package fingerprints, per-purchase and aggregate caps, maximum count, version and expiry.
- [x] Independent wallet-side checks and durable purchase-reference reservations are implemented.
- [x] Changed retries, policy refusals, revocation and uncertain outcomes have dedicated logic/tests.
- [x] Known signed transactions have a same-transaction rebroadcast path.
- [x] Stored receipt delivery can recover without calling the merchant again.
- [x] A real native run exposed proposal construction occurring before product eligibility; a preflight eligibility check and regression test were added.
- [x] A subsequent native proof confirmed receipt, safe retry and unauthorized-product refusal.

### To do

- [ ] Run the complete current application suite after all latest changes and record its exact count.
- [ ] Run final Ruff checks including `tools/proofs/`, JavaScript syntax and proof-helper build checks.
- [ ] Test crash/restart at registration, reservation, signing, broadcast, fulfillment persistence and receipt encryption boundaries.
- [ ] Review whether every refusal/timeout path consistently binds its purchase reference and preserves conservative allowance.
- [ ] Document the trusted adapter's role in invoice/destination mapping precisely.
- [ ] Verify revocation propagation when the wallet bridge is unavailable or only one side persisted the update.
- [ ] Keep existing encryption/signed-record identifiers compatible; renaming is not a migration strategy.

Acceptance: altered product/recipient bindings, stale quotes, expired/revoked mandates and exhausted caps never create an unauthorized signature; retries never create an accidental additional purchase.

## 7. Workstream C — native Zcash payment

### Done

- [x] Modified native ZecPy built and installed in the local application environment.
- [x] Offline native watch-bundle and split-signing/rebroadcast API smoke passed without printing a seed.
- [x] Official Zebra 7.0.0 Linux archive downloaded and SHA-256 checked.
- [x] Dedicated loopback regtest validator started; a cached Linux container image was used as the runtime after the full node image download failed.
- [x] Controlled watch-only merchant and invoice-specific shielded addresses are implemented.
- [x] Merchant confirmation checks use ZecPy local scanning/invoice detection.
- [x] Actual shielded regtest policy payment confirmed: 100,000 zatoshis.
- [x] Native proof confirmed unchanged retry created no second transaction and an unauthorized item was blocked.

### To do

- [ ] Make the local-chain bootstrap fully reproducible from a documented clean environment.
- [ ] Persist all test journal/authority configuration needed for safe proof recovery; do not rerun a half-finished payment blindly.
- [ ] Run the existing chain-dependent mandate and recovery tests against the running native chain.
- [ ] Repeat the complete MCP/private-UI controlled-merchant flow using actual native wallets, not only direct wallet-service calls and mocked HTTP tests.
- [ ] Demonstrate public-testnet receipt if feasible, with dedicated test wallets; label it separately from regtest.
- [ ] Verify Tor before making network-privacy claims. Direct loopback regtest intentionally does not test Tor.

Acceptance: reproducible payment and confirmed receiver evidence, with rejected cases producing no additional transfer. No mainnet enablement is needed for this proof.

## 8. Workstream D — FROST

### Done

- [x] Added FROST repository reviewed; threshold signing distinguished from policy enforcement.
- [x] Official `frost-client`, `frostd`, `zcash-sign` and development wallet tools built locally.
- [x] Local TLS setup corrected without modifying system trust.
- [x] Actual 2-of-2 RedPallas distributed key generation succeeded.
- [x] Separate FROST payment proof script and official-encoder network conversion helper are present.

### To do

- [ ] Inspect/review the payment proof script before running it; it was not verified complete at this snapshot.
- [ ] Confirm PCZT, pool and dependency compatibility across the pinned native/tool versions.
- [ ] Use an unfunded/new dedicated threshold watch wallet and private regtest funds only.
- [ ] Verify the signer/coordinator are authorizing the expected transaction data.
- [ ] Withhold participant two and establish that the session cannot complete; then complete with both participants.
- [ ] Apply and verify the threshold signature, broadcast the transaction and confirm actual receiver receipt.
- [ ] Preserve nonce/session safety on failures; no casual retries with reused signing material.
- [ ] Keep share/config/log files owner-only and outside source control/model context.
- [ ] Record that same-host participants do not provide independent host-compromise protection.

Deferred: replacing the default Pactora full-key service with independently deployed policy-enforcing threshold signers. A successful separate FROST transaction is not that integration.

## 9. Workstream E — Bitrefill and settlement

### Done

- [x] Typed discovery adapter and live-execution gates exist.
- [x] Read-only MCP contract probe exists; it blocks debit-capable tool calls.
- [x] Known immediate balance-debit and uncertain-result risks identified.

### Blocked / to do

- [ ] Operator obtains sponsor/API access and provisions credentials outside chat/source control.
- [ ] Establish dedicated funding and choose a supported low-cost real product.
- [ ] Run authenticated discovery/details and verify actual response schemas.
- [ ] Verify the protected network route with real requests.
- [ ] Confirm an enforceable maximum debit or reserved-price contract before enabling balance checkout; a preview alone is insufficient.
- [ ] Verify invoice/order reconciliation when the purchase response is lost.
- [ ] Implement a narrowly scoped supported-payment adapter with durable pre-debit operation recording.
- [ ] Complete the fulfillment workstream below before calling a purchase successful.
- [ ] Obtain explicit private approval for any real spend. The existing $5 ceiling is a limit, not blanket spending approval.
- [ ] Keep ZEC conversion disabled until deposits, fees, destination amounts, expiry, refunds and operator correlation are separately verified.

Bitrefill source facts: invoice polling exposes payment/delivery status and fulfillment information; account-balance checkout may debit immediately, including test products; an uncertain debit must not be submitted again. Keep invoice access capabilities private. These points are documented in the [partner integration guide](https://docs.bitrefill.com/docs/mcp-partner-integration-guide). They do not establish a refund guarantee or an atomic price bound.

## 10. Workstream F — fulfillment assurance: the mentor's missing requirement

### The question

> We paid, but did the user receive the particular product/service they paid for? What if nothing, only part of it, or unusable information comes back?

**Payment confirmation and fulfillment confirmation are separate facts.** A valid Zcash/FROST signature proves authorization of a transfer, not delivery of an eSIM or a working gift card. A merchant status saying “delivered” is a merchant assertion. A receipt file alone does not prove the underlying service works.

### What is currently missing

The controlled merchant only verifies receipt of test money. Its “receipt” explicitly says no real goods are delivered. Existing generic `completed` state can also mean stored-result/device delivery has finished; it is not a universal guarantee of successful redemption or service activation.

A real purchase must not become “completed” merely because:

- the wallet returned a transaction ID;
- payment was broadcast or confirmed;
- HTTP returned 200;
- the merchant reports success without the required deliverable;
- one order in a multi-order purchase was delivered;
- a code/link exists but the private user device cannot decrypt/access it.

### Proposed lifecycle — not implemented as a complete live fulfillment system

Track **payment**, **merchant fulfillment** and **private delivery** independently rather than overloading one status.

| Dimension | Minimum useful states |
| --- | --- |
| Payment | not started, reserved, signed, submitted, confirmed, uncertain, failed |
| Fulfillment | not started, pending, partial, merchant-delivered, failed, disputed |
| Private delivery | not stored, encrypted/stored, accessible to user, acknowledged |
| Refund | not requested, requested, pending, confirmed, refused/unresolved |

“Complete” should require the product-specific deliverables for every authorized item to be available in the private interface. Acknowledgement and activation/redemption remain separate claims. Keep model-facing status generic; detailed invoice/order reasons and deliverables belong only in the private UI.

### Required implementation checklist

- [ ] **F1 — bind the expected deliverable before paying.** Record approved product/package, quantity, region, denomination/data allowance and the provider's stable order identifiers. Do not let a post-payment response silently redefine what was purchased.
- [ ] **F2 — use a separate fulfillment verifier.** It reads the existing invoice/order through the trusted provider adapter. It never invokes checkout or payment. Authenticate the response and verify it belongs to this purchase.
- [ ] **F3 — follow each item.** Record per-order status and expected quantity. Partial fulfillment stays partial; do not mark the whole purchase complete.
- [ ] **F4 — validate required fields.** Parse the provider's actual schema; reject missing, malformed, mismatched or unsupported deliverables. Do not invent field names and call them verified.
- [ ] **F5 — preserve the result durably.** Encrypt the provider result before private device delivery; recovery must not require buying again. Persist state changes idempotently and avoid duplicate receipt insertion.
- [ ] **F6 — recover after restart.** Resume bounded polling of the same order. Use backoff, provider rate limits, an explicit timeout and an operator-visible next action. A timeout means unresolved delivery, not automatically failed payment.
- [ ] **F7 — verify private accessibility.** Confirm the encrypted artifact can be decrypted/rendered by the intended user device. Never send the plaintext back through the model to test it.
- [ ] **F8 — show the exact claim.** Distinguish “merchant issued”, “available privately”, “user acknowledged” and “activation/redemption confirmed”. Never claim a stronger state without evidence.
- [ ] **F9 — provide issue reporting.** Add a private way to report missing/invalid/partial fulfillment linked to this order and sanitized diagnostic evidence.
- [ ] **F10 — implement a recovery/refund workflow.** Use provider-supported support/refund operations only after verifying their actual contract and required authorization. Do not promise automatic refunds or release allowance on a merchant promise.
- [ ] **F11 — reconcile any refund.** Record amount, asset, recipient and status; require appropriate approval for sensitive changes. Keep refunds separate from purchase history. Do not automatically restore mandate capacity unless an explicit approved policy permits it.
- [ ] **F12 — fail closed for unknown schema/state.** Keep the order pending/private-attention. Do not retry payment, switch products, expose secrets to the agent or silently discard the case.

### Product-specific verification

| Product | What the verifier can check | What still needs stronger evidence |
| --- | --- | --- |
| Gift card | Correct brand/region/denomination/quantity, merchant delivery status, required code/PIN or authenticated claim link, private accessibility | Whether a code is unspent and accepted at redemption; use an official non-consuming check if available, otherwise user confirmation |
| eSIM | Correct destination/package, expected installation/activation artifact, provider-issued order status, private accessibility | Successful installation, coverage and actual usable data; check provider entitlement/activation status when supported or ask the user |
| Phone top-up | Bound recipient and amount, provider completion reference/status | Carrier-side balance change or explicit user confirmation |
| API/cloud credit service | Correct account/entitlement and provider acknowledgement | Read-only entitlement verification through an authorized interface; do not expose user credentials to the model |
| Controlled test voucher | Correct invoice received its test ZEC amount | No usable service exists; label it a payment proof only |

Do not validate a gift card by automatically redeeming it, install an eSIM automatically or consume a paid service as a “test” without explicit user authorization. Those actions can be irreversible or billable.

### Limits of assurance

A signed merchant receipt helps bind the merchant's statement to an order; it does not prove truthful delivery. If the provider offers no independent verification interface, the honest state is “merchant-delivered; user verification pending”. Do not describe it as cryptographic proof of service.

Escrow/arbitration may be future design options, but plain Zcash payments and FROST alone do not implement atomic exchange for off-chain goods. Pre-signature policy controls authorization. It cannot force delivery after funds have been transferred. For the MVP, rely on a documented trusted provider, accurate states, private evidence and an explicit dispute/refund path.

### Fulfillment tests that must pass before enabling a live adapter

- [ ] Paid/confirmed invoice with no deliverable remains pending and does not buy again.
- [ ] Delivered flag with missing/invalid code/link becomes private attention.
- [ ] Wrong product, region, package, denomination or quantity is rejected.
- [ ] One of multiple orders delivered produces partial fulfillment.
- [ ] Late delivery is recovered from the same order without a second payment.
- [ ] Timeout/restart/rate-limit handling preserves identifiers and resumes safely.
- [ ] Result saved before a crash can be delivered privately after restart.
- [ ] Duplicate status/webhook events do not duplicate receipts or payment.
- [ ] User-device decryption failure does not imply merchant/payment failure.
- [ ] Invalid/previously used code can be reported privately without leaking it to the agent.
- [ ] A requested but unconfirmed refund is not represented as returned funds.
- [ ] Generic MCP results and all logs omit codes, invoice access tokens and private payment details.

## 11. Workstream G — privacy, security and deployment

### Implemented foundations

- [x] Keys/approval credentials are absent from normal model-facing tool responses.
- [x] Encrypted operation records and device-encrypted receipt support exist.
- [x] HTTPS/host restrictions and protected merchant transport exist.
- [x] Local ZecPy scanning avoids unnecessary identifying address/transaction lookups in its normal path.
- [x] Mainnet and real Bitrefill execution gates remain closed.

### Still to prove/harden

- [ ] Observe actual Tor routing, DNS handling, circuit isolation and failure behavior.
- [ ] Verify direct egress is blocked where claimed, including IPv6 and DNS.
- [ ] Separate protected service identities/hosts and review agent access paths.
- [ ] Review logs, exceptions, backups, core dumps, browser extensions and screenshots.
- [ ] Restrict/bind allowed merchant redirects and fulfillment URLs; never let untrusted order text turn into unrestricted fetching.
- [ ] Review retention and deletion honestly; financial anti-replay/recovery records must remain.
- [ ] Document account/email/payment-source correlations and trusted conversion/provider visibility.
- [ ] Verify viewing-key/share backup and recovery without putting secrets into model context.

No “nobody can link any activity” claim is supported. Hosted Claude/Codex knows the shopping prompt and options/choices it sees. Merchants know their own orders. Tor, shielded payments and secret isolation address different observers.

## 12. Prioritized next steps for the implementing agent

This section is a handoff, not an instruction to a side-conversation assistant to resume parent-thread tools.

1. **Reinspect active state.** Confirm current checkout path, Git diff and completed proof reports. Do not assume an inherited process is still running or that a script exists unchanged. Do not overwrite concurrent work.
2. **Finish the FROST proof.** Review the existing runner/helper; use the successful DKG state and dedicated private-chain funds, apply the threshold signature and confirm actual receiver receipt. If compatibility fails, document the exact blocker.
3. **Run final current checks.** Complete the full application suite, native chain-dependent checks, Ruff including proof scripts, JS syntax and skill validators. Record precise evidence rather than replacing old test counts speculatively.
4. **Finish fulfillment design/tests before live checkout.** Implement separate fulfillment state and the F1–F12 checks for one narrow product/provider. This is the main missing business-completion safeguard.
5. **Obtain Bitrefill prerequisites.** Credentials, funding, supported product, enforced debit ceiling and reconciliation contract. Keep secrets outside chat. Keep the live gate closed if any prerequisite is missing.
6. **Exercise an actual agent and private browser.** Demonstrate a mandate purchase and rejected attack in Claude Code, then Codex; complete browser QA.
7. **Run one explicitly approved small real purchase.** Only after the prior gates pass; demonstrate actual private delivery or an honest unresolved state.
8. **Package the three proofs honestly.** Clearly distinguish regtest/public testnet, DKG/threshold payment, simulator/real Bitrefill, payment/fulfillment and application/OS privacy guarantees.

Do not expand into conversion, production custody or a custom CLI before these gates are closed.

## 13. Source map for humans and agents

| Area | Primary files |
| --- | --- |
| Agent tools and setup | `src/pactora/mcp_server.py`, `skills/pactora-shopping/`, `skills/pactora-wallet-setup/`, `docs/AGENT_SETUP.md` |
| Private UI/API | `src/pactora/app.py`, `src/pactora/static/app.js` |
| Mandates and purchase orchestration | `src/pactora/mandates.py`, `src/pactora/mandate_commerce.py` |
| Wallet boundary | `src/pactora/wallet_service.py`, `wallet_api.py`, `wallet_bridge.py`, `wallet.py` |
| Controlled native merchant | `src/pactora/test_merchant.py`, `controlled_provider.py`, `merchant_cli.py` |
| Bitrefill status/probe | `src/pactora/providers.py`, `bitrefill_probe.py`, `docs/LIVE_GATES.md` |
| Local proofs | `tools/proofs/native_payment.py`, `frost_dkg.py`, `frost_payment.py`, `view-network/` |
| Tests | `tests/`, plus native tests in sibling `zecpy/tests/` |
| Privacy and wallet documentation | `docs/PRIVACY.md`, `docs/WALLET_PRIVACY.md`, `docs/ZECPY.md` |
| Historical status | `docs/STATUS.md`; older claims may be superseded by current evidence |

The sibling `zecpy/` and `frost/` directories are reference/dependency repositories. `.tools/` contains ignored local tooling. Do not stage them wholesale or accidentally add nested repositories as Git links. Keep upstream attribution and record dependency/tool revisions when sharing proofs.

## 14. Short context block to give another agent

> We are building Pactora: Claude Code/Codex shopping through restricted MCP with privately approved deterministic spending mandates, protected ZecPy signing and private fulfillment. No custom conversational CLI. Constraints currently run in software, not a Zcash smart contract. FROST provides threshold signing, not automatic product/budget enforcement. Simulator flow works; an actual shielded regtest policy payment of 100,000 zatoshis confirmed with safe retry and unauthorized-item refusal. Two-party RedPallas DKG passed; a FROST-signed payment is not yet established. Real Bitrefill checkout/fulfillment and observed Tor routing remain unverified. The checkout is currently named Factora but package/branding is Pactora. Reinspect current diffs and proof reports before continuing. Finish FROST and final verification; add separate payment/fulfillment/private-delivery states and product-specific checks. A merchant receiving payment is not proof the user received a usable service. Keep live gates closed until credentials, funding, safe debit limits, reconciliation and fulfillment prerequisites pass. Never read secrets into model context, reset uncertainty reservations, retry an ambiguous debit or claim complete anonymity/refund guarantees.
