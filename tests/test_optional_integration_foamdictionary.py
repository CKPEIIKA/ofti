import shutil

import pytest

from ofti.foam.subprocess_utils import run_trusted


@pytest.mark.skipif(
    shutil.which("foamDictionary") is None,
    reason="foamDictionary not available; integration test is optional",
)
def test_foamdictionary_help_runs() -> None:
    # Simple smoke test to ensure foamDictionary is callable when present.
    result = run_trusted(
        ["foamDictionary", "-help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
