# Pactora MVP proof harnesses

These are operator test harnesses, not shopping-agent tools. They use private
regtest funds. Never supply a mainnet seed, real wallet or personal account.
Generated shares, mnemonics, TLS keys, viewing keys, transaction plans and logs
stay under ignored owner-only `proof-state/`. Never commit that directory.

The compact, deliberately non-secret execution summary is
[docs/evidence/mvp-proofs.json](../../docs/evidence/mvp-proofs.json).

## Pinned tools and environment

- Modified ZecPy baseline: see patches/README.md; install its patched checkout.
- FROST library reference: `0966bd1529aa062ad3b621af99e277f976b1c0f0`.
- Official `frost-zcash-demo`: `53df99c2bd61f7cb60a0d1f634822a76be3799cf`.
- Official `zcash-devtool`: `0b3436bb8d235c67cd36b800cb45a7b1b489c415`.
- Validator: official Zebra 7.0.0 Linux binary, checked against release SHA256SUMS.
- ZecPy provides the Python native runtime. grpcio/grpcio-tools are needed for its
  audit proxy tests. PyYAML is needed for the bundled skill validator.

### Clean bootstrap

On 4 November 2026, the helper completed in a new temporary directory on macOS
arm64 using the host's existing Rust/uv installations and dependency caches.
All pinned sources and the patch were checked, the FROST tools, developer tool and address helper were
built, patched ZecPy imported, and 115 Pactora tests passed in the new Python
environment. This was not a fresh operating-system installation or a replay of
the private-chain payment proofs. Network access is required for uncached inputs.

From the project root, install Git, Rust 1.96 or newer, `uv`, a C toolchain and
system development dependencies needed by Rust. Then prepare a **new** directory:

```sh
python3 tools/proofs/bootstrap_tools.py --tools-dir .tools/clean-bootstrap
```

The helper checks out all three pinned sources, applies the ZecPy patch, builds the
FROST and devtool executables plus the address helper with `--locked`, and installs
Pactora and patched ZecPy in a dedicated virtual environment. It never starts a
node or touches wallet state. The binaries are in
`.tools/clean-bootstrap/target/release/`; Python is
`.tools/clean-bootstrap/venv/bin/python`. The directory must not already exist;
use a new name after a failure. Pass `--source-only` to validate checkouts and
patching without building. Validator download/start is a separate step below.

For the commands below, use the prepared Python and override paths, for example:

```sh
.tools/clean-bootstrap/venv/bin/python tools/proofs/frost_dkg.py \
  --tools .tools/clean-bootstrap/target/release --state proof-state/frost-dkg-new
```

For `frost_payment.py`, also point `--view-helper` at
`.tools/clean-bootstrap/target/release/pactora-proof-view-network`. For native
fixture setup, point `--devtool` at that directory's `zcash-devtool`. Use a new,
dedicated regtest state and do not reuse failed or uncertain payments.

### Existing environment setup

Use a dedicated Python environment. `uv pip install --python .venv/bin/python -e
/path/to/patched-zecpy grpcio grpcio-tools PyYAML` provisions the optional runtime
and tests. A subsequent `uv sync` can remove these optional tools; reinstall them
before native proof runs. Use `.venv/bin/python -m pytest` if the checkout moved
and old executable shebangs still reference its previous directory.

Clone official sources into ignored `.tools/src/`, check out the pinned commits,
then build the FROST workspace with `cargo build --locked --release -p frost-client
-p zcash-sign -p frostd`, and devtool with `cargo build --locked --release --features
regtest_support`. The proof helper uses official Zcash address encoders:

```sh
cargo build --locked --release --manifest-path tools/proofs/view-network/Cargo.toml
```

## 1. Private chain and normal shielded payment

The full official validator image download failed in this environment. The smaller
verified official binary ran successfully in an already available `postgres:15`
Linux/glibc container with its normal database entrypoint replaced. No existing
PostgreSQL container, volume or account is used. This is a local test convenience,
not a production deployment recommendation. Docker Desktop must be running.

