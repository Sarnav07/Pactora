# Live settlement is closed

This release never signs a mainnet payment or calls Bitrefill buy/pay endpoints.
`Bitrefill.quote` and `execute` fail closed in code, not just by a UI toggle.
The simulator is explicitly identified in every model response and private view.

## Evidence required before implementing live execution

1. Sponsor-confirmed API access for the chosen account and guest flows. Confirm
   current schemas, authentication, product availability, and test-product charges.
2. A known ZEC-funded route to an exact supported-asset invoice payment. Validate
   the route's returned deposit receiver with ZecPy; do not enable transparent
   outputs merely to get a swap to work.
3. A bounded exact-output quote including Zcash fees, conversion fees, destination
   network costs, expiry margin and refund address. Reject total costs over $5.
4. Independently checked invoice recipient/asset/network/amount. The model's URL or
   claims never establish the payment destination.
5. Restart-safe deposit, swap-status and merchant-status reconciliation. Deposit
   broadcast uncertainty may not produce a second deposit.
6. A real authorized transfer and delivered product with private evidence. Record
   what the conversion provider and public destination chain can see.

The public NEAR token inventory is discovery evidence only. CrossPay's documented
app flow is not proof of a headless ZecPy-compatible API or shielded deposit.

## Current interfaces

- `Simulator.search/quote/execute/reconcile`: deterministic-contract testing only.
- `Bitrefill.search`: strict REST catalog normalizer over protected HTTP; not tested
  against authenticated live data. No SDK schema guessing on unknown responses.
- `RouteProbe.inspect`: read-only NEAR asset inventory; reports unresolved gates.
- `ZecPyWallet.prepare`: exact local proposal with shielded defaults and all-in cap.
- `ZecPyWallet.execute`: requires a previously approved hash and a durable once-only
  claim callback. It cannot be called by the model gateway.

Do not treat both-track eligibility or a ZEC-funded Bitrefill demo as established
until the above evidence exists. A failed feasibility gate is a real result.

## Reference documentation

- [Bitrefill partner guide](https://docs.bitrefill.com/docs/mcp-partner-integration-guide)
- [Bitrefill product APIs](https://docs.bitrefill.com/docs/api-overview)
- [NEAR 1Click requests](https://docs.near-intents.org/integration/distribution-channels/1click-api/quickstart/making-a-request)
- [CrossPay](https://support.zodl.com/article/24-using-crosspay-to-spend-zec)
- [Event resources](https://fancy-spectacles-44b.notion.site/Zcash-Developer-Resources-3ff3e52aeb1580a583c8e82b95a6f94e)
