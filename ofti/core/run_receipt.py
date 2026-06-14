"""Compatibility aliases for the run manifest module.

New code should import :mod:`ofti.core.run_manifest`.
"""

from __future__ import annotations

from . import run_manifest as _run_manifest

SCHEMA_VERSION = _run_manifest.SCHEMA_VERSION
MANIFEST_KIND = _run_manifest.MANIFEST_KIND
LEGACY_RECEIPT_KIND = _run_manifest.LEGACY_RECEIPT_KIND
SUPPORTED_MANIFEST_KINDS = _run_manifest.SUPPORTED_MANIFEST_KINDS
DEFAULT_INPUT_ROOTS = _run_manifest.DEFAULT_INPUT_ROOTS

build_run_receipt = _run_manifest.build_run_manifest
write_run_receipt = _run_manifest.write_run_manifest
write_case_run_receipt = _run_manifest.write_case_run_manifest
load_run_receipt = _run_manifest.load_run_manifest
verify_run_receipt = _run_manifest.verify_run_manifest
restore_run_receipt = _run_manifest.restore_run_manifest
resolve_receipt_output = _run_manifest.resolve_manifest_output
collect_case_inputs = _run_manifest.collect_case_inputs

__all__ = [
    "DEFAULT_INPUT_ROOTS",
    "LEGACY_RECEIPT_KIND",
    "MANIFEST_KIND",
    "SCHEMA_VERSION",
    "SUPPORTED_MANIFEST_KINDS",
    "build_run_receipt",
    "collect_case_inputs",
    "load_run_receipt",
    "resolve_receipt_output",
    "restore_run_receipt",
    "verify_run_receipt",
    "write_case_run_receipt",
    "write_run_receipt",
]
