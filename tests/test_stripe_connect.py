from types import SimpleNamespace

from app.payments.stripe_connect import create_checkout_session


def test_destination_charge_adds_ten_percent_without_reducing_award():
    calls = []
    fake = SimpleNamespace(checkout=SimpleNamespace(Session=SimpleNamespace(create=lambda **kw: calls.append(kw) or SimpleNamespace(id="cs_1", url="https://checkout.test"))))
    result = create_checkout_session(
        attestation={"case_id": "case-1", "attestation_hash": "a" * 64, "payment": {
            "award_minor_units": 100_000, "platform_fee_minor_units": 10_000,
            "total_charge_minor_units": 110_000, "currency": "BRL"}},
        connected_account_id="acct_winner", success_url="https://v.test/success",
        cancel_url="https://v.test/cancel", idempotency_key="payment:case-1", stripe_client=fake)
    assert result["session_id"] == "cs_1"
    assert calls[0]["line_items"][0]["price_data"]["unit_amount"] == 110_000
    assert calls[0]["payment_intent_data"]["application_fee_amount"] == 10_000
    assert calls[0]["payment_intent_data"]["transfer_data"]["destination"] == "acct_winner"
