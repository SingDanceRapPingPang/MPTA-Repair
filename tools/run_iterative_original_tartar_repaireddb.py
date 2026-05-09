#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = (
    ROOT
    / "models"
    / "multi_counterexample_examples"
    / "TarTarRepairedDB"
    / "2repaireddb_multi"
    / "bound_multi_0001"
    / "model.xml"
)
DEFAULT_PROPERTIES = DEFAULT_MODEL.with_name("properties.q")
DEFAULT_OUT = ROOT / "experiments" / "iterative_original_tartar_repaireddb_20260509"
WRAPPER = ROOT / "tools" / "run_with_uppaal_blacklist_server.sh"
JAR = "../release/tartar.main-3.1.0.jar"
VERIFYTA = Path(r"D:\tool\programming\uppaal\UPPAAL-5.0.0\bin\verifyta.exe")


@dataclass(frozen=True)
class State:
    model: Path
    depth: int
    history: tuple[dict, ...]


def wsl_path(path: Path) -> str:
    result = subprocess.run(
        ["wsl", "-e", "wslpath", "-a", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def read_properties(path: Path) -> list[str]:
    formulas: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("//"):
            formulas.append(line)
    return formulas


def strip_queries(text: str) -> str:
    return re.sub(r"\s*<queries>.*?</queries>\s*", "\n", text, flags=re.S)


def write_model_with_single_query(model: Path, formula: str, dest: Path) -> None:
    text = strip_queries(model.read_text(encoding="utf-8"))
    query = "\n".join(
        [
            "  <queries>",
            "    <query>",
            f"      <formula>{html.escape(formula)}</formula>",
            "      <comment></comment>",
            "    </query>",
            "  </queries>",
        ]
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text.replace("</nta>", query + "\n</nta>"), encoding="utf-8")


def model_hash(path: Path) -> str:
    text = strip_queries(path.read_text(encoding="utf-8"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_one(model: Path, formula: str, timeout: int = 90) -> dict:
    query = OUT / "_queries" / (hashlib.sha1(formula.encode("utf-8")).hexdigest() + ".q")
    query.parent.mkdir(parents=True, exist_ok=True)
    query.write_text(formula + "\n", encoding="utf-8")
    start = time.time()
    proc = subprocess.run(
        [str(VERIFYTA), "-q", "-s", str(model), str(query)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = round(time.time() - start, 3)
    lower = proc.stdout.lower()
    if "formula is satisfied" in lower:
        status = "satisfied"
    elif "formula is not satisfied" in lower:
        status = "not_satisfied"
    else:
        status = "error"
    return {
        "formula": formula,
        "status": status,
        "satisfied": status == "satisfied",
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "output_tail": proc.stdout[-1200:],
    }


def verify_all(model: Path, formulas: list[str]) -> dict:
    results = []
    for index, formula in enumerate(formulas, start=1):
        result = verify_one(model, formula)
        result["index"] = index
        results.append(result)
    violated = [r["index"] for r in results if not r["satisfied"]]
    return {
        "status": "satisfied" if not violated else "not_satisfied",
        "violated_properties": violated,
        "results": results,
    }


def parse_candidate_statuses(stdout: str) -> dict[int, str]:
    statuses: dict[int, str] = {}
    current: int | None = None
    for line in stdout.splitlines():
        match = re.search(r"Search repair\s+(\d+):.*$", line)
        if match:
            current = int(match.group(1))
            if line.rstrip().endswith("[]"):
                current = None
            continue
        if current is not None and "Admissible:" in line:
            statuses[current] = "admissible"
            current = None
        elif current is not None and "Inadmissible:" in line:
            statuses[current] = "inadmissible"
            current = None
    return statuses


def run_tartar(model: Path, formula: str, prop_index: int, node_id: int, depth: int) -> dict:
    job_root = OUT / "rounds" / f"depth_{depth}" / f"node_{node_id:04d}_p{prop_index}"
    if job_root.exists():
        shutil.rmtree(job_root)
    job_root.mkdir(parents=True, exist_ok=True)
    model_with_query = job_root / "model_with_query.xml"
    write_model_with_single_query(model, formula, model_with_query)
    job_dir = job_root / "Job_RepairComputation"

    cmd = (
        "cd /mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master/tartar && "
        "export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 && "
        "export TARTAR_ROOT=/mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master && "
        "export PATH=$JAVA_HOME/bin:$TARTAR_ROOT/ltsmin-3.0.2/src/pins2lts-mc:$TARTAR_ROOT/opaal/bin:$PATH && "
        "export PYTHONPATH=$TARTAR_ROOT/opaal:$TARTAR_ROOT/pyuppaal:${PYTHONPATH:-} && "
        "export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu/jni:/lib:/usr/lib:/usr/local/lib:../lib:${LD_LIBRARY_PATH:-} && "
        f"timeout 300s {wsl_path(WRAPPER)} "
        f"java -Xmx4g -jar {JAR} "
        f"-run iterative_repaireddb_d{depth}_n{node_id}_p{prop_index} Job_RepairComputation "
        f"-Folder {wsl_path(job_dir)} "
        f"-Model {wsl_path(model_with_query)} "
        "-TimeoutZ3 600 "
        "-RepairKind BOUNDARY"
    )
    start = time.time()
    proc = subprocess.run(
        ["wsl", "-e", "bash", "-lc", cmd],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=360,
    )
    elapsed = round(time.time() - start, 3)
    (job_root / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (job_root / "stderr.txt").write_text(proc.stderr, encoding="utf-8")

    statuses = parse_candidate_statuses(proc.stdout)
    candidates = []
    for candidate in sorted(job_dir.glob("*_rep*.xml")):
        match = re.search(r"_rep(\d+)\.xml$", candidate.name)
        number = int(match.group(1)) if match else len(candidates) + 1
        status = statuses.get(number, "unknown")
        if status == "admissible":
            candidates.append(
                {
                    "repair_number": number,
                    "path": str(candidate),
                    "admissibility": status,
                    "hash": model_hash(candidate),
                }
            )
    return {
        "property_index": prop_index,
        "formula": formula,
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "timed_out": proc.returncode == 124,
        "stdout": str(job_root / "stdout.txt"),
        "stderr": str(job_root / "stderr.txt"),
        "job_dir": str(job_dir),
        "candidate_statuses": statuses,
        "admissible_candidates": candidates,
        "candidate_count": len(candidates),
        "no_counterexample": "No trace file found" in proc.stdout,
        "qe_failed_or_exception": "Run QE failed" in proc.stdout
        or "Z3Exception" in proc.stdout
        or "Exception" in proc.stderr,
    }


def main() -> int:
    model = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_MODEL
    properties = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEFAULT_PROPERTIES
    out = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else DEFAULT_OUT
    max_depth = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    max_nodes = int(sys.argv[5]) if len(sys.argv) > 5 else 80
    wall_timeout = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0

    global OUT
    OUT = out
    OUT.mkdir(parents=True, exist_ok=True)
    formulas = read_properties(properties)

    queue: deque[State] = deque([State(model, 0, tuple())])
    seen = {model_hash(model)}
    explored = []
    successful_state: dict | None = None
    timed_out = False
    node_id = 0
    start_time = time.time()

    while queue and node_id < max_nodes:
        if wall_timeout and time.time() - start_time >= wall_timeout:
            timed_out = True
            break
        state = queue.popleft()
        node_id += 1
        verification = verify_all(state.model, formulas)
        node_record = {
            "node": node_id,
            "depth": state.depth,
            "model": str(state.model),
            "hash": model_hash(state.model),
            "history": list(state.history),
            "verification": verification,
            "tartar_jobs": [],
        }
        print(
            f"node={node_id} depth={state.depth} violated={verification['violated_properties']}",
            flush=True,
        )
        if verification["status"] == "satisfied":
            successful_state = node_record
            explored.append(node_record)
            break
        if state.depth >= max_depth:
            explored.append(node_record)
            continue

        for prop_index in verification["violated_properties"]:
            if wall_timeout and time.time() - start_time >= wall_timeout:
                timed_out = True
                break
            formula = formulas[prop_index - 1]
            job = run_tartar(state.model, formula, prop_index, node_id, state.depth + 1)
            node_record["tartar_jobs"].append(job)
            for candidate in job["admissible_candidates"]:
                candidate_path = Path(candidate["path"])
                if candidate["hash"] in seen:
                    continue
                seen.add(candidate["hash"])
                history = (
                    *state.history,
                    {
                        "from_node": node_id,
                        "property_index": prop_index,
                        "candidate": candidate["path"],
                    },
                )
                queue.append(State(candidate_path, state.depth + 1, history))
        explored.append(node_record)

    summary = {
        "baseline": "iterative original TarTar BOUNDARY with branching over violated properties and admissible TarTar candidates",
        "model": str(model),
        "properties": str(properties),
        "output_root": str(OUT),
        "max_depth": max_depth,
        "max_nodes": max_nodes,
        "wall_timeout_sec": wall_timeout,
        "elapsed_sec": round(time.time() - start_time, 3),
        "explored_nodes": len(explored),
        "unique_models_seen": len(seen),
        "queue_remaining": len(queue),
        "status": "success" if successful_state else ("timeout" if timed_out else "failed"),
        "successful_state": successful_state,
        "explored": explored,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if successful_state:
        return 0
    return 2 if timed_out else 1


if __name__ == "__main__":
    raise SystemExit(main())