```sh
.venv/bin/python tools/proofs/start_regtest.py --state proof-state/regtest
.venv/bin/python tools/proofs/native_payment.py \
  --state proof-state/native-payment --node-state proof-state/regtest
```

The startup helper refuses to overwrite existing state or replace an existing
container. Both RPC ports bind only to host loopback. Zebra's built-in lightwallet
gRPC endpoint is used, rather than a separate lightwalletd daemon. The payment
harness mines test funds, provisions fresh wallets, changes only its dedicated
container's mining destination and creates a signed mandate. It verifies an actual
shielded receiver receipt, a safe identical retry and an unauthorized-product
refusal. Journal encryption keys are retained in owner-only test state for recovery.

To run a deliberate fresh proof without mining another mature miner wallet, use
`--funding-state proof-state/native-payment` with a NEW `--state` directory. Do not
rerun a failed or uncertain payment automatically; inspect its private journal and
native history first. The first validation attempt exposed a policy ordering issue:
product checks now precede scanning/proposal construction. Its test state remains
preserved separately; only the successful proof is included in the summary.

## 2. Separate FROST shielded payment

```sh
.venv/bin/python tools/proofs/frost_dkg.py \
  --tools .tools/src/frost-zcash-demo/target/release --state proof-state/frost-dkg
.venv/bin/python tools/proofs/frost_payment.py \
  --tools .tools/src/frost-zcash-demo/target/release \
  --dkg proof-state/frost-dkg --state proof-state/frost-payment \
  --funding-state proof-state/native-payment \
  --view-helper tools/proofs/view-network/target/release/pactora-proof-view-network
```

DKG generates two shares, without a retained full FROST spend-authorizing key.
The test TLS CA is trusted only through the child processes' SSL_CERT_FILE; no
system trust store is changed. Public contacts are exchanged explicitly. Native
watch-account metadata uses a group-derived identifier, not a recoverable seed.

The payment harness uses official Zcash encoders to re-encode the FROST viewing
key for private regtest, funds a watch-only wallet and constructs a real PCZT.
It waits with one signing participant, verifies no final signature is produced,
then starts the second. Test participants approve only the digest extracted from
that PCZT; signatures are applied and verified by the official tools/native
extractor, and receiver confirmation is required before recording success.

Both shares run on ONE host. This demonstrates threshold protocol operation,
not protection against compromise of that host. It does NOT integrate an
independent FROST policy signer with Pactora's mandates. Earlier signing attempts
that were cancelled are not reused; each run uses a new native transaction and
fresh coordinator/participant processes. Do not reuse signing nonces.

## Native regression tests

Provision the existing ZecPy devnet fixture without printing test mnemonics:

```sh
.venv/bin/python tools/proofs/setup_devnet_wallet.py \
  --funding-state proof-state/native-payment \
  --devtool .tools/src/zcash-devtool/target/release/zcash-devtool \
  --devnet-home .tools/devnet --activation-heights /path/to/zecpy/devnet/activation-heights.toml
```

Run the ZecPy tests from its source directory, with `ZECPY_DEV` set to the absolute
`.tools/devnet` path, using the Pactora environment's Python. The executed targets
were test_devnet_recovery.py, test_devnet_mandates.py and test_devnet_proposals.py.
They passed after correcting the mandate test's preserved `veilcart-mandate-v1`
wire identifier. Test fixtures wait for sufficient confirmations before spending.

Stop only the owned test container after verification: `docker stop pactora-regtest`.
Preserve state for inspection; `docker start pactora-regtest` resumes it.

## Not demonstrated

Public testnet/mainnet payments, observed Tor routing, deployed signer isolation,
interactive Claude/Codex skill use, ZEC-to-Bitrefill conversion or actual Bitrefill
fulfillment are NOT established by these private-chain proofs.
