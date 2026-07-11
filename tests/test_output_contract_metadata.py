from ofti.core.output_contract import JSON_SCHEMA_VERSION, stamp_payload


def test_stamp_payload_owns_reserved_metadata() -> None:
    payload = {
        "schema_version": 999,
        "command": "plugin supplied",
        "value": 42,
    }

    assert stamp_payload(payload, "knife inspect") == {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": "knife inspect",
        "value": 42,
    }


def test_stamp_payload_leaves_non_mapping_payload_unchanged() -> None:
    payload = ["value"]

    assert stamp_payload(payload, "knife inspect") is payload
