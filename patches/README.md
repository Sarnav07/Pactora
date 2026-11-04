# ZecPy dependency patch

Upstream: https://github.com/mikemoulder/zecpy
Baseline: `f0b79c9289ff59f0b93007d4e2040ce88bf9bbfa`.

`zecpy.patch` includes the invoice decimal-format correction, local signing and
stored-transaction rebroadcast extensions, and native recovery/mandate tests.
The optional Pactora import in the native mandate test requires this application
installed in the test environment. The chain-dependent tests require a private regtest node. Six targeted native
recovery, proposal and mandate integration tests passed in this workspace, along
with 37 native unit tests. These results do not establish public-testnet behavior
or Tor routing; see [the proof evidence](../docs/evidence/mvp-proofs.json).

Apply to a clean upstream checkout at the baseline:

```sh
git checkout f0b79c9289ff59f0b93007d4e2040ce88bf9bbfa
git apply --check /absolute/path/to/patches/zecpy.patch
git apply /absolute/path/to/patches/zecpy.patch
```

Install that patched checkout into the protected wallet runtime. The simulator
does not require it. Upstream licenses are included alongside the patch; this
patch does not represent the full upstream repository as Pactora-authored code.
