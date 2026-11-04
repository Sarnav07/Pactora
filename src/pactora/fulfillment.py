"""Private evidence checks for the supported demo adapters, never live goods.

Payment, provider issuance and device accessibility are independent claims.
Unknown provider schemas fail closed. No URLs are fetched or codes redeemed.
"""

import time


def expected_delivery(quote, operation):
    return {
        "product": quote.product.model_dump(),
        "invoice": quote.invoice_id,
        "operation": operation,
        "amount_zat": quote.source_zat,
        "total_cents": quote.total_cents,
        "simulated": quote.simulated,
    }


def assess_delivery(expected, result):
    """Return a precise private state and sanitized reason; preserve raw evidence encrypted."""
    if not isinstance(result, dict):
        return "private_attention", "unsupported_result"
    if result.get("invoice") != expected["invoice"] or result.get("product") != expected["product"]:
        return "private_attention", "deliverable_binding_mismatch"
    if expected["simulated"]:
        if result.get("simulated") is not True:
            return "private_attention", "environment_mismatch"
        if result.get("transaction") != "SIM-TX-" + expected["operation"]:
            return "private_attention", "operation_mismatch"
        if result.get("total_cents") != expected["total_cents"]:
            return "private_attention", "amount_mismatch"
        code = result.get("code")
        if code is None or code == "":
            return "pending", "deliverable_missing"
        if not isinstance(code, str) or not code.startswith("SIM-CODE-") or len(code) > 256:
            return "private_attention", "deliverable_invalid"
        return "simulator_issued", "not_redeemable"
    if result.get("test_only") is not True or result.get("simulated") is not False:
        return "private_attention", "environment_mismatch"
    received = result.get("confirmed_zat")
    if type(received) is not int or received < expected["amount_zat"]:
        return "pending", "payment_unconfirmed"
    return "not_applicable", "test_payment_only_no_goods"


def new_delivery(quote, operation):
    now = int(time.time())
    return {
        "expected": expected_delivery(quote, operation),
        "quote": quote.model_dump(),
        "payment": "reserved",
        "fulfillment": "not_started",
        "private_delivery": "not_stored",
        "refund": "not_requested",
        "attempts": 0,
        "next_poll": now,
        "deadline": now + 900,
    }
