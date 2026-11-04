# Pactora — project context, work checklist and implementation handoff

Snapshot: 4 November 2026. Prepared from the current application source, parent-thread verification outputs and the completed local proof reports. This is a planning/status document, not a claim that every checklist item is implemented.

**Read this first:** Two of the three MVP proofs are verified: an actual shielded **regtest** payment under Pactora software policy, and a separate **2-of-2 FROST-signed shielded regtest payment**, each with a confirmed receiver receipt of 100,000 test zatoshis. Real Bitrefill fulfillment, public-testnet payment, observed Tor routing and deployed signer isolation remain unverified. The application suite passes **115 tests**, with **37 native unit tests** and **6 targeted native integration tests** also passing.

The project branding and Python package are **Pactora / `pactora`**. The current checkout directory is `Pactora/`. Some historical documents and compatibility identifiers still use VeilCart. Read the latest section of `docs/STATUS.md`, [MVP results](MVP.md) and [sanitized execution evidence](evidence/mvp-proofs.json) before older milestone snapshots. The regtest validator was running before and after the latest verification; temporary browser-QA services were stopped and private state is preserved.

## Current integration and final demo checklist (4 November 2026)

The current implementation includes **demo-only** expected-result validation, separate payment/fulfillment/private-delivery states, encrypted receipt acknowledgement and private issue reporting, bounded reconciliation, revocation recovery and refusal binding. The dashboard shows delivery details under Live. Background confirmation polling observes already-broadcast transactions; it does not initiate wallet purchases. This is not a live Bitrefill adapter or proof of redeemable goods.

Release preparation: a dedicated `deploy/Dockerfile.wallet` builds the pinned patched ZecPy dependency; the existing simulator image remains separate. `tools/proofs/bootstrap_tools.py` prepares pinned proof sources and binaries in a new directory. The wallet image built on Docker Desktop Linux arm64 and the patched methods imported with networking disabled. The proof bootstrap completed in a new macOS arm64 directory, and its fresh Python environment passed 115 tests. Existing host toolchains/caches were used; a fresh operating-system setup and new-chain proof replay remain unverified. See the deployment and proof-tool README files for commands.

Priority for the final demonstration:

Verification on 4 November 2026: **115 application tests passed**, followed by successful browser/MCP simulator and controlled native regtest browser/MCP checks. See [sanitized end-to-end results](evidence/e2e-verification-2026-11-04.json). The first native harness invocation stopped before funding because the selected directory lacked the miner mnemonic; a fresh state directory and the existing dedicated regtest miner were used for the successful run. The running regtest container was left running as found. Interactive Codex/Claude sessions, real Bitrefill delivery, Tor routing and deployed isolation were not verified.

- [x] Integrate the dashboard, fulfillment and recovery work.
- [x] Run the application suite on the integrated working tree: 115 tests passed. Ruff, JavaScript syntax and Git diff checks passed.
- [x] Run browser/MCP simulator verification on the integrated code: approval, purchase, refusal, retry, receipt reveal and reload, acknowledgement, issue reporting, revocation, logout and mobile overflow check passed using temporary Playwright and Chrome.
- [ ] Rehearse the actual Claude Code and Codex skill flows, each with a private browser inaccessible to the shopping agent. Record generic model-visible responses only.
- [x] Reproduce the controlled native-wallet browser/MCP flow using dedicated regtest state: browser approval and receipt decryption, actual 100,000-zatoshi receiver confirmation, safe retry, unauthorized-product refusal and revocation passed. This is separate from the FROST proof.
- [ ] Prepare a concise demo sequence: introduce the mandate and its scope, show private approval, permitted test purchase, a refused request, and the receipt with honest payment-versus-fulfillment labels. Have the sanitized proof summaries ready as fallback.
- [ ] Complete live provider prerequisites and fulfillment verification before any real purchase; real Bitrefill goods, public-testnet behavior and Tor routing remain unverified. Obtain explicit approval before real spend.

