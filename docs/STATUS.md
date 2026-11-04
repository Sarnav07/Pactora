# Current verification — 4 November 2026

The application suite passed **115 tests**. Browser/MCP simulator verification and a separate native browser/MCP flow passed, including a confirmed 100,000-zatoshi shielded regtest receipt, safe retry and unauthorized-product refusal. The separate 2-of-2 FROST regtest payment is verified. See [MVP evidence](MVP.md), [end-to-end results](evidence/e2e-verification-2026-11-04.json) and the [project checklist](PROJECT_CONTEXT_AND_CHECKLIST.md). The native wallet image was built and its patched wallet methods imported; the pinned proof tools also built in an isolated directory. Real Bitrefill fulfillment, Tor routing, deployed signer isolation and interactive hosted-agent sessions remain unverified.

The sections below are historical snapshots and may have been superseded.

---

# Three-proof MVP update — 4 November 2026

Executed: ordinary shielded regtest payment through Pactora mandate enforcement,
confirmed watch-only merchant receipt, safe replay, unauthorized product refusal;
separate 2-of-2 RedPallas DKG and threshold-signed shielded regtest payment with
confirmed receipt. Each proof receiver confirmed 100,000 test zatoshis. No public
funds or Bitrefill balance were spent. The FROST proof is not a deployed policy signer.

Implemented: controlled merchant service/adapter, persistent test-payment retry
and receipt reconciliation, protected read-only Bitrefill contract probe, pinned
proof harnesses and proof summary. Product eligibility is now checked before
native wallet sync/proposal construction, following a real native test finding.
Merchant order identity is persisted before native invoice creation to prevent
reference rebinding after a crash. Test helper keys/state are ignored and owner-only.

Verification: **94 Pactora tests**, **37 native unit tests**, **6 targeted native
integration tests** passed. Both real regtest payment proofs passed. Skills pass
the bundled validator now that PyYAML is installed. Browser login/mandate display
were inspected in Chrome; approval/decryption visual QA was interrupted by native
computer-use framing/window failures. Actual hosted-agent skill use is unverified.

Blocked: real Bitrefill purchase has no provisioned credentials/funds, and no verified
atomic maximum-debit/reserved-quote plus uncertain-response reconciliation contract.
Live checkout remains closed. Tor traffic and deployed host/signer isolation are
unverified. Details: MVP.md, evidence/mvp-proofs.json and tools/proofs/README.md.

Older sections below are historical and do not supersede this verification record.

---

# Pactora first-commit verification — 4 November 2026

Renamed the Python distribution/package, preferred commands, MCP identity, skills,
deployment templates and project branding to Pactora. Legacy operator command
aliases and VEILCART_* settings remain compatible; PACTORA_* takes precedence.
Stored-record domains, encryption AAD and browser identifiers remain unchanged.

Verified: **82 Python tests pass**, Ruff lint/format and JavaScript syntax pass;
renamed Pactora MCP stdio + HTTP simulator purchase smoke passes. Both primary
and legacy service command help entry points work. Skill YAML parses successfully.
The bundled native dependency patch applies cleanly to its documented upstream
baseline and includes upstream license texts. No native transfers or funds moved.

Interactive Claude Code/Codex skill sessions, browser visual QA, native regtest
runtime, observed Tor routing and actual Bitrefill settlement remain unverified.
Mainnet and live execution remain disabled. Older sections below are historical
milestone records; the latest naming and compatibility guide is AGENT_SETUP.md.

---

# Skills and bounded mandates update — 4 November 2026

Implemented portable shopping/operator skills, six restricted MCP tools, private
mandate approval/revocation, signed deterministic product/package mandates,
independent wallet policy enforcement, persistent budget/count reservations,
explicit purchase references, cached policy refusals, generic status, encrypted
receipt recovery, and an optional backend-to-wallet registration/revocation bridge.
Administrative service commands are retained; the custom shopping CLI direction
is removed from the current scope.

