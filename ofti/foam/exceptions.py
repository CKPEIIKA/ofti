from __future__ import annotations


class QuitAppError(RuntimeError):
    """Raised to request a full application exit from anywhere."""


class OpenFOAMError(RuntimeError):
    @classmethod
    def missing_openfoam_tools(cls) -> OpenFOAMError:
        return cls(
            "OpenFOAM tools not found on PATH. "
            "Please source your OpenFOAM bashrc before running ofti.",
        )

    @classmethod
    def foamlib_keywords_failed(cls, exc: Exception) -> OpenFOAMError:
        return cls(f"foamlib failed to parse keywords: {exc}")

    @classmethod
    def foamlib_entry_failed(cls, exc: Exception) -> OpenFOAMError:
        return cls(f"foamlib failed to parse entry: {exc}")
