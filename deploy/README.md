# Protected-host deployment template

These files have not been image-built or deployed in this session. They are a
deployment starting point, not evidence of production isolation.

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
