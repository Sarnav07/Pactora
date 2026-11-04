# MVP demo progress

> Historical branch report. The integration into the local dashboard changed its UI and recovery behavior. See [project context and final demo checklist](PROJECT_CONTEXT_AND_CHECKLIST.md) for current status, and [MVP proof evidence](MVP.md) for the separately verified FROST payment. The branch-specific browser results below were reported before this integration and do not verify the combined code.

This branch adds private payment, fulfillment and receipt-delivery states for the
supported demo adapters, expected-result validation, bounded reconciliation,
device acknowledgement and private issue reporting. Unknown/missing deliverables
never become successful delivery. A review request does not claim a refund.

It also fixes expired mandate display, recovery after a lost wallet-registration
response, early wallet policy-refusal binding, product-country substitution,
cancellation propagation and the native patch's mandate-domain mismatch.

Executed evidence in this workspace:

- Application suite: 104 passed, 1 skipped before the final country/cancellation
  regressions were added. The skipped test needs the adjacent ZecPy checkout.
- Real MCP stdio and Chromium simulator flow passed: private approval, safe retry,
  unauthorized-option refusal, decryption, IndexedDB reload, acknowledgement,
  private issue reporting, revocation, logout and mobile overflow checks.
- Two-participant RedPallas DKG passed. This does not establish a threshold payment.
- Native shielded regtest policy payment confirmed 100,000 zatoshis, identical
  retry made no second transaction, and an unauthorized product was refused.
- Ruff lint/format and JavaScript syntax checks passed.

`tools/verify_demo.py` reproduces the browser/MCP simulator proof with Playwright
installed separately and an installed Chromium browser. `tools/proofs/` includes
the private-chain bootstrap and native-browser integration runners. The latter
has not yet completed verification. Runtime wallets, shares, keys and raw logs
remain ignored under `proof-state/` and `.tools/`; they are not branch artifacts.

Still outstanding: a confirmed FROST payment, native-browser proof, final full
suite after the last changes, hosted Claude/Codex sessions, observed Tor routing,
real Bitrefill credentials/funding/checkout and actual goods fulfillment. Live
Bitrefill and mainnet gates remain closed. No public funds moved.
