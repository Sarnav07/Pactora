"""Run official 2-of-2 RedPallas DKG with TLS on loopback.

This proves key generation only. It deliberately does not claim a payment proof.
Private shares/logs stay in the requested owner-only state directory.
"""

import argparse
import datetime
import ipaddress
import json
import os
import socket
import subprocess
import time
import tomllib
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def run(tools, state, port):
    tools, state = Path(tools).resolve(), Path(state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.umask(0o077)
    tls_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pactora local proof root")])
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca = (
        x509.CertificateBuilder()
        .subject_name(issuer)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    cert_file, key_file = state / "tls.pem", state / "tls.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    trust_file = state / "trust.pem"
    trust_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        tls_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    env = {
        **os.environ,
        "SSL_CERT_FILE": str(trust_file),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    processes = []
    logs = []

    def start(name, args):
        log = open(state / (name + ".log"), "wb")
        logs.append(log)
        proc = subprocess.Popen(
            args, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=state, stdin=subprocess.DEVNULL
        )
        processes.append(proc)
        return proc

    def call(name, args):
        proc = start(name, args)
        if proc.wait(timeout=120) != 0:
            raise RuntimeError(name + " failed; inspect private state logs locally")

    try:
        server = start(
            "server",
            [
                str(tools / "frostd"),
                "--ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--tls-cert",
                str(cert_file),
                "--tls-key",
                str(key_file),
            ],
        )
        for _ in range(30):
            if server.poll() is not None:
                raise RuntimeError("FROST server failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.2)
        client = str(tools / "frost-client")
        for participant in ("alice", "bob"):
            call("init-" + participant, [client, "init", "-c", str(state / (participant + ".toml"))])
        configs = {p: tomllib.loads((state / (p + ".toml")).read_text()) for p in ("alice", "bob")}
        # Public contact export/import authenticates the expected peer. No private share
        # or communication secret is passed as an argument or printed by this wrapper.
        for participant, peer in (("alice", "bob"), ("bob", "alice")):
            result = subprocess.run(
                [client, "export", "-c", str(state / (peer + ".toml")), "--name", peer],
                capture_output=True,
                env=env,
                cwd=state,
                check=True,
            )
            contact = next(
                line.strip() for line in result.stderr.decode().splitlines() if line.startswith("zffrost1")
            )
            call(
                "import-" + participant,
                [client, "import", contact, "-c", str(state / (participant + ".toml"))],
            )
        common = [
            "--description",
            "Pactora 2-of-2 test proof",
            "--server-url",
            f"127.0.0.1:{port}",
            "--threshold",
            "2",
            "--ciphersuite",
            "redpallas",
        ]
        alice = start(
            "dkg-alice",
            [
                client,
                "dkg",
                "-c",
                str(state / "alice.toml"),
                *common,
                "-S",
                configs["bob"]["communication_key"]["pubkey"],
            ],
        )
        time.sleep(2)
        bob = start("dkg-bob", [client, "dkg", "-c", str(state / "bob.toml"), *common])
        for proc in (alice, bob):
            if proc.wait(timeout=180) != 0:
                raise RuntimeError("DKG failed; inspect private state logs locally")
        configs = {p: tomllib.loads((state / (p + ".toml")).read_text()) for p in ("alice", "bob")}
        groups = [set(configs[p].get("group", {})) for p in ("alice", "bob")]
        if len(groups[0]) != 1 or groups[0] != groups[1]:
            raise RuntimeError("DKG group mismatch")
        report = {
            "proof": "frost_dkg_only",
            "participants": 2,
            "threshold": 2,
            "ciphersuite": "RedPallas",
            "distributed_key_generation": True,
            "same_group_verified": True,
            "threshold_signature_verified": False,
            "shielded_payment_confirmed": False,
            "deployment": "single-host protocol demonstration; no host-compromise isolation claim",
        }
        (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--port", type=int, default=2744)
    args = parser.parse_args()
    run(args.tools, args.state, args.port)
