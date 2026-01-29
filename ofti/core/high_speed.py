from __future__ import annotations

import math


class HighSpeedInputError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid inputs")


def compute_high_speed_fields(
    mach: float,
    temperature: float,
    gamma: float,
    gas_constant: float,
    static_pressure: float,
) -> tuple[float, float]:
    if mach <= 0 or temperature <= 0 or gamma <= 1 or gas_constant <= 0 or static_pressure <= 0:
        raise HighSpeedInputError()
    speed_of_sound = math.sqrt(gamma * gas_constant * temperature)
    velocity = mach * speed_of_sound
    pressure_ratio = 1 + (gamma - 1) / 2 * mach**2
    total_pressure = static_pressure * (pressure_ratio ** (gamma / (gamma - 1)))
    return velocity, total_pressure
