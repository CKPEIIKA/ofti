import shutil
import subprocess

import pytest


@pytest.mark.skipif(
    shutil.which("foamDictionary") is None,
    reason="foamDictionary not available; integration test is optional",
)
def test_foamdictionary_help_runs() -> None:
    # Simple smoke test to ensure foamDictionary is callable when present.
    result = subprocess.run(
        ["foamDictionary", "-help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

