import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def env(name, default=None):
    """New Pactora settings take precedence; retain legacy config compatibility."""
    legacy = name.replace("PACTORA_", "VEILCART_", 1)
    value = os.environ.get(name, os.environ.get(legacy, default))
    if value is None:
        raise KeyError(name)
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    master_key: str = field(repr=False)
    gateway_key: str = field(repr=False)
    password_hash: str = field(repr=False)
    origin: str = "http://127.0.0.1:8787"
    provider: str = "simulator"
    live_cap_cents: int = 500
    session_ttl: int = 900
    tor_proxy: str = "socks5h://127.0.0.1:9050"
    bitrefill_token: str = field(default="", repr=False)
    near_token: str = field(default="", repr=False)
    checkout_mode: str = "guest"
    wallet_service_url: str = ""
    wallet_api_token_file: str = field(default="", repr=False)
    wallet_network: str = "test"
    test_merchant_url: str = ""
    test_merchant_token_file: str = field(default="", repr=False)
    test_fee_ceiling_zat: int = 50000
    wallet_id: str = "test-wallet"
    mandate_signing_key_file: str = field(default="", repr=False)
    email: str = field(default="", repr=False)

    def __post_init__(self):
        u = urlsplit(self.origin)
        if u.scheme not in ("http", "https") or not u.hostname or u.path not in ("", "/"):
            raise ValueError("invalid private origin")
        if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("remote private view requires HTTPS")
        if len(self.gateway_key) < 32:
            raise ValueError("gateway key must be at least 32 characters")
        if not 1 <= self.live_cap_cents <= 500:
            raise ValueError("demo cap must be between 1 and 500 cents")
        if self.provider not in ("simulator", "bitrefill", "test_merchant"):
            raise ValueError("unknown provider")
        if self.wallet_network not in ("test", "regtest") or self.test_fee_ceiling_zat <= 0:
            raise ValueError("invalid test wallet configuration")
        if self.checkout_mode not in ("guest", "account"):
            raise ValueError("unknown checkout mode")

    @property
    def secure_cookie(self):
        return self.origin.startswith("https://")

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(env("PACTORA_DATA")),
            master_key=env("PACTORA_MASTER_KEY"),
            gateway_key=env("PACTORA_GATEWAY_KEY"),
            password_hash=env("PACTORA_PASSWORD_HASH"),
            origin=env("PACTORA_ORIGIN", "http://127.0.0.1:8787"),
            provider=env("PACTORA_PROVIDER", "simulator"),
            live_cap_cents=int(env("PACTORA_CAP_CENTS", "500")),
            tor_proxy=env("PACTORA_TOR_PROXY", "socks5h://127.0.0.1:9050"),
            bitrefill_token=env("BITREFILL_TOKEN", ""),
            near_token=env("NEAR_TOKEN", ""),
            checkout_mode=env("PACTORA_CHECKOUT_MODE", "guest"),
            wallet_service_url=env("PACTORA_WALLET_URL", ""),
            wallet_api_token_file=env("PACTORA_WALLET_TOKEN_FILE", ""),
            wallet_network=env("PACTORA_WALLET_NETWORK", "test"),
            test_merchant_url=env("PACTORA_TEST_MERCHANT_URL", ""),
            test_merchant_token_file=env("PACTORA_TEST_MERCHANT_TOKEN_FILE", ""),
            test_fee_ceiling_zat=int(env("PACTORA_TEST_FEE_CEILING_ZAT", "50000")),
            wallet_id=env("PACTORA_WALLET_ID", "test-wallet"),
            mandate_signing_key_file=env("PACTORA_MANDATE_KEY_FILE", ""),
            email=env("PACTORA_CHECKOUT_EMAIL", ""),
        )
