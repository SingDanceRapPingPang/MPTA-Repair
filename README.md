# MPTA-Repair

**MPTA-Repair** stands for **Multi-Property Timed Automata Repair**.

This project studies dataset construction and follow-up repair methods for timed automata that must satisfy multiple temporal properties simultaneously. The current stage focuses on building a curated benchmark from UPPAAL timed-automata models and verified property sets.

## Name Rationale

- **MP**: Multi-Property, because each model may contain several properties that should be preserved or repaired together.
- **TA**: Timed Automata, the formal model used throughout the project.
- **Repair**: the target research task, namely repairing faulty timed automata after mutation-based error injection.

## Dataset

The curated model/property dataset is stored in:

```text
models/curated_model_with_properties
```

The archival source models and references remain in:

```text
models/model_with_ref
```

Regenerate the curated dataset:

```powershell
python scripts\build_curated_dataset.py
```

Generate the Bound Modification faulty dataset:

```powershell
python scripts\build_bound_modified_error_dataset.py
```

The generated mutants are stored in `models/bound_modified_error_dataset`.
Each mutant applies one clock-bound change and is kept only when `verifyta`
finds at least one violated property from the original property set.

Generate the two-fault boundary dataset:

```powershell
python scripts\build_bound_modified_error_dataset.py --fault-count 2
```

The generated mutants are stored in `models/bound2_dataset` by default. Each
mutant applies two non-overlapping clock-bound changes, then uses the same
property-violation and TARTAR-style admissibility filters as the one-fault
dataset. Two-fault generation keeps at most 20 final mutants per model unless
`--stop-after-kept-per-model` is set explicitly.
