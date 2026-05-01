#!/usr/bin/env python3
"""Build a compact model/property dataset from models/model_with_ref.

The output intentionally contains only timed automata and their selected
property files. Reference papers, markdown notes, images, and raw sources stay
in models/model_with_ref as archival material.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.verify_automata import DEFAULT_VERIFYTA, verify_property


OUTPUT_ROOT = Path("models/curated_model_with_properties")


@dataclass(frozen=True)
class SelectedProperty:
    formula: str
    reason: str


@dataclass(frozen=True)
class CuratedModel:
    family: str
    version_id: str
    source_model: Path
    properties: tuple[SelectedProperty, ...]
    fix_zero_equality_invariants: bool = False


CURATED_MODELS: tuple[CuratedModel, ...] = (
    CuratedModel(
        family="BangOlufsen",
        version_id="5bando",
        source_model=Path("models/model_with_ref/BangOlufsen/versions/5bando/model.xml"),
        properties=(
            SelectedProperty(
                "A[] Sender_A.stop or Sender_A.end_jam or (A_c <= 28116)",
                "Global sender timing bound for completing or leaving the jam/stop handling window.",
            ),
            SelectedProperty(
                "A[] not Sender_A.jam or (A_c <= 25000)",
                "Collision handling must keep the jamming signal within the protocol bound.",
            ),
            SelectedProperty(
                "A[] not Sender_B.newPn or (B_c <= 40)",
                "The bus output update phase must respect the physical output-delay bound.",
            ),
        ),
    ),
    CuratedModel(
        family="csma_cd",
        version_id="2csma",
        source_model=Path("models/model_with_ref/csma_cd/versions/2csma/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not P1.sender_transm or not P2.sender_transm or (P1.x < 52)",
                "Two senders cannot remain in simultaneous transmission beyond the collision window.",
            ),
            SelectedProperty(
                "A[] not P0.bus_collision1 or (P0.x < 26)",
                "The medium must detect and propagate collision information within the bus-delay bound.",
            ),
            SelectedProperty(
                "A[] not P1.sender_transm or (p2t == 0) or (P1.x < 52)",
                "Transmission overlap with P2 is bounded by the collision detection window.",
            ),
        ),
    ),
    CuratedModel(
        family="Elevator",
        version_id="3elevator",
        source_model=Path("models/model_with_ref/Elevator/versions/3elevator/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not Door.idle or (x>=2 and x<=5)",
                "The door idle interval stays inside the modeled open/close timing window.",
            ),
            SelectedProperty(
                "A[] not Elevator.First_Floor or (x>=2)",
                "The elevator cannot report the first-floor state before the minimum travel delay.",
            ),
        ),
    ),
    CuratedModel(
        family="engine",
        version_id="engine",
        source_model=Path("models/model_with_ref/engine/versions/engine/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 0 or (SysTimer <= 1000)",
                "Normal gear changes must complete within the one-second industrial requirement.",
            ),
            SelectedProperty(
                "A[] not GearControl.GearChanged or ErrStat != 0 or (SysTimer <= 1500)",
                "All recoverable gear-change scenarios must satisfy the absolute response bound.",
            ),
            SelectedProperty(
                "A[] not GearControl.GearChanged or ErrStat != 0 or UseCase != 1 or (SysTimer <= 1055)",
                "Zero-torque failure recovery must complete within the derived fault-tolerant bound.",
            ),
        ),
    ),
    CuratedModel(
        family="FDDI",
        version_id="8fddi",
        source_model=Path("models/model_with_ref/FDDI/versions/8fddi/model.xml"),
        properties=(
            SelectedProperty(
                "A[] (ST1.x <= 140)",
                "Station 1 must receive token access within the bounded ring-access time.",
            ),
            SelectedProperty(
                "A[] (ST1.station_z_idle or ST1.station_y_idle) or (ST2.station_z_idle or ST2.station_y_idle)",
                "The token ring must not allow both stations to transmit at the same time.",
            ),
            SelectedProperty(
                "A[] not (ST1.station_z_idle or ST1.station_y_idle) imply (ST1.x <= 120)",
                "A station's continuous token possession is limited by the target rotation time.",
            ),
        ),
    ),
    CuratedModel(
        family="fischer",
        version_id="fischer_2_32_64",
        source_model=Path("models/model_with_ref/fischer/versions/fischer_2_32_64/model.xml"),
        properties=(
            SelectedProperty(
                "A[] P(1).cs imply P(1).x >= 64",
                "A process may enter the critical section only after the required minimum delay.",
            ),
            SelectedProperty(
                "A[] P(1).req imply P(1).x <= 32",
                "The request phase respects the maximum write-delay bound.",
            ),
        ),
    ),
    CuratedModel(
        family="lynch",
        version_id="lynch_2_16",
        source_model=Path("models/model_with_ref/lynch/versions/lynch_2_16/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not P(1).L2 or (P(1).c <= T)",
                "The write/pause phase of the timing-based mutual exclusion protocol is bounded.",
            ),
            SelectedProperty(
                "A[] not P(1).L8 or (P(1).c <= T)",
                "The exit region must finish within the protocol delay bound.",
            ),
            SelectedProperty(
                "A[] not P(1).L5 or (P(1).c <= T)",
                "The late trying-region phase remains inside the timing parameter used for mutual exclusion.",
            ),
        ),
    ),
    CuratedModel(
        family="mutex",
        version_id="mutex",
        source_model=Path("models/model_with_ref/mutex/versions/mutex/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not Ctrl.wait_for_s2 or (Ctrl_z <= 1000)",
                "The controller's waiting phase must respect the PLC polling-cycle upper bound.",
            ),
            SelectedProperty(
                "A[] not Ctrl.g1 or (Ctrl_z <= 1000)",
                "The grant-monitoring phase must keep observing the granted station within a cycle.",
            ),
            SelectedProperty(
                "A[] not S1.I_am_safe or (S1_z <= 1000)",
                "Station S1's local polling cycle remains within the configured PLC cycle time.",
            ),
        ),
    ),
    CuratedModel(
        family="Peacemaker",
        version_id="6pacemaker",
        source_model=Path("models/model_with_ref/Peacemaker/versions/6pacemaker/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not PURI_test.interval or (PURI_test.t >= TURI)",
                "The upper-rate interval prevents ventricular pacing faster than the clinical bound.",
            ),
            SelectedProperty(
                "A[] not PAVI.AVI or (PAVI.t <= TAVI)",
                "The atrioventricular interval must trigger ventricular support within TAVI.",
            ),
            SelectedProperty(
                "A[] not PVRP.VRP or (PVRP.t <= TVRP)",
                "The ventricular refractory period is bounded to filter early/noisy ventricular events.",
            ),
        ),
    ),
    CuratedModel(
        family="Philips_Audio_Protocol",
        version_id="bocdp",
        source_model=Path("models/model_with_ref/Philips Audio Protocol/versions/bocdp/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not Sender_A.transmit or not Sender_B.transmit or (A_c <= 781)",
                "Concurrent transmission is bounded by the half-bit-slot collision window.",
            ),
            SelectedProperty(
                "A[] not Sender_A.hold or (A_c <= 28116)",
                "The radio-silence hold phase must finish within the protocol timeout.",
            ),
            SelectedProperty(
                "A[] not Sender_A.jam or not Sender_B.jam or (A_c <= 25000)",
                "Collision jamming is bounded so the bus is not occupied indefinitely.",
            ),
        ),
    ),
    CuratedModel(
        family="simop",
        version_id="simop",
        source_model=Path("models/model_with_ref/simop/versions/simop/model.xml"),
        fix_zero_equality_invariants=True,
        properties=(
            SelectedProperty(
                "E<> COM.COM4",
                "A complete communication path for command 0 can reach the network reply handling state.",
            ),
            SelectedProperty(
                "E<> RIO.RIO5",
                "The remote I/O can produce the signal output and return the corresponding reply.",
            ),
        ),
    ),
    CuratedModel(
        family="TarTarRepairedDB",
        version_id="1repaireddb2",
        source_model=Path("models/model_with_ref/TarTarRepairedDB/versions/1repaireddb2/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not client.serReceiving or (x <= 4)",
                "The repaired database model preserves the bounded response time for service reception.",
            ),
        ),
    ),
    CuratedModel(
        family="train",
        version_id="trainahv93_2",
        source_model=Path("models/model_with_ref/train/versions/trainahv93_2/model.xml"),
        properties=(
            SelectedProperty(
                "A[] not (controller.controller3 && cnt>0)",
                "The controller may raise the gate only when no train is still counted in the crossing.",
            ),
            SelectedProperty(
                "A[] not (gate.gate1 && (train(1).train2 or train(1).train3))",
                "A train cannot already be inside the crossing while the gate is still closing.",
            ),
            SelectedProperty(
                "A[] not (train(1).train1 && gate.gate0) or (train(1).x <= 2)",
                "If the gate is open, an approaching train remains within the safe approach window.",
            ),
        ),
    ),
)


def clean_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def copy_model(source: Path, target: Path, fix_zero_equality_invariants: bool) -> None:
    text = clean_text(source.read_text(encoding="utf-8"))
    if fix_zero_equality_invariants:
        text = re.sub(r"([A-Za-z_]\w*)\s*==\s*0</label>", r"\1 &lt;= 0</label>", text)
    target.write_text(text, encoding="utf-8", newline="\n")


def write_query_file(target: Path, model: CuratedModel) -> None:
    blocks = []
    for index, prop in enumerate(model.properties, 1):
        blocks.append(
            "\n".join(
                [
                    f"// property {index}",
                    f"// reason: {prop.reason}",
                    prop.formula,
                ]
            )
        )
    target.write_text("\n\n".join(blocks) + "\n", encoding="utf-8", newline="\n")


def build_dataset() -> dict:
    if OUTPUT_ROOT.exists():
        resolved = OUTPUT_ROOT.resolve()
        workspace = Path.cwd().resolve()
        if not str(resolved).lower().startswith(str(workspace).lower()):
            raise RuntimeError(f"Refusing to delete outside workspace: {resolved}")
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)

    summary = {
        "output_root": str(OUTPUT_ROOT),
        "verifyta": str(DEFAULT_VERIFYTA),
        "models": [],
    }
    all_ok = True

    for model in CURATED_MODELS:
        model_dir = OUTPUT_ROOT / model.family / model.version_id
        model_dir.mkdir(parents=True, exist_ok=True)
        target_model = model_dir / "model.xml"
        target_query = model_dir / f"{model.version_id}_ref.q"
        copy_model(model.source_model, target_model, model.fix_zero_equality_invariants)
        write_query_file(target_query, model)

        results = []
        for index, prop in enumerate(model.properties, 1):
            result = verify_property(target_model, prop.formula, timeout=90)
            results.append(
                {
                    "index": index,
                    "formula": prop.formula,
                    "status": result.status,
                    "duration_sec": result.duration_sec,
                }
            )
            all_ok = all_ok and result.status == "satisfied"

        summary["models"].append(
            {
                "family": model.family,
                "version_id": model.version_id,
                "model": str(target_model),
                "properties": str(target_query),
                "property_count": len(model.properties),
                "satisfied_count": sum(1 for item in results if item["status"] == "satisfied"),
                "results": results,
            }
        )

    (OUTPUT_ROOT / "verification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    (OUTPUT_ROOT / "DATASET_INDEX.md").write_text(render_index(summary), encoding="utf-8", newline="\n")
    (OUTPUT_ROOT / "README.md").write_text(render_readme(summary), encoding="utf-8", newline="\n")

    if not all_ok:
        raise SystemExit("Some curated properties were not satisfied. See verification_summary.json.")
    return summary


def render_index(summary: dict) -> str:
    lines = [
        "# MPTA-Repair Curated Dataset",
        "",
        "Only canonical timed-automata models and selected property files are included.",
        "",
        "| Family | Version | Properties | Satisfied |",
        "| --- | --- | ---: | ---: |",
    ]
    for item in summary["models"]:
        lines.append(
            f"| {item['family']} | {item['version_id']} | "
            f"{item['property_count']} | {item['satisfied_count']} |"
        )
    return "\n".join(lines) + "\n"


def render_readme(summary: dict) -> str:
    return (
        "# MPTA-Repair Curated Dataset\n\n"
        "This directory contains the curated benchmark for **MPTA-Repair**: "
        "Multi-Property Timed Automata Repair. It is generated from `models/model_with_ref` by "
        "`scripts/build_curated_dataset.py`.\n\n"
        "Each model has at most three selected properties. Reference documents "
        "are intentionally not copied here; they remain in `models/model_with_ref`.\n\n"
        f"Model versions: {len(summary['models'])}\n"
        f"Total properties: {sum(item['property_count'] for item in summary['models'])}\n"
    )


if __name__ == "__main__":
    build_dataset()