The FROST payment was already verified separately; the older branch progress note saying it remains outstanding has been superseded by `docs/MVP.md` and `docs/evidence/mvp-proofs.json`. The previous frontend prompt is not included in this handoff; confirm any additional requested visual direction before treating frontend work as final.

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
| FROST signing | A real shielded transaction completed by two signing participants; one alone cannot complete the session | Verified 2-of-2 RedPallas DKG, threshold signature application and confirmed regtest receipt; single-host protocol proof |
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
| Current full application suite: **115 passing tests** | Current Pactora logic, mocked HTTP integration, eligibility-before-proposal regression and invoice crash binding | Complete native/live behavior or deployed isolation |
| ZecPy native unit run: **37 passing tests** | Executed native wallet/invoice/audit unit checks | Public-testnet transfers or network anonymity |
| Native integration targets: **6 passing tests** | Recovery, proposals and native two-purchase mandate behavior against the private chain | Bitrefill fulfillment or Tor routing |
| Real MCP stdio + HTTP simulator smoke | One private approval, two simulated purchases, retry and cap refusal | Actual hosted Claude/Codex behavior or real merchant fulfillment |
| Ruff lint/format, JavaScript syntax, Rust helper formatting and bundled skill validators | Current source/skill checks passed; the helper compiled and participated in the FROST proof | Security audit or model-behavior evaluation |
| Earlier native Chrome inspection | Updated disclosure copy, simulator login and mandate details were inspected | Earlier interaction hit framing errors; the later browser/MCP tests passed as described above |
| `proof-state/native-payment-3/report.json` | Actual 100,000-zatoshi shielded regtest receipt, no additional transaction for identical retry, unauthorized product blocked | FROST, Bitrefill, public testnet or Tor verification |
| `proof-state/frost-dkg-3/report.json` | Two-participant, threshold-two RedPallas DKG with matching group | This earlier DKG-only report intentionally leaves signature/payment false |
| `proof-state/frost-payment-2/report.json` | Separate actual FROST signatures applied/verified, incomplete session with one participant, completed signing with both, confirmed shielded regtest receipt | Independent signer-host security, Pactora mandate enforcement by FROST, public testnet or Bitrefill |
| `docs/evidence/mvp-proofs.json` | Sanitized summaries and pinned dependency/tool revisions for both successful payment proofs | Public-chain evidence or a third-party attestation |

`proof-state/` and `.tools/` are ignored private runtime/tooling directories. Never commit shares, mnemonics, viewing keys, raw transaction plans or private logs. Review only deliberately sanitized reports for sharing. Successful journal/authority keys are retained in owner-only test state. Earlier failed attempts are preserved for inspection and must not be blindly resumed.

Reproduction instructions are in [tools/proofs/README.md](../tools/proofs/README.md). The official Zebra image download failed; a checksum-verified official Zebra 7.0.0 Linux binary ran in an existing Linux/glibc container with its normal entrypoint replaced and both RPC ports published only on host loopback. No existing database volume/account was used.

## 5. Workstream A — agent, skills and private interface

### Done

- [x] Shopping skill and separately packaged operator setup skill exist.
- [x] Six restricted MCP tools are implemented: search, generic purchase status, legacy opt-in chat choice, mandate draft, mandate status and mandated purchase request.
- [x] Private authentication, approval/revocation routes and receipt interface are implemented.
- [x] Simulator MCP stdio workflow has been exercised with a real MCP client.
- [x] Pactora package/commands are implemented with legacy command/environment compatibility.
- [x] Native Chrome login, updated privacy disclosure and bounded-mandate display inspected in simulator mode.
- [x] Bundled validators pass for both skills; PyYAML is now installed in the local tool environment.
- [x] UI copy acknowledges that the model knows proposed choices; simulator/controlled-merchant labels are implemented.

### To do

