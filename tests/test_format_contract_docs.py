from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ofti.core import case_bundle, case_snapshot, run_manifest
from ofti.tools import job_registry
from ofti.tools.cli_tools import run_queue

PERSISTED_EXAMPLES = {
    "bundle-manifest.json": "ofti.case-bundle",
    "run-manifest.json": "ofti.run-manifest",
    "jobs.json": "ofti.jobs",
    "queue-record.json": "ofti.queue-record",
    "snapshot.json": "ofti.snapshot",
}

EXAMPLE_SCHEMAS = {
    "bundle-manifest.json": "ofti.case-bundle.v1.schema.json",
    "run-manifest.json": "ofti.run-manifest.v1.schema.json",
    "jobs.json": "ofti.jobs.v1.schema.json",
    "queue-record.json": "ofti.queue-record.v1.schema.json",
    "snapshot.json": "ofti.snapshot.v1.schema.json",
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


def test_actual_persisted_writers_validate_against_published_schemas(tmp_path: Path) -> None:
    case = _minimal_case(tmp_path / "case")

    _validate_payload(
        case_bundle.manifest_payload(case_bundle.build_bundle_manifest(case)),
        "ofti.case-bundle.v1.schema.json",
    )
    manifest_path = run_manifest.write_case_run_manifest(
        case,
        name="icoFoam",
        command="icoFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=tmp_path / "manifest.json",
    )
    _validate_payload(json.loads(manifest_path.read_text(encoding="utf-8")), "ofti.run-manifest.v1.schema.json")

    job_registry.save_jobs(case, [{"id": "job-1", "kind": "solver", "status": "running"}])
    _validate_payload(
        json.loads((case / ".ofti" / "jobs.json").read_text(encoding="utf-8")),
        "ofti.jobs.v1.schema.json",
    )

    _validate_payload(
        run_queue._queue_record_payload(
            {
                "queue_id": "queue-test",
                "queue_root": str(tmp_path),
                "queue_path": str(tmp_path / ".ofti" / "queues" / "queue-test.json"),
                "created_at": 1.0,
                "updated_at": 2.0,
                "completed_at": 3.0,
                "dry_run": False,
                "backend": "process",
                "count": 1,
                "max_parallel": 1,
                "parallel": 0,
                "ok": True,
                "planned": [{"case": str(case), "command": ["icoFoam"]}],
                "started": [],
                "finished": [],
                "failed_to_start": [],
            },
        ),
        "ofti.queue-record.v1.schema.json",
    )

    snapshot_dir = tmp_path / "snapshot"
    (snapshot_dir / "inputs" / "system").mkdir(parents=True)
    (snapshot_dir / "inputs" / "system" / "controlDict").write_text("application icoFoam;\n")
    _validate_payload(
        case_snapshot.build_snapshot_manifest(
            snapshot_dir,
            case,
            reason="format-test",
            roots=("system",),
        ),
        "ofti.snapshot.v1.schema.json",
    )


def test_persisted_readers_reject_unknown_format_versions(tmp_path: Path) -> None:
    case = _minimal_case(tmp_path / "case")
    bundle_payload = case_bundle.manifest_payload(case_bundle.build_bundle_manifest(case))
    bundle_payload["format_version"] = 999
    with pytest.raises(ValueError, match="unsupported bundle manifest version"):
        case_bundle.manifest_from_payload(bundle_payload)

    manifest_path = run_manifest.write_case_run_manifest(
        case,
        name="icoFoam",
        command="icoFoam",
        background=False,
        detached=False,
        parallel=0,
        mpi=None,
        sync_subdomains=True,
        prepare_parallel=True,
        clean_processors=False,
        output=tmp_path / "manifest.json",
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["format_version"] = 999
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported manifest version"):
        run_manifest.load_run_manifest(manifest_path)


def _validate_payload(payload: dict[str, object], schema_name: str) -> None:
    schema = json.loads((Path("docs/schemas") / schema_name).read_text(encoding="utf-8"))
    persisted_shape = json.loads(json.dumps(payload))
    Draft202012Validator(schema).validate(persisted_shape)


def _minimal_case(case: Path) -> Path:
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text("application icoFoam;\n", encoding="utf-8")
    (case / "system" / "fvSchemes").write_text("ddtSchemes {}\n", encoding="utf-8")
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n", encoding="utf-8")
    (case / "0" / "p").write_text("internalField uniform 0;\n", encoding="utf-8")
    return case
