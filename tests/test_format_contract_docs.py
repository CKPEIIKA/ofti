from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

PERSISTED_EXAMPLES = {
    "bundle-manifest.json": "ofti.case-bundle",
    "run-manifest.json": "ofti.run-manifest",
    "jobs.json": "ofti.jobs",
    "queue-record.json": "ofti.queue-record",
}

EXAMPLE_SCHEMAS = {
    "bundle-manifest.json": "ofti.case-bundle.v1.schema.json",
    "run-manifest.json": "ofti.run-manifest.v1.schema.json",
    "jobs.json": "ofti.jobs.v1.schema.json",
    "queue-record.json": "ofti.queue-record.v1.schema.json",
    "cli-json.json": "ofti.cli-envelope.v1.schema.json",
}


def test_format_examples_use_consistent_persisted_envelope() -> None:
    root = Path("docs/examples/formats")
    for filename, expected_format in PERSISTED_EXAMPLES.items():
        payload = json.loads((root / filename).read_text(encoding="utf-8"))
        assert payload["format"] == expected_format
        assert payload["format_version"] == 1


def test_cli_json_example_uses_cli_envelope() -> None:
    payload = json.loads(Path("docs/examples/formats/cli-json.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["command"] == "bundle"


def test_format_schema_files_are_valid_json() -> None:
    schema_root = Path("docs/schemas")
    names = {path.name for path in schema_root.glob("*.schema.json")}
    assert {
        "ofti.cli-envelope.v1.schema.json",
        "ofti.case-bundle.v1.schema.json",
        "ofti.run-manifest.v1.schema.json",
        "ofti.jobs.v1.schema.json",
        "ofti.queue-record.v1.schema.json",
        "ofti.snapshot.v1.schema.json",
    } <= names
    for path in schema_root.glob("*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"].startswith("https://json-schema.org/")
        assert payload["type"] == "object"
        Draft202012Validator.check_schema(payload)


def test_format_examples_validate_against_published_schemas() -> None:
    example_root = Path("docs/examples/formats")
    schema_root = Path("docs/schemas")
    for example_name, schema_name in EXAMPLE_SCHEMAS.items():
        example = json.loads((example_root / example_name).read_text(encoding="utf-8"))
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(example)
