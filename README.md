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