- [ ] Install and exercise the shopping skill in an actual Claude Code session.
- [ ] Repeat in Codex; do not infer cross-client behavior from a stdio smoke alone.
- [x] Verify simulator browser approval, revocation, IndexedDB persistence, receipt reveal and reload; separately verify native browser approval, receipt decryption and revocation. Full crash/recovery and other browser/device combinations remain to be tested.
- [ ] Complete visual QA and accessibility/error-state checks.
- [ ] Show active/expired/revoked mandate status accurately in the private view.
- [ ] Inspect each mode label in an actual browser; simulator labeling is visually checked, while controlled/live states still need browser verification.
- [ ] Exercise actual agent behavior to confirm it communicates disclosure limits; skill/UI text already states that proposed choices are known to the model.

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
- [x] Full current application suite passed: 115 tests.
- [x] Final Ruff checks include proof scripts; JavaScript syntax, Rust helper formatting/build, patch applicability and skill validators passed.
- [x] Controlled merchant order identity is persisted before native invoice creation; crash/rebinding regression test passes.
- [x] Trusted adapter assumptions are documented: the wallet does not independently fetch/verify merchant invoice authenticity.

### To do

- [ ] Test crash/restart at registration, reservation, signing, broadcast, fulfillment persistence and receipt encryption boundaries.
- [ ] Review whether every refusal/timeout path consistently binds its purchase reference and preserves conservative allowance.
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

- [ ] Repeat clean-environment bootstrap. A pinned startup helper and reproduction instructions now exist; the successful local setup used the equivalent verified binary/container path, not a clean-host replay of the helper.
- [x] Successful native proof runner persists journal and authority keys in owner-only test state. Earlier failed-run state is preserved separately; inspect it rather than automatically rerunning a payment.
- [x] Six targeted chain-dependent recovery/proposal/mandate tests passed against the private chain. The stale mandate-test signing domain was corrected and confirmation waits hardened.
- [x] Repeat the MCP/private-UI controlled-merchant flow using actual native wallets on regtest; browser approval, receipt decryption and confirmed payment passed on 4 November 2026.
- [ ] Demonstrate public-testnet receipt if feasible, with dedicated test wallets; label it separately from regtest.
- [ ] Verify Tor before making network-privacy claims. Direct loopback regtest intentionally does not test Tor.

Acceptance: reproducible payment and confirmed receiver evidence, with rejected cases producing no additional transfer. No mainnet enablement is needed for this proof.

## 8. Workstream D — FROST

### Done

- [x] Added FROST repository reviewed; threshold signing distinguished from policy enforcement.
- [x] Official `frost-client`, `frostd`, `zcash-sign` and development wallet tools built locally.
- [x] Local TLS setup corrected without modifying system trust.
- [x] Actual 2-of-2 RedPallas distributed key generation succeeded.
- [x] Separate FROST payment proof script and official-encoder network conversion helper compiled/executed.
- [x] PCZT/pool/tool compatibility verified for the pinned private-chain proof.
- [x] A new dedicated threshold watch-only wallet was funded only with mined regtest funds.
- [x] Test participants approved only the exact digest extracted from the locally constructed PCZT.
- [x] Withholding participant two did not complete the session; both participants then completed signing.
- [x] Threshold signatures were applied/verified, broadcast and confirmed by the actual receiver: 100,000 test zatoshis.
- [x] Each signing attempt used fresh session/process state; cancelled sessions were not resumed with reused nonces.
- [x] Shares/config/logs remain owner-only and ignored; source-control exclusion checked.
- [x] Same-host limitation recorded: this is a protocol demonstration, not independent host-compromise protection.

### To do

- [ ] Reproduce the successful proof in a clean environment from pinned source/tool revisions.
- [ ] Audit nonce/session lifecycle and state rollback/recovery beyond the exercised successful/cancelled sessions.
- [ ] Demonstrate public-testnet threshold payment separately if feasible; do not relabel regtest.
- [ ] Design and verify signer-side transaction inspection, policy enforcement, backup and independent deployment before claiming threshold custody for Pactora.

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