Verification: **79 Python tests pass**; real MCP stdio + loopback HTTP simulator
smoke passes for one approval / two purchases / retry / cap refusal / private
receipts. Ruff and JavaScript syntax checks pass. Both skill packages and UI YAML
parsed successfully using Ruby YAML. The bundled Python skill validator could not
run because PyYAML is missing; dependency installation failed DNS resolution even
outside the sandbox. No interactive Claude Code/Codex skill session was tested.

Added a native regtest mandate test, not executed: native runtime/node setup is
missing. Tor traffic verification, browser visual QA, live FX/settlement and actual
Bitrefill fulfillment remain unverified. No funds moved. Mainnet/live payment gates
remain closed. See AGENT_SETUP.md for interfaces, setup and trust boundaries.

---

# Wallet milestone update — 4 November 2026

Implemented a separate authenticated wallet API, exact signed approvals, encrypted
operation journal, aggregate reservations, restart quarantine, recovery-only
rebroadcast, protected secret-file loading, explicit terminal approval, and a
Linux service-unit example. ZecPy has compatible local-sign and stored-transaction
rebroadcast methods. Mainnet stays disabled. No funds moved.

Pactora Python verification: **59 tests pass**, including fake-wallet failure
injection and the internal HTTP approval/execution flow. These tests do not
establish native cryptographic validity or actual Tor routing.

Native compile verification: `cargo check` **passed** for the modified ZecPy
Rust extension. This is type/build checking, not a native runtime payment test.
Native regtest execution is unavailable here: zebrad/lightwalletd binaries are
absent. Added `zecpy/tests/test_devnet_recovery.py` for that environment. Native
ZecPy is not installed in the current Python runtime. No packet-capture routing
verification or live testnet payment has been performed.

The existing shopping browser approval is not wired to the new service. Use the
trusted-terminal approval helper for this milestone. Bitrefill conversion remains
closed. See [wallet privacy details](WALLET_PRIVACY.md).

---

# Implementation and verification record

Date: 2026-11-04 IST. User authorized implementation. No funds moved.

## Implemented and checked

- Private-selection executor, optional privately enabled chat selection, typed MCP
  gateway, authenticated approval, quote binding, atomic aggregate budget cap.
- Device-encrypted receipts; temporary catalog clearing; encrypted uncertain-state
  recovery; no automatic re-payment after ambiguity.
- Testnet-only ZecPy wrapper and the adjacent invoice-formatting regression fix.
- HTTPS destination allowlist, remote-DNS SOCKS proxy, fresh SOCKS-auth isolation,
  and no direct fallback. Tor must honor IsolateSOCKSAuth.
- 31 pytest tests passed. Ruff checks and formatting checks passed. JavaScript
  module syntax passed Node's parser. Node WebCrypto decrypted a Python-produced
  envelope using a non-exportable RSA private key.
- Real stdio MCP handshake and tool calls passed against the running localhost
  simulator, including private HTTP approval, the background worker, encrypted
  receipt decryption and sanitized model status.

## Not verified / not implemented as live capabilities

- Tor route probe failed with `protected_route_unavailable`, both inside and
  outside the sandbox. It did not bypass the proxy. No swap/invoice was created.
- No authenticated live Bitrefill catalog, guest/account purchase, conversion,
  mainnet transaction, supplier delivery or ZecPy native/chain suite was run.
- Live Bitrefill quote and execution are deliberately refused in code. The route
  evidence required to implement those methods is listed in LIVE_GATES.md.
- Browser automation repeatedly failed; native browser capture also failed or
  returned an unusable frame. Browser visual QA and browser IndexedDB persistence
  remain unverified. API tests and WebCrypto compatibility do not replace that QA.
- Deployment templates were not image-built or deployed. OS/network isolation
  must be tested on the protected host. No claim of whole-system anonymity.
- Cross-device device-key recovery is not implemented. Exported ciphertext still
  requires the original browser key.

The local simulator is a working implementation of the control/privacy workflow,
not completion of the planned live ZEC-to-Bitrefill product. No hackathon
eligibility, security audit, or production-readiness claim is made.
