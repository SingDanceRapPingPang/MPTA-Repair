"""Independent timelock/deadlock and zenoness-oriented checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from src.utils.verify_automata import DEFAULT_VERIFYTA, verify_property


LOWER_GUARD_RE = re.compile(r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*(?P<op>>=|>|==)\s*(?P<bound>\d+)\b")
RESET_RE = re.compile(r"(?<![\w.])(?P<clock>[A-Za-z_]\w*)\s*:=\s*0\b")


@dataclass
class LivenessReport:
    timelock_status: str
    timelock_output_tail: str = ""
    zeno_status: str = "unknown"
    zeno_risk_cycles: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.timelock_status == "satisfied" and self.zeno_status in {"no_structural_risk", "unknown"}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def check_timelock_free(model_path: Path, verifyta: Path = DEFAULT_VERIFYTA, timeout: int = 60) -> tuple[str, str]:
    result = verify_property(model_path, "A[] not deadlock", verifyta_path=verifyta, timeout=timeout)
    return result.status, result.output[-1000:]


def _transition_zero_time_risk(transition: ET.Element) -> bool:
    guard_text = " && ".join(
        label.text or ""
        for label in transition.findall("label")
        if label.get("kind") == "guard"
    )
    lower_bounds = [
        int(match.group("bound"))
        for match in LOWER_GUARD_RE.finditer(guard_text)
        if match.group("op") in {">", ">=", "=="}
    ]
    if not lower_bounds:
        return True
    return min(lower_bounds) <= 0


def _transition_resets_time(transition: ET.Element) -> bool:
    assignments = " ; ".join(
        label.text or ""
        for label in transition.findall("label")
        if label.get("kind") == "assignment"
    )
    return bool(RESET_RE.search(assignments))


def analyze_zenoness_risk(model_path: Path) -> tuple[str, list[list[str]], list[str]]:
    root = ET.parse(model_path).getroot()
    notes: list[str] = []
    risk_cycles: list[list[str]] = []
    for template in root.findall("template"):
        template_name = (template.findtext("name") or "template").strip()
        urgent_locations = {
            location.get("id")
            for location in template.findall("location")
            if location.find("urgent") is not None or location.find("committed") is not None
        }
        graph: dict[str, list[str]] = {}
        labels: dict[str, str] = {}
        for location in template.findall("location"):
            location_id = location.get("id")
            if location_id:
                labels[location_id] = f"{template_name}.{(location.findtext('name') or location_id).strip()}"
        for transition in template.findall("transition"):
            source = transition.find("source")
            target = transition.find("target")
            source_ref = source.get("ref") if source is not None else None
            target_ref = target.get("ref") if target is not None else None
            if not source_ref or not target_ref:
                continue
            risky = source_ref in urgent_locations or _transition_zero_time_risk(transition)
            if risky and not _transition_resets_time(transition):
                graph.setdefault(source_ref, []).append(target_ref)

        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def dfs(node: str) -> None:
            if node in visiting:
                if node in stack:
                    cycle = stack[stack.index(node) :] + [node]
                    risk_cycles.append([labels.get(item, item) for item in cycle])
                return
            if node in visited:
                return
            visiting.add(node)
            stack.append(node)
            for nxt in graph.get(node, []):
                dfs(nxt)
            stack.pop()
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            dfs(node)

    if risk_cycles:
        notes.append("structural zero-time cycle risk detected; use model-checker support for a definitive zeno proof")
        return "structural_risk", risk_cycles[:10], notes
    return "no_structural_risk", [], notes


def run_liveness_checks(model_path: Path, verifyta: Path = DEFAULT_VERIFYTA, timeout: int = 60) -> LivenessReport:
    timelock_status, output_tail = check_timelock_free(model_path, verifyta, timeout)
    zeno_status, cycles, notes = analyze_zenoness_risk(model_path)
    return LivenessReport(
        timelock_status=timelock_status,
        timelock_output_tail=output_tail,
        zeno_status=zeno_status,
        zeno_risk_cycles=cycles,
        notes=notes,
    )
