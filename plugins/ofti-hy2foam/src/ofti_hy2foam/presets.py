from __future__ import annotations

from ofti.plugins import FieldPreset

AIR5 = FieldPreset(
    name="air5",
    fields=("N2", "O2", "NO", "N", "O", "Tt", "Tv", "p", "rho"),
    description="hy2Foam five-species air profile",
    source="ofti-hy2foam",
)

AIR11 = FieldPreset(
    name="air11",
    fields=(
        "N2",
        "O2",
        "NO",
        "N",
        "O",
        "N2+",
        "O2+",
        "NO+",
        "N+",
        "O+",
        "e-",
        "Tt",
        "Tv",
        "p",
        "rho",
    ),
    description="hy2Foam ionized eleven-species air profile",
    source="ofti-hy2foam",
)

TRANSPORT = FieldPreset(
    name="hy2foam-transport",
    fields=("Dmix_N2", "Dmix_O2", "rhoD_N2", "rhoD_O2", "J_N2", "J_O2", "sumJ", "qDiff"),
    description="hy2Foam transport-diffusion fields",
    source="ofti-hy2foam",
)

TWO_TEMPERATURE = FieldPreset(
    name="hy2foam-2T",
    fields=("Tt", "Tv", "Tov", "e", "ev"),
    description="hy2Foam two-temperature/modal-energy fields",
    source="ofti-hy2foam",
)

WALL = FieldPreset(
    name="hy2foam-wall",
    fields=("wallHeatFlux", "qCond", "qDiff", "p"),
    description="hy2Foam wall pressure and heat-flux fields",
    source="ofti-hy2foam",
)
