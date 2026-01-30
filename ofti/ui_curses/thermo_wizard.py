from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ofti.core.entries import Entry, autoformat_value
from ofti.core.entry_io import read_entry, write_entry
from ofti.core.versioning import get_dict_path
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.foam.openfoam import OpenFOAMError
from ofti.ui_curses.entry_editor import EntryEditor
from ofti.ui_curses.menus import Menu

THERMO_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "thermoType": [
        (
            "hePsiThermo (perfectGas + sutherland)",
            """{
    type            hePsiThermo;
    mixture         pureMixture;
    transport       sutherland;
    thermo          hConst;
    equationOfState perfectGas;
    specie          specie;
    energy          sensibleEnthalpy;
}""",
        ),
        (
            "heRhoThermo (rhoConst + const)",
            """{
    type            heRhoThermo;
    mixture         pureMixture;
    transport       const;
    thermo          hConst;
    equationOfState rhoConst;
    specie          specie;
    energy          sensibleEnthalpy;
}""",
        ),
    ],
    "mixture": [
        (
            "pureMixture",
            """{
    specie
    {
        nMoles      1;
        molWeight   28.96;
    }
}""",
        ),
        (
            "multiComponentMixture",
            """{
    species (O2 N2);
    defaultSpecie O2;
    specie
    {
        nMoles      1;
        molWeight   32;
    }
}""",
        ),
    ],
    "transport": [
        (
            "sutherland",
            """{
    As          1.4792e-06;
    Ts          116;
}""",
        ),
        (
            "const",
            """{
    mu          1.8e-05;
    Pr          0.7;
}""",
        ),
    ],
    "equationOfState": [
        (
            "perfectGas",
            """{
    R           287;
}""",
        ),
        (
            "Boussinesq",
            """{
    rho0        1000;
    T0          300;
    beta        3e-03;
}""",
        ),
        (
            "rhoConst",
            """{
    rho         1000;
}""",
        ),
    ],
}


def thermophysical_wizard_screen(stdscr: Any, case_path: Path) -> None:  # noqa: C901
    dict_rel = get_dict_path("thermophysical")
    dict_path = case_path / dict_rel
    if not dict_path.is_file():
        _show_message(stdscr, f"Missing {dict_rel}.")
        return

    keys = ["thermoType", "mixture", "transport", "equationOfState"]
    values = {key: _read_value(dict_path, key) for key in keys}

    while True:
        labels = [_label_for(key, values[key]) for key in keys] + ["Back"]
        menu = Menu(
            stdscr,
            "Thermophysical properties wizard",
            labels,
            status_line="Edit core thermophysical slots",
        )
        choice = menu.navigate()
        if choice in (-1, len(labels) - 1):
            return

        key = keys[choice]
        templates = THERMO_TEMPLATES.get(key, [])
        action_labels = [
            "Edit manually",
            *[f"Use template: {name}" for name, _ in templates],
            "Back",
        ]

        def hint_for(idx: int, template_list=templates) -> str | None:
            if idx == 0:
                return "Edit the raw dictionary block"
            template_index = idx - 1
            if 0 <= template_index < len(template_list):
                return _template_hint(template_list[template_index][1])
            return None

        action_menu = Menu(
            stdscr,
            f"{key} options",
            action_labels,
            hint_provider=hint_for,
        )
        action_choice = action_menu.navigate()
        if action_choice in (-1, len(action_labels) - 1):
            continue
        if action_choice == 0:
            entry = Entry(key=key, value=values[key])
            editor = EntryEditor(
                stdscr,
                entry,
                on_save=lambda value, k=key: _write_value(dict_path, k, value),
                validator=_thermo_validator,
                type_label="dict",
            )
            editor.edit()
            values[key] = entry.value
            continue
        template_index = action_choice - 1
        if 0 <= template_index < len(templates):
            template_value = templates[template_index][1]
            if _write_value(dict_path, key, template_value):
                values[key] = template_value
                _show_message(stdscr, f"Applied {key} template.")
            else:
                _show_message(stdscr, f"Failed to apply {key} template.")


def _label_for(key: str, value: str) -> str:
    summary = "missing" if not value.strip() else value.splitlines()[0][:40]
    return f"{key}: {summary}"


def _read_value(path: Path, key: str) -> str:
    try:
        return read_entry(path, key)
    except OpenFOAMError:
        return ""


def _write_value(path: Path, key: str, value: str) -> bool:
    cleaned = autoformat_value(value)
    if not cleaned.strip():
        return False
    return write_entry(path, key, cleaned)


def _thermo_validator(value: str) -> str | None:
    if not value.strip():
        return "Value cannot be empty."
    lowered = value.lower()
    if "janaf" in lowered or "coeffs" in lowered:
        numbers = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", value)
        if len(numbers) < 7:
            return "Janaf/coeffs section looks too short (expected >= 7 numbers)."
    return None


def _template_hint(value: str) -> str:
    for line in value.splitlines():
        stripped = line.strip().strip("{}")
        if stripped:
            return stripped[:60]
    return "Template"


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press {back_hint} to return.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
