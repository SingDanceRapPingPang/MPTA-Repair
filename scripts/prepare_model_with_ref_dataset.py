#!/usr/bin/env python3
"""Normalize and verify the models/model_with_ref dataset.

The script builds a canonical dataset layout:

models/model_with_ref/<family>/
  versions/<model_id>/
    model.xml
    <model_id>_ref.q
    verification_report.json
  references/
  raw_sources/

It also extracts queries embedded in UPPAAL XML files into the query file and
removes the XML <queries> block from the canonical copy.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


DEFAULT_VERIFYTA = r"D:\tool\programming\uppaal\UPPAAL-5.0.0\bin\verifyta.exe"
MODEL_ROOT = Path("models/model_with_ref")
XML_RESERVED_RENAMES = {
    "exit": "exit_chan",
}

QUERY_START_RE = re.compile(
    r"(?P<formula>(?:A\[\]|E<>|A<>|E\[\]|sup:|inf:|Pr\[|simulate\b|control:|strategy\b).*)"
)
PROCESS_RE = re.compile(r"\bprocess\s+([A-Za-z_]\w*)\s*(?:\((.*?)\))?\s*\{", re.DOTALL)
SYSTEM_RE = re.compile(r"\bsystem\b\s+(.+?)\s*;", re.DOTALL)
STATE_RE = re.compile(r"\bstate\b\s*(.*?)\s*;", re.DOTALL)
COMMIT_RE = re.compile(r"\bcommit\b\s*(.*?)\s*;", re.DOTALL)
URGENT_RE = re.compile(r"\burgent\b\s*(.*?)\s*;", re.DOTALL)
INIT_RE = re.compile(r"\binit\b\s*([A-Za-z_]\w*)\s*;", re.DOTALL)
TRANS_RE = re.compile(
    r"([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)\s*\{(.*?)\}",
    re.DOTALL,
)


@dataclass
class Property:
    formula: str
    comments: list[str] = field(default_factory=list)
    source: str = ""
    replaced_from: str | None = None


@dataclass
class ModelSource:
    family: str
    source_path: Path
    model_id: str
    query_paths: list[Path]


def clean_id(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_").lower()
    return value or "model"


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def normalize_formula(text: str) -> str:
    text = text.strip().rstrip(";")
    text = text.replace("\\\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_properties_from_text(text: str, source: str) -> list[Property]:
    properties: list[Property] = []
    pending_comments: list[str] = []
    current: list[str] = []

    def flush_current() -> None:
        nonlocal current, pending_comments
        if not current:
            return
        formula = normalize_formula("\n".join(current))
        if formula:
            properties.append(Property(formula=formula, comments=pending_comments, source=source))
        current = []
        pending_comments = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_current()
            continue
        if line.startswith("//") or line.startswith("#"):
            flush_current()
            pending_comments.append(line)
            continue
        match = QUERY_START_RE.search(line)
        if match:
            flush_current()
            current.append(match.group("formula"))
            if not line.endswith("\\"):
                flush_current()
            continue
        if current:
            current.append(line)
            if not line.endswith("\\"):
                flush_current()
    flush_current()
    return properties


def extract_xml_queries(xml_path: Path) -> tuple[list[Property], ET.ElementTree]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(xml_path, parser=parser)
    root = tree.getroot()
    properties: list[Property] = []
    queries = root.find("queries")
    if queries is not None:
        for query in list(queries.findall("query")):
            formula = query.findtext("formula") or ""
            comment = query.findtext("comment") or ""
            formula = normalize_formula(html.unescape(formula))
            comments = [f"// {comment.strip()}"] if comment.strip() else []
            if formula:
                properties.append(Property(formula=formula, comments=comments, source=str(xml_path)))
        root.remove(queries)
    return properties, tree


def write_xml(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def split_top_level_names(text: str) -> list[tuple[str, str | None]]:
    items: list[tuple[str, str | None]] = []
    for part in re.split(r",", text):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"([A-Za-z_]\w*)\s*(?:\{(.*?)\})?$", part, re.DOTALL)
        if match:
            invariant = normalize_formula(match.group(2) or "")
            invariant = re.sub(r"\b([A-Za-z_]\w*)\s*==\s*0\b", r"\1 <= 0", invariant)
            items.append((match.group(1), invariant or None))
    return items


def find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unmatched process brace")


def parse_processes(xta: str) -> tuple[str, list[tuple[str, str, str]], str]:
    processes: list[tuple[str, str, str]] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        match = PROCESS_RE.search(xta, pos)
        if not match:
            break
        open_index = xta.find("{", match.start())
        close_index = find_matching_brace(xta, open_index)
        name = match.group(1)
        params = (match.group(2) or "").strip()
        body = xta[open_index + 1 : close_index]
        processes.append((name, params, body))
        spans.append((match.start(), close_index + 1))
        pos = close_index + 1

    global_parts: list[str] = []
    last = 0
    for start, end in spans:
        global_parts.append(xta[last:start])
        last = end
    global_parts.append(xta[last:])
    global_text = "\n".join(global_parts)
    system_match = SYSTEM_RE.search(global_text)
    system_text = normalize_formula(system_match.group(1)) if system_match else ""
    global_text = SYSTEM_RE.sub("", global_text).strip()
    return global_text, processes, system_text


def extract_template_declaration(body: str) -> str:
    cut_points = [
        m.start()
        for pattern in (STATE_RE, INIT_RE, COMMIT_RE, URGENT_RE, re.compile(r"\btrans\b", re.DOTALL))
        for m in [pattern.search(body)]
        if m
    ]
    if not cut_points:
        return ""
    return body[: min(cut_points)].strip()


def parse_edge_labels(body: str) -> list[tuple[str, str]]:
    labels: list[tuple[str, str]] = []
    keyword_map = {
        "select": "select",
        "guard": "guard",
        "sync": "synchronisation",
        "assign": "assignment",
    }
    matches = list(re.finditer(r"\b(select|guard|sync|assign)\b", body))
    for i, match in enumerate(matches):
        key = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = body[start:end].strip().strip(";").strip()
        if value:
            if key == "guard":
                value = re.sub(r"\s*,\s*", " && ", value)
            elif key == "assign":
                value = value.replace(":=", "=")
            labels.append((keyword_map[key], value))
    return labels


def xta_to_xml(xta_path: Path, xml_path: Path) -> None:
    xta = read_text(xta_path)
    for old, new in XML_RESERVED_RENAMES.items():
        xta = re.sub(rf"\b{re.escape(old)}\b", new, xta)
    global_decl, processes, system_text = parse_processes(xta)

    root = ET.Element("nta")
    decl = ET.SubElement(root, "declaration")
    decl.text = global_decl.replace(":=", "=")

    for proc_name, params, body in processes:
        template = ET.SubElement(root, "template")
        ET.SubElement(template, "name").text = proc_name
        if params:
            ET.SubElement(template, "parameter").text = params
        local_decl = extract_template_declaration(body)
        if local_decl:
            ET.SubElement(template, "declaration").text = local_decl.replace(":=", "=")

        state_match = STATE_RE.search(body)
        init_match = INIT_RE.search(body)
        if not state_match or not init_match:
            raise ValueError(f"cannot parse states/init in {xta_path}:{proc_name}")

        committed = set()
        for regex in (COMMIT_RE,):
            match = regex.search(body)
            if match:
                committed.update(name.strip() for name in match.group(1).split(",") if name.strip())
        urgent = set()
        match = URGENT_RE.search(body)
        if match:
            urgent.update(name.strip() for name in match.group(1).split(",") if name.strip())

        location_ids: dict[str, str] = {}
        for index, (state_name, invariant) in enumerate(split_top_level_names(state_match.group(1))):
            loc_id = f"{clean_id(proc_name)}_{index}"
            location_ids[state_name] = loc_id
            location = ET.SubElement(template, "location", id=loc_id)
            ET.SubElement(location, "name").text = state_name
            if invariant:
                label = ET.SubElement(location, "label", kind="invariant")
                label.text = invariant
            if state_name in committed:
                ET.SubElement(location, "committed")
            if state_name in urgent:
                ET.SubElement(location, "urgent")

        init_name = init_match.group(1)
        if init_name not in location_ids:
            raise ValueError(f"unknown init state {init_name} in {xta_path}:{proc_name}")
        ET.SubElement(template, "init", ref=location_ids[init_name])

        for source, target, edge_body in TRANS_RE.findall(body):
            if source not in location_ids or target not in location_ids:
                raise ValueError(f"unknown transition endpoint {source}->{target} in {xta_path}:{proc_name}")
            transition = ET.SubElement(template, "transition")
            ET.SubElement(transition, "source", ref=location_ids[source])
            ET.SubElement(transition, "target", ref=location_ids[target])
            for kind, value in parse_edge_labels(edge_body):
                label = ET.SubElement(transition, "label", kind=kind)
                label.text = value

    if not system_text:
        system_text = ", ".join(name for name, _, _ in processes)
    system = ET.SubElement(root, "system")
    system.text = f"system {system_text};"

    write_xml(ET.ElementTree(root), xml_path)


def format_query_file(properties: Iterable[Property]) -> str:
    blocks: list[str] = []
    for i, prop in enumerate(properties, 1):
        lines = [f"// property {i}"]
        lines.extend(prop.comments)
        if prop.replaced_from:
            lines.append(f"// replaced unsatisfied property: {prop.replaced_from}")
        if prop.source:
            lines.append(f"// source: {prop.source}")
        lines.append(prop.formula)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip() + "\n"


def unique_properties(properties: Iterable[Property]) -> list[Property]:
    seen: set[str] = set()
    result: list[Property] = []
    for prop in properties:
        key = normalize_formula(prop.formula)
        if key and key not in seen:
            seen.add(key)
            prop.formula = key
            result.append(prop)
    return result


def extract_global_names(xml_path: Path) -> set[str]:
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return set()
    declaration = root.findtext("declaration") or ""
    names: set[str] = set()
    decl_re = re.compile(
        r"\b(?:clock|(?:broadcast\s+|urgent\s+)?chan|bool|int(?:\s*\[[^\]]+\])?)\s+([^;]+);",
        re.DOTALL,
    )
    for match in decl_re.finditer(declaration):
        for part in match.group(1).split(","):
            name = part.strip()
            name = re.split(r"\s*=|\[", name, maxsplit=1)[0].strip()
            if re.match(r"^[A-Za-z_]\w*$", name):
                names.add(name)
    return names


def rewrite_global_qualified_formula(formula: str, global_names: set[str]) -> str:
    if not global_names:
        return formula
    pattern = re.compile(r"\b[A-Za-z_]\w*\.(" + "|".join(re.escape(n) for n in sorted(global_names, key=len, reverse=True)) + r")\b")
    return pattern.sub(lambda m: m.group(1), formula)


def discover_models(root: Path) -> list[ModelSource]:
    models: list[ModelSource] = []
    for family_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if family_dir.name in {"references", "raw_sources", "versions"}:
            continue
        family = family_dir.name
        ignored = {"versions", "references", "raw_sources"}
        model_paths = sorted(
            [
                p
                for p in family_dir.rglob("*")
                if p.suffix.lower() in {".xml", ".xta"} and not ignored.intersection(p.relative_to(family_dir).parts)
            ]
        )
        ref_queries = sorted(
            q for q in family_dir.rglob("*_ref.q") if not ignored.intersection(q.relative_to(family_dir).parts)
        )
        for model_path in model_paths:
            rel = model_path.relative_to(family_dir)
            stem = clean_id(model_path.stem)
            if rel.parent != Path("."):
                stem = clean_id("_".join(rel.with_suffix("").parts))
            query_paths = []
            companion = model_path.with_suffix(".q")
            if companion.exists():
                query_paths.append(companion)
            query_paths.extend(q for q in ref_queries if q not in query_paths)
            local_ref = list(model_path.parent.glob("*_ref.q"))
            query_paths.extend(q for q in local_ref if q not in query_paths)
            models.append(ModelSource(family=family, source_path=model_path, model_id=stem, query_paths=query_paths))
    return models


def verify_property(verifyta: Path, model_path: Path, formula: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="uppaal_query_") as tmp:
        q_path = Path(tmp) / "property.q"
        write_text(q_path, formula + "\n")
        start = time.time()
        try:
            proc = subprocess.run(
                [str(verifyta), "-q", "-s", str(model_path), str(q_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = proc.stdout
            lower = output.lower()
            if "formula is satisfied" in lower:
                status = "satisfied"
            elif "formula is not satisfied" in lower:
                status = "not_satisfied"
            else:
                status = "error"
            return {
                "status": status,
                "exit_code": proc.returncode,
                "duration_sec": round(time.time() - start, 3),
                "output_tail": output[-1200:],
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "timeout",
                "exit_code": None,
                "duration_sec": timeout,
                "output_tail": (exc.stdout or "")[-1200:] if isinstance(exc.stdout, str) else "",
            }


def collect_candidate_properties(family_dir: Path) -> list[Property]:
    candidates: list[Property] = []
    ignored = {"versions", "references", "raw_sources"}
    for path in sorted(family_dir.rglob("*")):
        if path.suffix.lower() in {".q", ".md"} and not ignored.intersection(path.relative_to(family_dir).parts):
            candidates.extend(extract_properties_from_text(read_text(path), str(path)))
    return unique_properties(candidates)


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_references_and_raw(family_dir: Path) -> None:
    references_dir = family_dir / "references"
    raw_dir = family_dir / "raw_sources"
    ensure_clean_dir(references_dir)
    ensure_clean_dir(raw_dir)

    for item in sorted(family_dir.iterdir()):
        if item.name in {"versions", "references", "raw_sources"}:
            continue
        if item.is_file():
            target_root = references_dir if item.suffix.lower() in {".md", ".docx", ".pdf"} else raw_dir
            shutil.copy2(item, target_root / item.name)
        elif item.is_dir():
            target = references_dir / item.name if item.name in {"images", "doc"} else raw_dir / item.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)


def build_dataset(root: Path, verifyta: Path, timeout: int, apply_replacements: bool) -> dict:
    models = discover_models(root)
    summary = {
        "root": str(root),
        "verifyta": str(verifyta),
        "model_count": len(models),
        "families": {},
        "unresolved": [],
    }

    for model in models:
        family_dir = root / model.family
        copy_references_and_raw(family_dir)
        version_dir = family_dir / "versions" / model.model_id
        ensure_clean_dir(version_dir)
        canonical_xml = version_dir / "model.xml"

        properties: list[Property] = []
        if model.source_path.suffix.lower() == ".xml":
            xml_properties, tree = extract_xml_queries(model.source_path)
            properties.extend(xml_properties)
            write_xml(tree, canonical_xml)
        else:
            xta_to_xml(model.source_path, canonical_xml)

        for query_path in model.query_paths:
            if query_path.exists():
                properties.extend(extract_properties_from_text(read_text(query_path), str(query_path)))
        properties = unique_properties(properties)
        global_names = extract_global_names(canonical_xml)
        for prop in properties:
            prop.formula = rewrite_global_qualified_formula(prop.formula, global_names)
        properties = unique_properties(properties)

        candidates = collect_candidate_properties(family_dir)
        for candidate in candidates:
            candidate.formula = rewrite_global_qualified_formula(candidate.formula, global_names)
        candidates = unique_properties(candidates)
        used_formulas = {p.formula for p in properties}
        report = {
            "family": model.family,
            "model_id": model.model_id,
            "source_model": str(model.source_path),
            "canonical_model": str(canonical_xml),
            "query_sources": [str(p) for p in model.query_paths],
            "properties": [],
        }

        for index, prop in enumerate(properties, 1):
            result = verify_property(verifyta, canonical_xml, prop.formula, timeout)
            if result["status"] != "satisfied" and apply_replacements:
                for candidate in candidates:
                    if candidate.formula in used_formulas:
                        continue
                    candidate_result = verify_property(verifyta, canonical_xml, candidate.formula, timeout)
                    if candidate_result["status"] == "satisfied":
                        old = prop.formula
                        prop.formula = candidate.formula
                        prop.comments = candidate.comments
                        prop.source = candidate.source
                        prop.replaced_from = old
                        used_formulas.add(prop.formula)
                        result = candidate_result
                        result["replacement"] = {
                            "old_formula": old,
                            "new_formula": prop.formula,
                            "source": prop.source,
                        }
                        break

            entry = {
                "index": index,
                "formula": prop.formula,
                "status": result["status"],
                "duration_sec": result["duration_sec"],
                "source": prop.source,
            }
            if prop.replaced_from:
                entry["replaced_from"] = prop.replaced_from
            if result["status"] != "satisfied":
                entry["output_tail"] = result.get("output_tail", "")
                summary["unresolved"].append(
                    {
                        "family": model.family,
                        "model_id": model.model_id,
                        "index": index,
                        "formula": prop.formula,
                        "status": result["status"],
                    }
                )
            if "replacement" in result:
                entry["replacement"] = result["replacement"]
            report["properties"].append(entry)

        query_out = version_dir / f"{model.model_id}_ref.q"
        write_text(query_out, format_query_file(properties) if properties else "// no properties discovered\n")
        write_text(version_dir / "verification_report.json", json.dumps(report, ensure_ascii=False, indent=2))

        family_summary = summary["families"].setdefault(model.family, {"versions": []})
        family_summary["versions"].append(
            {
                "model_id": model.model_id,
                "property_count": len(properties),
                "satisfied_count": sum(1 for p in report["properties"] if p["status"] == "satisfied"),
                "unresolved_count": sum(1 for p in report["properties"] if p["status"] != "satisfied"),
            }
        )

    write_text(root / "dataset_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    write_text(root / "DATASET_INDEX.md", render_index(summary))
    write_text(root / "UNRESOLVED_PROPERTIES.md", render_unresolved(summary["unresolved"]))
    return summary


def render_index(summary: dict) -> str:
    lines = [
        "# MPTA-Repair Source Model Archive",
        "",
        f"- Model versions: {summary['model_count']}",
        f"- verifyta: `{summary['verifyta']}`",
        "",
        "| Family | Version | Properties | Satisfied | Unresolved |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for family, data in sorted(summary["families"].items()):
        for version in data["versions"]:
            lines.append(
                f"| {family} | {version['model_id']} | {version['property_count']} | "
                f"{version['satisfied_count']} | {version['unresolved_count']} |"
            )
    lines.append("")
    lines.append("Canonical files are under `versions/<version_id>/model.xml` and `<version_id>_ref.q`.")
    return "\n".join(lines) + "\n"


def render_unresolved(unresolved: list[dict]) -> str:
    lines = ["# unresolved properties", ""]
    if not unresolved:
        lines.append("All discovered properties are satisfied by their canonical models.")
    else:
        lines.extend(
            [
                "The following properties could not be verified as satisfied and no verified replacement was found automatically.",
                "",
                "| Family | Version | Index | Status | Formula |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        for item in unresolved:
            formula = item["formula"].replace("|", "\\|")
            lines.append(
                f"| {item['family']} | {item['model_id']} | {item['index']} | {item['status']} | `{formula}` |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--verifyta", type=Path, default=Path(DEFAULT_VERIFYTA))
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--no-replacements", action="store_true")
    args = parser.parse_args()

    if not args.verifyta.exists():
        raise SystemExit(f"verifyta not found: {args.verifyta}")
    if not args.root.exists():
        raise SystemExit(f"dataset root not found: {args.root}")

    summary = build_dataset(args.root, args.verifyta, args.timeout, not args.no_replacements)
    print(
        json.dumps(
            {
                "model_count": summary["model_count"],
                "unresolved_count": len(summary["unresolved"]),
                "summary": str(args.root / "DATASET_INDEX.md"),
                "unresolved": str(args.root / "UNRESOLVED_PROPERTIES.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