1. **Reinspect active state.** Confirm the `Pactora/` checkout, current Git diff and sanitized proof summary. Both payment proofs passed; do not rerun them merely because historical snapshots say unfinished. The regtest validator remains running and private test state is retained.
2. **Finish fulfillment design/tests before live checkout.** Implement separate payment, fulfillment and private-delivery state plus F1–F12 for one narrow product/provider. A paid invoice is not proof of usable service.
3. **Resolve Bitrefill prerequisites in parallel.** Obtain dedicated access/funding, verified product schemas, an enforceable pre-debit ceiling or reserved quote, and lost-response reconciliation. Keep secrets outside chat and live execution closed while any gate is missing.
4. **Complete actual client/browser validation.** Exercise the skill in Claude Code and Codex; finish browser mandate approval/revocation and receipt decryption/recovery. Simulator login and mandate-display inspection are already recorded, but not the full flow.
5. **Verify privacy/deployment claims.** Observe Tor routing/failure/egress behavior and review protected host identities, viewing-key/share handling and backups. Loopback proofs do not cover this.
6. **Run one explicitly approved small real Bitrefill purchase.** Only after authorization, price, reconciliation and fulfillment gates pass. Show actual private delivery or an honest unresolved state; the $5 ceiling is not blanket spending approval.
7. **Package the three proofs honestly.** Ordinary Zcash and FROST regtest receipts are verified. Bitrefill is still blocked. Keep regtest/public testnet, simulator/real goods, payment/fulfillment and application/OS privacy claims distinct.
8. **Preserve reviewable changes.** The latest documentation, evidence summary and some follow-up hardening remain local changes; inspect the current diff before committing. Do not overwrite concurrent work or stage ignored runtime state.

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
| Local proofs | `tools/proofs/README.md`, `start_regtest.py`, `native_payment.py`, `frost_dkg.py`, `frost_payment.py`, `view-network/` |
| Current MVP evidence | `docs/MVP.md`, `docs/evidence/mvp-proofs.json` |
| Tests | `tests/`, plus native tests in sibling `zecpy/tests/` |
| Privacy and wallet documentation | `docs/PRIVACY.md`, `docs/WALLET_PRIVACY.md`, `docs/ZECPY.md` |
| Historical status | `docs/STATUS.md`; older claims may be superseded by current evidence |

The sibling `zecpy/` and `frost/` directories are reference/dependency repositories. `.tools/` contains ignored local tooling. Do not stage them wholesale or accidentally add nested repositories as Git links. Keep upstream attribution and record dependency/tool revisions when sharing proofs.

## 14. Short context block to give another agent

> We are building Pactora: Claude Code/Codex shopping through restricted MCP with privately approved deterministic spending mandates, protected ZecPy signing and private fulfillment. No custom conversational CLI. Constraints run in software, not a Zcash smart contract. Two separate actual regtest payment proofs passed: a 100,000-zatoshi shielded policy payment with safe retry/unauthorized-item refusal, and a 2-of-2 RedPallas FROST-signed shielded payment with confirmed 100,000-zatoshi receipt. DKG passed; one participant did not complete signing, and both did. FROST is a single-host protocol proof, not an independently deployed Pactora policy signer. Current checks: 115 Pactora tests, 37 native unit tests, 6 native integration tests, lint/format/JS/skill checks passed. Simulator browser approval, reload/decryption, issue reporting and revocation passed, as did native regtest browser approval and decryption. Actual Claude/Codex skill sessions remain unverified. Real Bitrefill fulfillment, public-testnet execution and observed Tor routing remain unverified. Bitrefill is blocked by credentials/funding plus pre-debit amount bounds and uncertain-order reconciliation. Checkout folder is Pactora; package/branding remains Pactora. Read docs/MVP.md and docs/evidence/mvp-proofs.json before historical status. The regtest validator remains running; ignored owner-only state is preserved. Next implement narrow product-specific fulfillment assurance, resolve sponsor prerequisites, complete client/browser and privacy verification, then obtain explicit approval for a small real purchase. Payment is not proof of usable service. Never read secrets into model context, reset uncertain reservations, retry an ambiguous debit or claim complete anonymity/refund guarantees.
