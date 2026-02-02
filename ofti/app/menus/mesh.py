from __future__ import annotations

from pathlib import Path
from typing import Any

from ofti.app.menu_utils import has_processor_dirs, menu_choice
from ofti.app.state import AppState, Screen
from ofti.tools.menus import run_tool_by_name
from ofti.tools.mesh_utils import (
    cfmesh_screen,
    renumber_mesh_screen,
    transform_points_screen,
)
from ofti.tools.reconstruct import reconstruct_manager_screen
from ofti.tools.run import run_checkmesh
from ofti.ui_curses.blockmesh_helper import blockmesh_helper_screen
from ofti.ui_curses.help import preprocessing_help
from ofti.ui_curses.snappy_toggle import snappy_staged_screen


def mesh_menu(
    stdscr: Any,
    case_path: Path,
    state: AppState,
    *,
    command_handler: Any | None = None,
    command_suggestions: Any | None = None,
) -> Screen:
    options = [
        "Run blockMesh",
        "blockMesh helper",
        "Mesh quality",
        "snappyHexMesh staged",
        "Decompose",
        "Reconstruct manager",
        "renumberMesh",
        "transformPoints",
        "cfMesh",
        "Back",
    ]
    disabled: set[int] = set()
    disabled_reasons: dict[int, str] = {}
    disabled_helpers: dict[int, str] = {}

    blockmesh_dict = case_path / "system" / "blockMeshDict"
    snappy_dict = case_path / "system" / "snappyHexMeshDict"
    cfmesh_dict = case_path / "system" / "cfMeshDict"
    decompose_dict = case_path / "system" / "decomposeParDict"

    if not blockmesh_dict.is_file():
        disabled.add(0)
        disabled_reasons[0] = (
            "blockMesh requires system/blockMeshDict; "
            "create it via Config Manager."
        )
        disabled_helpers[0] = "config"
    if not blockmesh_dict.is_file():
        disabled.add(1)
        disabled_reasons[1] = "blockMesh helper needs system/blockMeshDict."
        disabled_helpers[1] = "config"
    if not snappy_dict.is_file():
        disabled.add(3)
        disabled_reasons[3] = "snappyHexMesh requires system/snappyHexMeshDict."
        disabled_helpers[3] = "config"
    if not cfmesh_dict.is_file():
        disabled.add(8)
        disabled_reasons[8] = "cfMesh requires system/cfMeshDict."
        disabled_helpers[8] = "config"
    if not decompose_dict.is_file():
        disabled.add(4)
        disabled_reasons[4] = "Decompose requires system/decomposeParDict."
        disabled_helpers[4] = "config"
    if state.no_foam:
        disabled.update(range(len(options) - 1))
        for idx in range(len(options) - 1):
            disabled_reasons.setdefault(
                idx,
                "OpenFOAM environment missing; run :foamenv or use limited editor features.",
            )
    if not has_processor_dirs(case_path):
        disabled.add(5)
        disabled_reasons[5] = "Reconstructions need processorN directories."
        disabled_helpers[5] = "diagnostics"

    while True:
        choice = menu_choice(
            stdscr,
            "Mesh",
            options,
            state,
            "menu:pre",
            command_handler=command_handler,
            command_suggestions=command_suggestions,
            disabled_indices=disabled,
            disabled_reasons=disabled_reasons,
            disabled_helpers=disabled_helpers,
            help_lines=preprocessing_help(),
        )
        if choice in (-1, len(options) - 1):
            return Screen.MAIN_MENU
        if choice == 0:
            run_tool_by_name(stdscr, case_path, "blockMesh")
        elif choice == 1:
            blockmesh_helper_screen(stdscr, case_path)
        elif choice == 2:
            run_checkmesh(stdscr, case_path)
        elif choice == 3:
            run_snappy = snappy_staged_screen(stdscr, case_path)
            if run_snappy:
                run_tool_by_name(stdscr, case_path, "snappyHexMesh")
        elif choice == 4:
            run_tool_by_name(stdscr, case_path, "decomposePar")
        elif choice == 5:
            reconstruct_manager_screen(stdscr, case_path)
        elif choice == 6:
            renumber_mesh_screen(stdscr, case_path)
        elif choice == 7:
            transform_points_screen(stdscr, case_path)
        elif choice == 8:
            cfmesh_screen(stdscr, case_path)
