from __future__ import annotations

from pathlib import Path

from ofti.core.solver_checks import resolve_solver_name


class CaseSourceError(ValueError):
    @classmethod
    def case_not_found(cls, path: Path) -> CaseSourceError:
        return cls(f"case directory not found: {path}")

    @classmethod
    def read_failed(cls, path: Path, exc: OSError) -> CaseSourceError:
        return cls(f"failed to read {path}: {exc}")

    @classmethod
    def log_source_not_found(cls, path: Path) -> CaseSourceError:
        return cls(f"log source not found: {path}")

    @classmethod
    def no_logs_found(cls, path: Path) -> CaseSourceError:
        return cls(f"no log.* files found in {path}")


def require_case_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise CaseSourceError.case_not_found(resolved)
    return resolved


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise CaseSourceError.read_failed(path, exc) from exc


def solver_log_path(case_path: Path) -> Path | None:
    solver, _error = resolve_solver_name(case_path)
    if not solver:
        return None
    path = case_path / f"log.{solver}"
    if path.is_file():
        return path
    return None


def resolve_log_source(source: Path) -> Path:
    target = source.expanduser().resolve()
    if target.is_file():
        return target
    if not target.is_dir():
        raise CaseSourceError.log_source_not_found(target)
    solver_log = solver_log_path(target)
    if solver_log is not None:
        return solver_log
    logs = sorted(
        target.glob("log.*"),
        key=lambda path: (
            path.stat().st_mtime_ns,
            path.stat().st_ctime_ns,
        ),
    )
    if not logs:
        raise CaseSourceError.no_logs_found(target)
    return logs[-1]
