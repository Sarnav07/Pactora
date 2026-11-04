# Reference review: Omamori

Reviewed local commit `6ba6be7065603a6632ff385b965698351791bf99`. Static review only;
no payment, deployment, or live attack reproduction. No Omamori source was copied.

| Source | Observed behavior | Pactora response |
|---|---|---|
| apps/agent/index.ts:347 | Logs and returns giftCard object | No raw fulfillment in MCP |
| apps/mcp/tools.ts:376 | Recognized code withheld; URL/txid returned | Generic model-visible status |
| apps/mcp/session.ts | Untrusted text accumulates in conversation state | Typed structured search only |
| apps/firewall/jev.ts:253 | Task/payment/source context sent to semantic service | No secondary model in execution path |
| apps/firewall/store.ts:337 | Receipt JSON and plaintext SKU/amount retained | Encrypt operational detail |
| apps/firewall/store.ts:918 | Fulfillment key derived from signing key | Independent storage/device keys |
| apps/mcp/ssrf-guard.ts | DNS check/connect gap documented | No model-supplied external URL |
| apps/site/src/lib/storage.ts | Bearer session in localStorage | HttpOnly private-view session |

Useful patterns retained conceptually: independent merchant verification, intent
binding, fail-closed decisions, human authorization, and replay protection. Base
smart accounts, Jev, Intercepta and World ID do not transfer Zcash privacy guarantees.
