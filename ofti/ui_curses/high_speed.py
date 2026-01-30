from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.core.boundary import zero_dir
from ofti.core.entry_io import write_entry
from ofti.core.high_speed import HighSpeedInputError, compute_high_speed_fields
from ofti.foam.config import get_config, key_hint, key_in
from ofti.foam.exceptions import QuitAppError
from ofti.ui_curses.inputs import prompt_input


def high_speed_helper_screen(stdscr: Any, case_path: Path) -> None:
    inputs = _collect_inputs(stdscr)
    if inputs is None:
        return
    mach, temperature, gamma, gas_constant, static_pressure = inputs

    try:
        velocity, total_pressure = compute_high_speed_fields(
            mach,
            temperature,
            gamma,
            gas_constant,
            static_pressure,
        )
    except HighSpeedInputError:
        _show_message(stdscr, "Invalid inputs.")
        return

    if not _confirm_apply(stdscr, velocity, total_pressure):
        return

    zero_path = zero_dir(case_path)
    u_path = zero_path / "U"
    p_path = zero_path / "p"
    if not u_path.is_file() or not p_path.is_file():
        _show_message(stdscr, "Missing 0/U or 0/p file.")
        return

    u_value = f"uniform ({velocity:.6g} 0 0)"
    p_value = f"uniform {total_pressure:.6g}"
    ok_u = write_entry(u_path, "internalField", u_value)
    ok_p = write_entry(p_path, "internalField", p_value)
    if ok_u and ok_p:
        _show_message(stdscr, "Updated internalField for U and p.")
        return
    _show_message(stdscr, "Failed to update one or more fields.")


def _collect_inputs(stdscr: Any) -> tuple[float, float, float, float, float] | None:
    stdscr.clear()
    stdscr.addstr("High-speed initial conditions helper\n\n")
    stdscr.addstr("Provide static conditions to compute U and p0.\n\n")
    mach = _prompt_float(stdscr, "Mach number", default=2.0)
    if mach is None:
        return None
    temperature = _prompt_float(stdscr, "Static temperature (K)", default=300.0)
    if temperature is None:
        return None
    gamma = _prompt_float(stdscr, "Gamma", default=1.4)
    if gamma is None:
        return None
    gas_constant = _prompt_float(stdscr, "Gas constant R", default=287.0)
    if gas_constant is None:
        return None
    static_pressure = _prompt_float(stdscr, "Static pressure (Pa)", default=101325.0)
    if static_pressure is None:
        return None
    return mach, temperature, gamma, gas_constant, static_pressure


def _confirm_apply(stdscr: Any, velocity: float, total_pressure: float) -> bool:
    summary = (
        f"U = {velocity:.3f} m/s\n"
        f"p0 = {total_pressure:.3f} Pa\n\n"
        "Apply to 0/U (internalField) and 0/p (internalField)? [y/N]: "
    )
    stdscr.clear()
    stdscr.addstr(summary)
    stdscr.refresh()
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))


def _prompt_float(stdscr: Any, label: str, *, default: float) -> float | None:
    raw = prompt_input(stdscr, f"{label} [{default}]: ")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _show_message(stdscr, f"Invalid number for {label}.")
        return None


def _show_message(stdscr: Any, message: str) -> None:
    stdscr.clear()
    stdscr.addstr(message + "\n")
    back_hint = key_hint("back", "h")
    stdscr.addstr(f"Press {back_hint} to return.\n")
    stdscr.refresh()
    key = stdscr.getch()
    if key_in(key, get_config().keys.get("quit", [])):
        raise QuitAppError()
