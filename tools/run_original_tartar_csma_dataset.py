#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "models" / "bound_modified_error_dataset" / "csma_cd" / "2csma"
OUT = ROOT / "experiments" / "original_tartar_dataset_csma_current_20260506"
TARTAR_DIR = ROOT / "TarTar-master" / "tartar"
WRAPPER = ROOT / "tools" / "run_with_uppaal_blacklist_server.sh"
JAR = "../release/tartar.main-3.1.0.jar"
REPAIR_KINDS = ["BOUNDARY", "RESET", "URGENT", "COMPARISON", "REFERENCE"]


def wsl_path(path: Path) -> str:
    result = subprocess.run(
        ["wsl", "-e", "wslpath", "-a", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def read_properties(path: Path) -> list[str]:
    formulas: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        formulas.append(line)
    return formulas


def write_model_with_queries(model: Path, properties: Path, dest: Path) -> list[str]:
    formulas = read_properties(properties)
    text = model.read_text(encoding="utf-8")
    text = re.sub(r"<queries>.*?</queries>", "", text, flags=re.S)
    queries = ["  <queries>"]
    for formula in formulas:
        queries.extend(
            [
                "    <query>",
                f"      <formula>{html.escape(formula)}</formula>",
                "      <comment></comment>",
                "    </query>",
            ]
        )
    queries.append("  </queries>")
    if "</nta>" not in text:
        raise ValueError(f"missing </nta> in {model}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text.replace("</nta>", "\n".join(queries) + "\n</nta>"), encoding="utf-8")
    return formulas


def run_job(mod_dir: Path, repair_kind: str) -> dict:
    mod_id = mod_dir.name
    work = OUT / repair_kind.lower() / mod_id
    model_with_queries = work / "model_with_queries.xml"
    formulas = write_model_with_queries(mod_dir / "model.xml", mod_dir / "properties.q", model_with_queries)

    folder_rel = f"../experiments/original_tartar_dataset_csma_current_20260506/{mod_id}/Job_RepairComputation"
    cmd = (
        "cd /mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master/tartar && "
        "export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 && "
        "export TARTAR_ROOT=/mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master && "
        "export PATH=$JAVA_HOME/bin:$TARTAR_ROOT/ltsmin-3.0.2/src/pins2lts-mc:$TARTAR_ROOT/opaal/bin:$PATH && "
        "export PYTHONPATH=$TARTAR_ROOT/opaal:$TARTAR_ROOT/pyuppaal:${PYTHONPATH:-} && "
        "export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu/jni:/lib:/usr/lib:/usr/local/lib:../lib:${LD_LIBRARY_PATH:-} && "
        f"timeout 180s {wsl_path(WRAPPER)} "
        f"java -Xmx4g -jar {JAR} "
        f"-run original_dataset_{repair_kind.lower()}_{mod_id} Job_RepairComputation "
        f"-Folder ../experiments/original_tartar_dataset_csma_current_20260506/{repair_kind.lower()}/{mod_id}/Job_RepairComputation "
        f"-Model {wsl_path(model_with_queries)} "
        "-TimeoutZ3 120 "
        f"-RepairKind {repair_kind}"
    )
    start = time.time()
    proc = subprocess.run(
        ["wsl", "-e", "bash", "-lc", cmd],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=240,
    )
    elapsed = time.time() - start
    (work / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (work / "stderr.txt").write_text(proc.stderr, encoding="utf-8")

    symbolic_candidates = [
        line
        for line in re.findall(r"^.*Search repair \d+:\s+.*$", proc.stdout, flags=re.M)
        if not line.rstrip().endswith("[]")
    ]
    printed_repairs = re.findall(r"^\s*Repair/", proc.stdout, flags=re.M)
    inadmissible = len(re.findall(r"\bInadmissible:", proc.stdout))
    admissible = len(re.findall(r"\bAdmissible:", proc.stdout))
    no_trace = "No trace file found" in proc.stdout
    qe_failed = "Run QE failed" in proc.stdout or "Z3Exception" in proc.stdout or "Exception" in proc.stderr
    timed_out = proc.returncode == 124
    normal = proc.returncode == 0 and not qe_failed and not no_trace
    return {
        "id": mod_id,
        "repair_kind": repair_kind,
        "model": str(mod_dir / "model.xml"),
        "formulas": formulas,
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "symbolic_repair_candidates": len(symbolic_candidates),
        "printed_repairs": len(printed_repairs),
        "inadmissible_candidates": inadmissible,
        "admissible_candidates": max(0, admissible),
        "successful_repair": max(0, admissible) > 0 or len(printed_repairs) > 0,
        "normal_completion": normal,
        "no_counterexample": no_trace,
        "qe_failed_or_exception": qe_failed,
        "timed_out": timed_out,
        "stdout": str(work / "stdout.txt"),
        "stderr": str(work / "stderr.txt"),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    model_dirs = [p for p in sorted(DATASET.glob("bound_mod_*")) if (p / "model.xml").exists()]
    for repair_kind in REPAIR_KINDS:
        for mod_dir in model_dirs:
            print(f"running {repair_kind} {mod_dir.name}", flush=True)
            results.append(run_job(mod_dir, repair_kind))

    successful_ids = sorted({r["id"] for r in results if r["successful_repair"] and r["normal_completion"]})
    candidate_ids = sorted({r["id"] for r in results if r["symbolic_repair_candidates"] > 0})
    summary = {
        "dataset": str(DATASET),
        "repair_kinds": REPAIR_KINDS,
        "total_models": len(model_dirs),
        "total_jobs": len(results),
        "models_with_symbolic_repair_candidates": len(candidate_ids),
        "models_successfully_repaired": len(successful_ids),
        "successful_model_ids": successful_ids,
        "models_timed_out": len([r for r in results if r["timed_out"]]),
        "models_qe_failed_or_exception": len([r for r in results if r["qe_failed_or_exception"]]),
        "results": results,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
