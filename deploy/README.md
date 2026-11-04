# Protected-host deployment template

The native wallet image was built on Docker Desktop (Linux arm64), and its
patched ZecPy methods were imported in a container with networking disabled.
The simulator Compose stack has not been deployed as an isolation test. These
files are a deployment starting point, not evidence of production isolation.

The executor is attached only to an `internal` Docker network. The Tor container
alone also has outbound access. The SOCKS listener is never published to the host.
`IsolateSOCKSAuth` honors the HTTP client's per-request random credentials.

Provision an executor configuration as described in the main README. In the
container copy set `PACTORA_DATA` to `/state`, `PACTORA_TOR_PROXY` to
`socks5h://tor:9050`, and keep `PACTORA_PROVIDER` set to `simulator` initially.
Store this copy at `deploy/config.json` (git-ignored), never in the image.

For bind-backed Compose secrets, uid/gid/mode may not be remapped by the engine.
Provision the file readable only by the executor identity (UID 10001 on Linux), or
use your platform's secret manager. Do not make it world-readable to fix startup.

The port is published only on loopback. Remote access requires an authenticated
HTTPS ingress or a separately secured tunnel, and a matching `PACTORA_ORIGIN`.
Do not expose plain HTTP remotely. Verify real Docker firewall behavior, IPv6,
DNS and Tor outage tests on the target host before enabling any live adapter.

An agent with host shell access or Docker administrator access can bypass this
boundary. The protected executor must live outside those permissions. The private
browser must also be outside the agent's computer-use session.

## Separate native wallet image

The simulator executor image intentionally does not contain wallet keys or ZecPy.
Build the separate wallet image from the repository root:

```sh
docker build -f deploy/Dockerfile.wallet -t pactora-wallet:local .
docker run --rm --entrypoint /app/.venv/bin/python pactora-wallet:local -c 'from zecpy import Wallet; assert hasattr(Wallet, "sign_proposal"); assert hasattr(Wallet, "rebroadcast_transaction")'
```

The build checks out the pinned upstream revision, applies the checked-in patch,
and compiles the native extension. It needs network access and can take a long
time. The `.dockerignore` excludes local wallet state and credentials from build
context. No wallet is created or funded by the build.

`pactora-wallet` binds only to `127.0.0.1` inside its own network namespace.
For a local integration on a Linux protected host, use host networking deliberately
or put the caller in the same network namespace; simply publishing a Docker port
will not make the loopback-only listener reachable. Docker Desktop host networking
has different behavior and is not covered by this template. Do not expose the
wallet to a shopping agent or publish it to a public interface.

Provide a dedicated, separately provisioned wallet directory and config as
owner-only bind mounts. The image runs as UID/GID 10001; the config, mnemonic and
wallet directory must satisfy `pactora-wallet`'s owner and mode checks for that
identity. Pass the in-container config path with `--config` when starting it.
Provisioning, secure transport, backup and operating-system isolation remain
operator responsibilities; building this image does not establish them.
