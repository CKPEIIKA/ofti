from __future__ import annotations

from ofti.core.versioning import get_dict_path, is_legacy_version, resolve_solver_alias


def test_is_legacy_version() -> None:
    assert is_legacy_version("2.3.x") is True
    assert is_legacy_version("2.1") is True
    assert is_legacy_version("v2312") is False


def test_get_dict_path_turbulence() -> None:
    assert get_dict_path("turbulence", version="2.3.x") == "constant/RASProperties"
    assert get_dict_path("turbulence", version="v2312") == "constant/turbulenceProperties"


def test_resolve_solver_alias() -> None:
    assert resolve_solver_alias("compressible", version="2.3.x") == "rhoCentralFoam"
    assert resolve_solver_alias("compressible", version="v2312") == "rhoPimpleFoam"
