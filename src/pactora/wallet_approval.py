"""Trusted operator approval helper, to run outside the agent account/filesystem."""

import argparse
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import b64, canonical, digest, unb64
from .wallet_cli import protected_file


def main():
    parser = argparse.ArgumentParser(description="Privately approve an exact Pactora wallet operation")
    parser.add_argument("--approval-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    approval = json.loads(protected_file(args.approval_file))
    if approval.get("domain") != "veilcart-wallet-approval-v1":
        raise ValueError("wrong approval domain")
    print(json.dumps(approval, indent=2, ensure_ascii=True))
    fingerprint = digest(approval)
    print("Review every field above in this trusted terminal.")
    if (
        input(f"Type approve {fingerprint[:12]} to authorize this exact payment: ")
        != f"approve {fingerprint[:12]}"
    ):
        raise SystemExit("Not approved")
    key = Ed25519PrivateKey.from_private_bytes(unb64(protected_file(args.key_file)))
    signature = b64(key.sign(canonical(approval)))
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump({"signature": signature}, output)
    print("Approval written to the protected output file.")


if __name__ == "__main__":
    main()
