# Protected ZecPy wallet milestone

Pactora keeps ZecPy as its primary wallet adapter. Noir is not part of the default
payment path. This service is testnet/regtest only and is not wired to Bitrefill
settlement. Nothing in this milestone authorizes a mainnet transfer.

## Trust boundary

Run the wallet service as a dedicated OS user or on a separate protected host.
The agent must not have that user's filesystem, process, shell, Docker, debugging
or administrator access. A different Python process under the same unrestricted
user is not a secret boundary. The service holds spending authority for a small,
dedicated wallet; never use the user's primary wallet.

Three independent credentials have different purposes:

* API bearer token: backend access to the internal service; never give it to MCP.
* Ed25519 approval private key: trusted private approval terminal/backend only.
  The wallet stores only its public key. Possession of the API token cannot approve.
* Storage key: AES-GCM encryption of the operation journal; not a spending key.

The private view now signs bounded mandates and can register/revoke them through
an optional backend-to-wallet bridge; see AGENT_SETUP.md. Live commerce execution
remains closed. For exact-payment operator testing, a trusted-terminal approval
helper remains available. It
shows the exact binding and requires a fingerprint confirmation. Run it outside
the agent environment. Merchant, product and invoice semantics are attested by
the trusted backend; the wallet cannot prove delivery or discover a forged
merchant invoice on its own. Do not let the model populate a trusted attestation
without independent backend validation.

## Provisioning and running

Build/install the modified sibling ZecPy repository into the wallet runtime. The
service refuses versions without `sign_proposal` and `rebroadcast_transaction`.
The original `send_proposal` API remains available to existing library users.
Create a dedicated existing testnet wallet using ZecPy's documented provisioning
flow. Create the mnemonic file with owner-only permissions outside this repo and
the agent's home directory. No wallet creation, funding or network transfer is
automatically performed by the service runner.

Create an owner-only JSON configuration outside the agent filesystem:

```json
{
  "wallet_directory": "/var/lib/pactora-wallet/wallet",
  "mnemonic_file": "/etc/pactora-wallet/mnemonic",
  "state_directory": "/var/lib/pactora-wallet/journal",
  "server": "https://testnet.zec.rocks:443",
  "regtest_local": false,
  "encryption_key": "BASE64_OF_RANDOM_32_BYTES",
  "approval_public_key": "BASE64_OF_ED25519_RAW_PUBLIC_KEY",
  "api_token": "RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS",
  "aggregate_cap_zat": 1000000
}
```

The example cap is in testnet zatoshis, not dollars. Generate independent random
keys, retain them in protected storage, and provision the approval private key
separately. Config and mnemonic must be regular files owned by the service user,
with no group/other permissions. The existing wallet directory must also be
owner-only and owned by the service user. Use encrypted disks and protected backups for
the native ZecPy wallet database, which is NOT encrypted by this journal layer.

Run `python -m pactora.wallet_cli --config /etc/pactora-wallet/config.json` in
the installed Pactora environment. The listener binds only 127.0.0.1:8790.
Do not publish it or place the approval key on the wallet host. For separate hosts,
use an authenticated encrypted tunnel; plain remote HTTP is not supported by the
runner. The example systemd unit provides Linux process/filesystem restrictions;
it is not an installed or verified host configuration.

## Backend workflow

All internal requests require `Authorization: Bearer <api_token>`. Browser-origin
requests are refused. Request/response access logs are disabled by the runner.

1. `POST /sync` scans locally through ZecPy. Remote network errors are generic.
2. `POST /prepare` takes `merchant`, `invoice`, `product`, `destination`,
   `network`, integer `amount_zat`, integer `max_debit_zat`, and Unix-seconds
   `expires_at`. It returns an exact approval document including domain, random
   reference, fee and total. Only the trusted backend/private UI sees it.
3. Save that document to an owner-only file on the trusted approval machine.
   Run `python -m pactora.wallet_approval --approval-file <file> --key-file
   <private-key-file> --output <new-signature-file>`. The key file contains the
   base64-encoded raw 32-byte Ed25519 private key. Review all fields and confirm.
4. `POST /operations/<reference>/execute` with `{"signature":"..."}` checks
   the signature against the service's own saved document, expiry, replay state
   and lifetime aggregate cap before signing. It refreshes wallet state through
   protected sync and rechecks expiry after that potentially slow operation.
5. `GET /operations/<reference>` returns generic state only. `broadcast` means
   submission succeeded, not chain confirmation or merchant fulfillment.
6. For state `signed`, `POST /operations/<reference>/recover` may rebroadcast the
   SAME stored transaction, including after restart. It never constructs a payment.
7. `POST /operations/<reference>/revoke` works only before signing. Signed
   transactions cannot be revoked using application expiry or cancellation.

All operations are serialized. Approved transactions reserve their total before
signing. Reservations are never automatically released, including uncertain
outcomes. The aggregate cap is a lifetime cap for this journal, not a rolling
budget; reducing it below existing reservations prevents more spending. Do not
delete or reset the journal to recover capacity.

## Recovery and privacy behavior

Native signing stores the transaction in ZecPy's database without network I/O.
Pactora records the returned transaction ID in its encrypted journal before
broadcast. Broadcast errors retain `signed` for safe rebroadcast. Errors during
signing and restart during `signing` become `quarantined`, with budget retained.
A crash between native storage and journal recording requires private operator
reconciliation; it never triggers automatic re-signing. Unexecuted prepared
proposals are also quarantined on restart because native proposals live in RAM.

The service rejects mainnet, transparent payments, any pool crossing, wrong
networks, fee overruns and changed approvals. It does not auto-shield unsuitable
funds. It exposes no memo-fetch, arbitrary transaction-build, seed-export or
viewing-key API. Payment detection remains ZecPy's local scan.

Remote endpoints require HTTPS and ZecPy's embedded Arti Tor client, which uses
isolated clients without a direct fallback. Loopback is permitted only in explicit
regtest mode. The wallet does NOT use the commerce executor's external SOCKS
proxy; its embedded Arti needs its own outbound connectivity. The existing
executor Docker Compose file does not deploy this wallet service.

Remaining limitations: embedded Tor is an application routing guarantee, not an
OS prohibition of arbitrary direct sockets. Packet capture, Tor failure testing,
actual circuit behavior and a controlled testnet receipt still need verification.
Tor does not defeat all timing correlation; blockchain metadata and funding
patterns can correlate activity. Native wallet storage and Tor state require disk
protection. The service cannot protect secrets against compromise of its own OS
identity or the approval authority. Journaling encrypts details but exposes opaque
operation references and states. Python cannot promise reliable memory erasure.

## Verification record

See STATUS.md for executed checks. Unit tests use fake wallet methods and cannot
prove native transaction validity or network anonymity. The native regtest test
`zecpy/tests/test_devnet_recovery.py` checks local-only signing, watch-only reopen,
rebroadcast and receiver balance when the devnet is running. Mainnet remains
closed regardless of test results.
