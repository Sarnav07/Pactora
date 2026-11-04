from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Search(StrictModel):
    query: str = Field(min_length=2, max_length=160)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    budget_cents: int = Field(gt=0, le=100_000)


class Product(StrictModel):
    id: str
    name: str
    price_cents: int = Field(gt=0)
    country: str
    package: str
    restrictions: str


class Quote(StrictModel):
    invoice_id: str
    product: Product
    total_cents: int = Field(gt=0)
    deposit_address: str
    source_zat: int = Field(gt=0)
    fee_zat: int = Field(ge=0)
    max_debit_zat: int = Field(gt=0)
    expires_at: int
    destination_asset: str
    destination_address: str
    checkout_mode: str
    simulated: bool


class PrivateSelection(StrictModel):
    option: int = Field(ge=0, le=19)


class Approve(StrictModel):
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    device_public_key: str = Field(min_length=100, max_length=8192)
