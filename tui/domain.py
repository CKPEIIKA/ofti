from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DictionaryFile:
    """
    Lightweight wrapper for a dictionary file in an OpenFOAM case.

    Holds both the absolute path and the case root so that callers can
    easily obtain a relative path for display.
    """

    root: Path
    path: Path

    @property
    def rel(self) -> Path:
        return self.path.relative_to(self.root)


@dataclass(frozen=True)
class EntryRef:
    """
    Reference to a specific dictionary entry (file + key).
    """

    file: DictionaryFile
    key: str


@dataclass(frozen=True)
class Case:
    """
    Thin representation of a case root.
    """

    root: Path

