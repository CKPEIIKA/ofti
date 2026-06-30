from __future__ import annotations

import curses
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.ui.help import menu_hint
from ofti.ui.menu import Menu
from ofti.ui_curses.inputs import prompt_input


def option_index(options: list[str], selection: str | None) -> int:
    if not selection:
        return 0
    try:
        return options.index(selection)
    except ValueError:
        return 0


def show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    stdscr.addstr("Press any key to continue.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()


def is_case_dir(path: Path) -> bool:
    return (path / "system" / "controlDict").is_file()


@dataclass(frozen=True)
class RunningCaseChoice:
    path: Path
    pids: tuple[int, ...]
    solvers: tuple[str, ...]


@dataclass
class _RunningCaseBucket:
    pids: set[int]
    solvers: set[str]


def discover_running_case_choices(start_path: Path) -> list[RunningCaseChoice]:
    """Return visible live solver case directories for the startup chooser."""
    scope = start_path if start_path.is_dir() else start_path.parent
    try:
        rows = _scan_proc_solver_processes(
            scope,
            None,
            tracked_pids=set(),
            include_tracked=True,
            require_case_target=False,
        )
    except (OSError, ValueError):
        return []

    cases: dict[Path, _RunningCaseBucket] = {}
    for row in rows:
        raw_case = str(row.get("case") or "").strip()
        if not raw_case:
            continue
        try:
            case_path = Path(raw_case).expanduser().resolve()
        except OSError:
            continue
        if not is_case_dir(case_path):
            continue
        bucket = cases.setdefault(case_path, _RunningCaseBucket(set(), set()))
        pid = row.get("pid")
        if isinstance(pid, int) and pid > 0:
            bucket.pids.add(pid)
        solver = str(row.get("solver") or "").strip()
        if solver and solver != "unknown":
            bucket.solvers.add(solver)

    choices: list[RunningCaseChoice] = []
    for case_path, values in cases.items():
        pids = tuple(sorted(values.pids))
        solvers = tuple(sorted(values.solvers))
        choices.append(RunningCaseChoice(case_path, pids, solvers))
    return sorted(choices, key=lambda choice: choice.path.as_posix())


def _scan_proc_solver_processes(*args: Any, **kwargs: Any) -> list[Mapping[str, object]]:
    service = import_module("ofti.tools.process_scan_service")
    return cast("list[Mapping[str, object]]", service.scan_proc_solver_processes(*args, **kwargs))


def select_start_case(stdscr: Any, start_path: Path) -> Path | None:
    current_case = start_path.resolve() if is_case_dir(start_path) else None
    running_cases = discover_running_case_choices(start_path)
    options: list[tuple[str, Path | None, str]] = []
    if current_case is not None:
        options.append((_current_case_label(current_case), current_case, "current"))
    for choice in running_cases:
        if current_case is not None and choice.path == current_case:
            continue
        options.append((_running_case_label(choice), choice.path, "running"))
    options.append(("[Choose from a directory]", None, "browse"))

    extra_lines = [
        "Select a live case, open the current case, or browse to a case directory.",
    ]
    if not running_cases:
        extra_lines.append("No live solver cases detected.")
    choice = _navigate_start_case_menu(
        stdscr,
        [label for label, _path, _kind in options],
        [kind for _label, _path, kind in options],
        extra_lines=extra_lines,
    )
    if choice == -1:
        return None
    label, path, kind = options[choice]
    if kind == "browse":
        return select_case_directory(stdscr, start_path)
    if path is None:
        show_message(stdscr, f"{label} is not a case directory.")
        return None
    return path


def _navigate_start_case_menu(
    stdscr: Any,
    labels: list[str],
    kinds: list[str],
    *,
    extra_lines: list[str],
) -> int:
    """Navigate the startup chooser while keeping the final option selectable."""
    cfg = get_config()
    menu = Menu(
        stdscr,
        "Choose case",
        labels,
        extra_lines=extra_lines,
        hint_provider=lambda idx: _start_case_hint(kinds[idx]),
    )
    while True:
        menu.display()
        key = stdscr.getch()

        if key_in(key, cfg.keys.get("quit", [])):
            raise QuitAppError()
        if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
            menu.current_option = (menu.current_option - 1) % len(labels)
            continue
        if key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
            menu.current_option = (menu.current_option + 1) % len(labels)
            continue
        if key_in(key, cfg.keys.get("top", [])):
            menu.current_option = 0
            continue
        if key_in(key, cfg.keys.get("bottom", [])):
            menu.current_option = len(labels) - 1
            continue
        if key_in(key, cfg.keys.get("back", [])):
            return -1
        if key in (curses.KEY_ENTER, 10, 13) or key_in(key, cfg.keys.get("select", [])):
            return int(menu.current_option)


def _current_case_label(path: Path) -> str:
    return f"[Current case] {path}"


def _running_case_label(choice: RunningCaseChoice) -> str:
    solver_text = ", ".join(choice.solvers) if choice.solvers else "solver"
    if not choice.pids:
        pid_text = "pid=?"
    elif len(choice.pids) == 1:
        pid_text = f"pid={choice.pids[0]}"
    else:
        pid_text = f"pids={len(choice.pids)}"
    return f"{solver_text} {pid_text} | {choice.path}"


def _start_case_hint(kind: str) -> str:
    if kind == "browse":
        return "Open the directory case chooser."
    if kind == "running":
        return "Open this currently running case."
    if kind == "current":
        return "Open the current case directory."
    return "Exit OFTI."


def is_probable_case_dir(path: Path) -> bool:
    if not path.is_dir() or is_case_dir(path):
        return False
    has_system = (path / "system").is_dir()
    has_constant = (path / "constant").is_dir()
    has_zero = False
    try:
        for entry in os.scandir(path):
            if entry.is_dir() and entry.name.startswith("0"):
                has_zero = True
                break
    except OSError:
        return False
    return has_system and (has_constant or has_zero)


def case_flag(path: Path) -> str:
    if is_case_dir(path):
        return "OF case"
    if is_probable_case_dir(path):
        return "probably OF case"
    return ""


def list_dir_entries(path: Path) -> tuple[list[Path], list[Path]]:
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        entries = list(os.scandir(path))
    except OSError:
        return [], []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                dirs.append(Path(entry.path))
            elif entry.is_file():
                files.append(Path(entry.path))
        except OSError:
            continue
    return sorted(dirs), sorted(files)


def select_case_directory(stdscr: Any, start_path: Path) -> Path | None:
    current = start_path if start_path.is_dir() else start_path.parent
    index = 0
    scroll = 0
    query = ""
    cfg = get_config()

    while True:
        dirs, files = list_dir_entries(current)
        entries = _case_chooser_entries(current, dirs, files, query)

        labels = [label for label, _path in entries]
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        header = f"Select case folder: {current}"
        current_flag = case_flag(current)
        if current_flag:
            header += f" [{current_flag}]"
        back_hint = key_hint("back", "h")
        search_hint = "/" if not query else f"/:{query}"
        hint = (
            f"Enter: open/select  e: use this folder  {search_hint}: search  "
            f"n: new case  {back_hint}: back  "
            "[Create new case] to clone from examples"
        )
        try:
            stdscr.addstr(0, 0, header[: max(1, width - 1)])
            stdscr.addstr(1, 0, hint[: max(1, width - 1)])
        except curses.error:
            pass

        scroll = menu_scroll(index, scroll, stdscr, len(labels), header_rows=3)
        visible = max(0, height - 3)
        for row_idx, label_idx in enumerate(range(scroll, min(len(labels), scroll + visible))):
            prefix = ">> " if label_idx == index else "   "
            line = f"{prefix}{labels[label_idx]}"
            try:
                if label_idx == index:
                    stdscr.attron(curses.color_pair(1))
                stdscr.addstr(3 + row_idx, 0, line[: max(1, width - 1)])
                if label_idx == index:
                    stdscr.attroff(curses.color_pair(1))
            except curses.error:
                break

        stdscr.refresh()
        key = stdscr.getch()

        if key_in(key, cfg.keys.get("quit", [])):
            raise QuitAppError()
        if key in (curses.KEY_UP,) or key_in(key, cfg.keys.get("up", [])):
            index = (index - 1) % len(labels)
            continue
        if key in (curses.KEY_DOWN,) or key_in(key, cfg.keys.get("down", [])):
            index = (index + 1) % len(labels)
            continue
        if key_in(key, cfg.keys.get("top", [])):
            index = 0
            continue
        if key_in(key, cfg.keys.get("bottom", [])):
            index = len(labels) - 1
            continue
        if key_in(key, cfg.keys.get("back", [])):
            if current.parent != current:
                current = current.parent
                index = 0
                scroll = 0
                query = ""
            continue
        if key == ord("/") or key_in(key, cfg.keys.get("search", [])):
            value = prompt_input(stdscr, "Search entries (empty clears): ")
            if value is None:
                continue
            query = value.strip().lower()
            index = 0
            scroll = 0
            continue
        if key == ord("e"):
            if is_case_dir(current):
                return current
            show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
            continue
        if key in (ord("n"), ord("N")):
            created = _create_case_from_example(stdscr, current)
            if created is not None:
                return created
            continue
        if key in (curses.KEY_ENTER, 10, 13) or key_in(key, cfg.keys.get("select", [])):
            label, path = entries[index]
            if label == "[Use this folder]":
                if is_case_dir(current):
                    return current
                show_message(stdscr, "Not an OpenFOAM case (missing system/controlDict).")
                continue
            if label == "[Create new case]":
                created = _create_case_from_example(stdscr, current)
                if created is not None:
                    return created
                continue
            if label == ".." and path is not None:
                current = path
                index = 0
                scroll = 0
                query = ""
                continue
            if path is None:
                continue
            if path.is_dir():
                current = path
                index = 0
                scroll = 0
                query = ""
                continue
            show_message(stdscr, f"{path.name} is not a folder.")


def _case_chooser_entries(
    current: Path,
    dirs: list[Path],
    files: list[Path],
    query: str,
) -> list[tuple[str, Path | None]]:
    entries: list[tuple[str, Path | None]] = [
        ("[Use this folder]", None),
        ("[Create new case]", None),
        ("..", current.parent if current.parent != current else None),
    ]
    query_text = query.strip().lower()
    for path in dirs:
        if query_text and query_text not in path.name.lower():
            continue
        suffix = case_flag(path)
        suffix_text = f" [{suffix}]" if suffix else ""
        entries.append((f"{path.name}/{suffix_text}", path))
    for path in files:
        if query_text and query_text not in path.name.lower():
            continue
        entries.append((path.name, path))
    if len(entries) == 3 and query_text:
        entries.append(("[No matches]", None))
    return entries


def _list_example_cases() -> list[Path]:
    local = _list_local_examples()
    tutorials = _list_tutorial_cases()
    configured = _list_configured_examples()
    combined = set(local)
    combined |= set(tutorials)
    combined |= set(configured)
    return sorted(combined, key=lambda path: path.as_posix())


def _list_local_examples() -> list[Path]:
    examples_root = Path("examples")
    if not examples_root.is_dir():
        return []
    return sorted(
        path
        for path in examples_root.iterdir()
        if path.is_dir() and is_case_dir(path)
    )


def _list_tutorial_cases() -> list[Path]:
    wm_dir = os.environ.get("WM_PROJECT_DIR")
    if not wm_dir:
        return []
    tutorials = Path(wm_dir) / "tutorials"
    if not tutorials.is_dir():
        return []
    cases: set[Path] = set()
    for control in tutorials.rglob("system/controlDict"):
        case_path = control.parent.parent
        if case_path.is_dir() and is_case_dir(case_path):
            cases.add(case_path)
    return sorted(cases, key=lambda path: path.as_posix())


def _create_case_from_example(stdscr: Any, current: Path) -> Path | None:
    examples = _list_example_cases()
    if not examples:
        show_message(stdscr, "No example cases found in ./examples.")
        return None
    labels = [path.name for path in examples]
    menu = Menu(
        stdscr,
        "Create new case from example",
        [*labels, "Back"],
        hint_provider=lambda idx: (
            "Create case from selected example."
            if 0 <= idx < len(labels)
            else menu_hint("menu:create_case", "Back")
        ),
    )
    choice = menu.navigate()
    if choice in (-1, len(labels)):
        return None
    template = examples[choice]

    stdscr.clear()
    stdscr.addstr(f"Create from: {template.name}\n")
    stdscr.addstr(f"Destination: {current}\n\n")
    default_name = template.name
    dest_input = prompt_input(
        stdscr,
        f"New case folder name [{default_name}]: ",
    )
    if dest_input is None:
        return None
    dest_input = dest_input.strip()
    if not dest_input:
        dest_input = default_name
    dest = Path(dest_input)
    if not dest.is_absolute():
        dest = current / dest
    if dest.exists():
        show_message(stdscr, f"Destination already exists: {dest}")
        return None
    try:
        shutil.copytree(template, dest, symlinks=True)
    except OSError as exc:
        show_message(stdscr, f"Failed to create case: {exc}")
        return None
    if not is_case_dir(dest):
        show_message(stdscr, f"{dest} is not a valid case.")
        return None
    return dest


def _list_configured_examples() -> list[Path]:
    cfg = get_config()
    cases: set[Path] = set()
    for raw_path in cfg.example_paths:
        root = Path(raw_path).expanduser()
        if not root.exists():
            continue
        if root.is_dir() and is_case_dir(root):
            cases.add(root)
            continue
        cases.update(_collect_cases_from_root(root))
    return sorted(cases, key=lambda path: path.as_posix())


def _collect_cases_from_root(root: Path) -> set[Path]:
    cases: set[Path] = set()
    if not root.exists():
        return cases
    try:
        for control in root.rglob("system/controlDict"):
            case_path = control.parent.parent
            if case_path.is_dir() and is_case_dir(case_path):
                cases.add(case_path)
    except OSError:
        pass
    return cases


def prompt_command(stdscr: Any, suggestions: list[str] | None) -> str:
    height, width = stdscr.getmaxyx()
    buffer: list[str] = []
    cursor = 0
    last_matches: list[str] = []
    match_index = 0
    last_buffer = ""

    def render() -> None:
        try:
            stdscr.move(height - 1, 0)
            stdscr.clrtoeol()
            display = ":" + "".join(buffer)
            stdscr.addstr(height - 1, 0, display[: max(1, width - 1)])
            stdscr.move(height - 1, min(width - 1, 1 + cursor))
            stdscr.refresh()
        except curses.error:
            pass

    render()
    while True:
        key = stdscr.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            return "".join(buffer).strip()
        if key in (27,):  # ESC
            return ""
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                buffer.pop(cursor - 1)
                cursor -= 1
            render()
            continue
        if key == curses.KEY_LEFT:
            if cursor > 0:
                cursor -= 1
            render()
            continue
        if key == curses.KEY_RIGHT:
            if cursor < len(buffer):
                cursor += 1
            render()
            continue
        if key == 9:  # TAB
            pool = suggestions or []
            current = "".join(buffer)
            if current != last_buffer:
                last_matches = [s for s in pool if s.startswith(current)]
                match_index = 0
                last_buffer = current
            if last_matches:
                completion = last_matches[match_index % len(last_matches)]
                buffer = list(completion)
                cursor = len(buffer)
                match_index += 1
                render()
            continue
        if 32 <= key <= 126:
            buffer.insert(cursor, chr(key))
            cursor += 1
            render()


def menu_scroll(
    current: int, scroll: int, stdscr: Any, total: int, header_rows: int,
) -> int:
    height, _ = stdscr.getmaxyx()
    visible = max(0, height - header_rows - 1)
    if visible <= 0:
        return 0
    if current < scroll:
        scroll = current
    elif current >= scroll + visible:
        scroll = current - visible + 1
    max_scroll = max(0, total - visible)
    return min(scroll, max_scroll)


def set_no_foam_mode(state: Any, enabled: bool, reason: str | None = None) -> None:
    state.no_foam = enabled
    state.no_foam_reason = reason
    if enabled:
        os.environ["OFTI_NO_FOAM"] = "1"
    else:
        os.environ.pop("OFTI_NO_FOAM", None)
