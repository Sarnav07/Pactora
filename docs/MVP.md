# Pactora MVP: verified proofs and next gate

Two of the three agreed proofs are now executed. They are separate demonstrations,
not a single private ZEC-funded Bitrefill checkout.

| Proof | Executed result | Boundary |
|---|---|---|
| Zcash policy payment | Actual shielded regtest receipt; replay produced no second transaction; unauthorized product refused | Full-key wallet service remains trusted |
| FROST payment | 2-of-2 RedPallas DKG and signatures; one participant did not complete; actual shielded regtest receipt | Separate protocol proof on one host; not a deployed policy signer |
| Bitrefill purchase | Not executed | No account credentials/funds provisioned; maximum-debit and uncertain-checkout reconciliation unverified |

Both successful payment receivers confirmed 100,000 private-chain test zatoshis.
No public-chain funds or account balances were spent. No goods were purchased.
Evidence summary: [mvp-proofs.json](evidence/mvp-proofs.json). Reproduction:
[proof harnesses](../tools/proofs/README.md).

## Controlled merchant application path

`PACTORA_PROVIDER=test_merchant` enables a distinctly labeled test-only adapter.
Set `PACTORA_WALLET_NETWORK` to `regtest` or `test`, matching the wallet service.
Provide protected `PACTORA_TEST_MERCHANT_TOKEN_FILE`, `PACTORA_TEST_MERCHANT_URL`,
`PACTORA_MANDATE_KEY_FILE`, `PACTORA_WALLET_URL`, `PACTORA_WALLET_TOKEN_FILE` and
matching wallet identity. `PACTORA_TEST_FEE_CEILING_ZAT` defaults to 50,000.

The operator runs `python -m pactora.merchant_cli --config <owner-only-file>`.
The file uses the wallet launcher's `wallet_directory`, `server`, `regtest_local`,
plus `state_directory`, `api_token`, optional `amount_zat` (default 100000) and
`confirmations` (default 1). Open the merchant wallet WITHOUT a mnemonic: the
merchant refuses spending-capable or mainnet wallets. Provision wallets outside
model sessions; never put wallet secrets in MCP configuration.

The adapter fetches a trusted catalog, creates an invoice-specific shielded
address, binds the exact retry envelope before signing, and asks the protected
wallet service to enforce the mandate. Completion requires the watch-only
merchant's local chain scan to confirm receipt. A wallet broadcast alone is not
fulfillment. Use private receipt recovery to reconcile pending test payments;
this reuses the same wallet operation and never constructs a replacement payment.

Direct HTTP is permitted only for explicit regtest loopback. Remote test merchant
HTTPS uses the configured Tor transport and a host allowlist supplied by operator
configuration, never by the model. The loopback proofs do not verify Tor routing.
Test catalog dollar figures are accounting units, not a real ZEC/USD exchange rate.
The wallet trusts the merchant adapter for product/invoice/recipient authenticity;
it does not independently fetch the invoice. A compromised trusted adapter remains
a risk. The separate FROST proof does not change that trust boundary.
The integrated HTTP application path is covered by test doubles; the executed
native proof directly exercised the real wallet policy and merchant receiver.

## Bitrefill: what the sponsor needs to establish

The official MCP guide says account-balance purchases debit immediately, even for
test products. PAYMENT_UNCERTAIN must be reconciled, not retried:
https://docs.bitrefill.com/docs/mcp-partner-integration-guide

Before implementing/enabling a real debit, obtain:

1. A dedicated account/API or OAuth access and a small funded balance, provisioned
   through protected local files outside chat.
2. An atomic maximum-debit parameter or guaranteed fixed/reserved checkout quote.
   Reading a price and checking the charged amount AFTER debit does not enforce
   the user's spending cap.
3. A supported client-operation reference or a reliable way to identify and query
   the existing invoice if the purchase response is lost.
4. A supported product/denomination whose complete charges fit the $5 ceiling,
   plus explicit private authorization of the actual spend.

`python -m pactora.cli probe-bitrefill --config <file> --output <report>` performs
only protected read-only MCP contract inspection. The owner-only config contains
`tor_proxy` and `token_file`; the latter points to an owner-only bearer-token file.
The probe refuses buy-products and emits no raw balances, credentials or invoice
contents. Its report always leaves safe balance checkout unverified until an
actual supported spending contract is implemented. It has not been run with live
credentials. Unknown/SSE response shapes fail closed instead of guessing a schema.

If balance checkout cannot enforce a pre-debit ceiling, keep it closed and agree
on a separate exact-invoice supported payment adapter. Do not imply that simply
adding an API key enables safe autonomous purchasing.

## Current verification

94 Pactora Python tests; 37 native ZecPy unit tests; 6 targeted native integration
tests; actual ordinary/FROST regtest receiver confirmations; skill validation;
Ruff and JavaScript syntax checks. Browser login and mandate display were inspected
in native Chrome, including a screenshot of the updated disclosure copy. Browser
approval interaction hit computer-use framing/window errors; complete browser
approval/decryption and interactive hosted-agent sessions remain unverified.

Mainnet remains refused by the ZecPy service. Bitrefill live execution remains
closed. No privacy or on-chain-policy guarantee follows from these test results.
