from zip_state import delivery_location


def test_prefers_explicit_state_in_full_address():
    assert delivery_location("123 Main St, Miami, FL 33101") == ("FL", "33101")


def test_resolves_state_from_zip_only():
    assert delivery_location("33101") == ("FL", "33101")
    assert delivery_location("10001") == ("NY", "10001")
    assert delivery_location("90210-1234") == ("CA", "90210")


def test_handles_special_district_and_no_zip():
    assert delivery_location("Washington DC 20001") == ("DC", "20001")
    assert delivery_location("Unknown destination") == ("", "")
