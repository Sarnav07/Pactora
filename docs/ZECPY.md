# ZecPy patch and adapter

Reference baseline: `f0b79c9289ff59f0b93007d4e2040ce88bf9bbfa`.

The dependency patch in [patches/](../patches/README.md) includes a small change in `python/zecpy/invoices.py`:
only strip trailing zeros when a decimal point exists. Previously 10, 20, and 100
ZEC formatted as 1, 2, and 1. Regression cases were added to its invoice tests.

Pactora's separate adapter calls `propose` with both privacy overrides disabled,
checks `paying_out + fee`, and sends the exact approved proposal. It does not rely
on `pay(max_zat=...)` as an all-in budget guard. Mainnet is refused.

The optional native package is not required for the simulator. To experiment on
the protected testnet wallet host, install the patched reference package there
(`uv pip install /path/to/patched-zecpy` from a suitable environment) and fund a dedicated test
wallet outside the model. Building the native dependency can take several minutes.
Do not give its mnemonic to MCP or commit it.

Six targeted ZecPy chain-dependent tests passed against a private regtest node,
and a shielded test payment was confirmed. No public funds were moved. ZecPy's recorded Tor/testnet run is reference-authored evidence, not a new
Pactora verification. Whole-system anonymity is not established by a request-count
metric. Keep opt-in memo fetching disabled in the normal path.



The patch also adds `sign_proposal` and `rebroadcast_transaction` native/Python
methods, plus recovery and Pactora mandate regtest tests. See patches/README.md
for the pinned baseline and application steps. Native compilation and private regtest transfers passed; observed Tor routing and public-network transfers remain unverified.
