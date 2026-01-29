from __future__ import annotations

import math

import pytest

from ofti.core.high_speed import compute_high_speed_fields


def test_compute_high_speed_fields() -> None:
    mach = 2.0
    temperature = 300.0
    gamma = 1.4
    gas_constant = 287.0
    static_pressure = 101325.0

    velocity, total_pressure = compute_high_speed_fields(
        mach,
        temperature,
        gamma,
        gas_constant,
        static_pressure,
    )

    speed_of_sound = math.sqrt(gamma * gas_constant * temperature)
    expected_velocity = mach * speed_of_sound
    pressure_ratio = 1 + (gamma - 1) / 2 * mach**2
    expected_p0 = static_pressure * (pressure_ratio ** (gamma / (gamma - 1)))

    assert velocity == pytest.approx(expected_velocity, rel=1e-6)
    assert total_pressure == pytest.approx(expected_p0, rel=1e-6)


def test_compute_high_speed_fields_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        compute_high_speed_fields(0, 300, 1.4, 287.0, 101325.0)
