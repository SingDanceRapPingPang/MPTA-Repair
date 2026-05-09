#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "models" / "curated_model_with_properties" / "TarTarRepairedDB" / "3repaireddb_sla_fanout"
MUTATED = (
    ROOT
    / "models"
    / "multi_counterexample_examples"
    / "TarTarRepairedDB"
    / "3repaireddb_sla_fanout"
    / "bound_multi_0001"
)

WORKFLOWS = [
    ("read", "front-end read query", "read responses"),
    ("write", "transaction commit", "commit acknowledgements"),
    ("audit", "audit replication", "audit acknowledgements"),
    ("backup", "incremental backup checkpoint", "backup checkpoint acknowledgements"),
]


def add_label(parent: ET.Element, kind: str, text: str, x: int, y: int) -> None:
    label = ET.SubElement(parent, "label", {"kind": kind, "x": str(x), "y": str(y)})
    label.text = text


def add_loc(template: ET.Element, loc_id: str, name: str, x: int, y: int, invariant: str | None = None, urgent: bool = False) -> None:
    loc = ET.SubElement(template, "location", {"id": loc_id, "x": str(x), "y": str(y)})
    name_el = ET.SubElement(loc, "name", {"x": str(x + 20), "y": str(y - 25)})
    name_el.text = name
    if urgent:
        ET.SubElement(loc, "urgent")
    if invariant:
        add_label(loc, "invariant", invariant, x + 20, y + 20)


def add_transition(
    template: ET.Element,
    source: str,
    target: str,
    labels: list[tuple[str, str]],
    x: int,
    y: int,
) -> None:
    trans = ET.SubElement(template, "transition")
    ET.SubElement(trans, "source", {"ref": source})
    ET.SubElement(trans, "target", {"ref": target})
    for offset, (kind, text) in enumerate(labels):
        add_label(trans, kind, text, x, y + 20 * offset)


def build_model(mutated: bool) -> ET.ElementTree:
    nta = ET.Element("nta")
    decl_lines = ["// Fan-out database SLA example generated for iterative TarTar baseline stress."]
    for key, _, _ in WORKFLOWS:
        decl_lines.extend(
            [
                f"clock e_{key};",
                f"clock s_{key};",
                f"clock p_{key};",
                f"chan req_{key};",
                f"chan done_{key};",
            ]
        )
    decl = ET.SubElement(nta, "declaration")
    decl.text = "\n".join(decl_lines)

    for idx, (key, meaning, _) in enumerate(WORKFLOWS):
        y = -1400 + idx * 260
        client = ET.SubElement(nta, "template")
        name = ET.SubElement(client, "name")
        name.text = f"{key}Client"
        add_loc(client, f"{key}_c0", "idle", -1780, y)
        add_loc(client, f"{key}_c1", "dispatch", -1660, y, urgent=True)
        add_loc(client, f"{key}_c2", "pending", -1540, y)
        add_loc(client, f"{key}_c3", "ackReceived", -1420, y, urgent=True)
        ET.SubElement(client, "init", {"ref": f"{key}_c0"})
        add_transition(client, f"{key}_c0", f"{key}_c1", [("assignment", f"e_{key}:=0")], -1740, y + 20)
        add_transition(client, f"{key}_c1", f"{key}_c2", [("synchronisation", f"req_{key}!")], -1625, y + 20)
        add_transition(client, f"{key}_c2", f"{key}_c3", [("synchronisation", f"done_{key}?")], -1505, y + 20)
        add_transition(client, f"{key}_c3", f"{key}_c0", [], -1420, y + 80)

        worker = ET.SubElement(nta, "template")
        name = ET.SubElement(worker, "name")
        name.text = f"{key}Worker"
        stage_bound = 4 if mutated else 2
        process_bound = 3 if mutated else 1
        add_loc(worker, f"{key}_w0", "awaiting", -8600, y)
        add_loc(worker, f"{key}_w1", "validated", -8460, y, f"s_{key}<={stage_bound}")
        add_loc(worker, f"{key}_w2", "processing", -8320, y, f"p_{key}<={process_bound}")
        ET.SubElement(worker, "init", {"ref": f"{key}_w0"})
        add_transition(
            worker,
            f"{key}_w0",
            f"{key}_w1",
            [("synchronisation", f"req_{key}?"), ("assignment", f"s_{key}:=0")],
            -8565,
            y + 20,
        )
        add_transition(
            worker,
            f"{key}_w1",
            f"{key}_w2",
            [("guard", f"s_{key}>=1"), ("assignment", f"p_{key}:=0")],
            -8425,
            y + 20,
        )
        add_transition(
            worker,
            f"{key}_w2",
            f"{key}_w0",
            [("guard", f"p_{key}>=1"), ("synchronisation", f"done_{key}!")],
            -8285,
            y + 20,
        )

    system = ET.SubElement(nta, "system")
    instances = []
    for key, _, _ in WORKFLOWS:
        instances.extend([f"{key}Client", f"{key}Worker"])
    system.text = "system " + ", ".join(instances) + ";"
    ET.indent(nta, space="    ")
    return ET.ElementTree(nta)


def write_queries(path: Path) -> None:
    lines: list[str] = []
    for index, (key, meaning, ack_label) in enumerate(WORKFLOWS, start=1):
        lines.extend(
            [
                f"// property {2 * index - 1}",
                f"// reason: The {meaning} workflow must finish within its 3-unit service-level objective.",
                f"A[] not {key}Client.ackReceived or (e_{key} <= 3)",
                "",
                f"// property {2 * index}",
                f"// reason: The {ack_label} must not be emitted before the 2-unit validation/commit durability window.",
                f"A[] not {key}Client.ackReceived or (e_{key} >= 2)",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    CURATED.mkdir(parents=True, exist_ok=True)
    MUTATED.mkdir(parents=True, exist_ok=True)
    build_model(mutated=False).write(CURATED / "model.xml", encoding="utf-8", xml_declaration=True)
    write_queries(CURATED / "3repaireddb_sla_fanout_ref.q")
    build_model(mutated=True).write(MUTATED / "model.xml", encoding="utf-8", xml_declaration=True)
    write_queries(MUTATED / "properties.q")
    mutation = {
        "id": "bound_multi_0001",
        "mutation_type": "fanout_multi_bound_mod",
        "description": "Four database workflows have relaxed validation and processing upper bounds. Each has a fast SLA and a minimum validation/durability window.",
        "source_model": str(CURATED / "model.xml"),
        "source_properties": str(CURATED / "3repaireddb_sla_fanout_ref.q"),
        "faults": [],
    }
    for key, meaning, _ in WORKFLOWS:
        mutation["faults"].extend(
            [
                {
                    "template": f"{key}Worker",
                    "owner_kind": "location",
                    "owner": "validated",
                    "label_kind": "invariant",
                    "original": f"s_{key}<=2",
                    "mutated": f"s_{key}<=4",
                    "semantic_role": f"{meaning} validation budget",
                },
                {
                    "template": f"{key}Worker",
                    "owner_kind": "location",
                    "owner": "processing",
                    "label_kind": "invariant",
                    "original": f"p_{key}<=1",
                    "mutated": f"p_{key}<=3",
                    "semantic_role": f"{meaning} processing budget",
                },
            ]
        )
    (MUTATED / "mutation.json").write_text(json.dumps(mutation, indent=2, ensure_ascii=False), encoding="utf-8")
    print(CURATED)
    print(MUTATED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
