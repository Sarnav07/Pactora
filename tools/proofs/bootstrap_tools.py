"""Build pinned proof dependencies in a new, isolated directory.

This prepares source and binaries only. It never opens wallets, starts Docker,
mines blocks or accesses existing proof state. Requires git, Rust, uv and network.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOS = {
    "zecpy": ("https://github.com/mikemoulder/zecpy.git", "f0b79c9289ff59f0b93007d4e2040ce88bf9bbfa"),
    "frost-zcash-demo": (
        "https://github.com/ZcashFoundation/frost-zcash-demo.git",
        "53df99c2bd61f7cb60a0d1f634822a76be3799cf",
    ),
    "zcash-devtool": (
        "https://github.com/zcash/zcash-devtool.git",
        "0b3436bb8d235c67cd36b800cb45a7b1b489c415",
    ),
}


def run(*args, cwd=None, env=None):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tools-dir", type=Path, required=True, help="New directory; never overwrites an existing one"
    )
    parser.add_argument("--source-only", action="store_true", help="Clone and check patches without building")
    args = parser.parse_args()
    root = args.tools_dir.resolve()
    try:
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
    except FileExistsError:
        raise SystemExit("Tools directory already exists; choose a new directory.") from None
    src = root / "src"
    src.mkdir()
    for name, (url, revision) in REPOS.items():
        checkout = src / name
        run("git", "clone", "--no-checkout", url, checkout)
        run("git", "checkout", "--detach", revision, cwd=checkout)
    zecpy = src / "zecpy"
    patch = ROOT / "patches/zecpy.patch"
    run("git", "apply", "--check", patch, cwd=zecpy)
    run("git", "apply", patch, cwd=zecpy)
    if args.source_only:
        print("Pinned sources checked out and ZecPy patch applied; binaries have not been built.")
        return
    env = {**os.environ, "CARGO_TARGET_DIR": str(root / "target")}
    run(
        "cargo",
        "build",
        "--locked",
        "--release",
        "-p",
        "frost-client",
        "-p",
        "zcash-sign",
        "-p",
        "frostd",
        cwd=src / "frost-zcash-demo",
        env=env,
    )
    run(
        "cargo",
        "build",
        "--locked",
        "--release",
        "--features",
        "regtest_support",
        cwd=src / "zcash-devtool",
        env=env,
    )
    run(
        "cargo",
        "build",
        "--locked",
        "--release",
        "--manifest-path",
        ROOT / "tools/proofs/view-network/Cargo.toml",
        env=env,
    )
    venv = root / "venv"
    run("uv", "venv", venv)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run(
        "uv",
        "pip",
        "install",
        "--python",
        python,
        "-e",
        f"{ROOT}[dev]",
        "-e",
        zecpy,
        "grpcio",
        "grpcio-tools",
        "PyYAML",
    )
    run(
        python,
        "-c",
        "import zecpy; from zecpy import Wallet; assert hasattr(Wallet, 'sign_proposal'); assert hasattr(Wallet, 'rebroadcast_transaction')",
    )
    print(f"Prepared binaries: {root / 'target/release'}")
    print(f"Prepared Python: {python}")


if __name__ == "__main__":
    main()
