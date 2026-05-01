# MPTA-Repair Source Model Archive

This directory is the archival source model collection for **MPTA-Repair**: Multi-Property Timed Automata Repair. It is normalized by `scripts/prepare_model_with_ref_dataset.py`.

For each model family, canonical model versions are stored as:

```text
<family>/
  versions/
    <version_id>/
      model.xml
      <version_id>_ref.q
      verification_report.json
  references/
  raw_sources/
```

- `model.xml` is the canonical UPPAAL XML model. Embedded XML queries are removed.
- `<version_id>_ref.q` contains all collected properties for that model version.
- `verification_report.json` records the per-property `verifyta` result.
- `DATASET_INDEX.md` summarizes all versions.
- `UNRESOLVED_PROPERTIES.md` lists properties that still need manual replacement.

Regenerate the normalized dataset:

```powershell
python scripts\prepare_model_with_ref_dataset.py --root models\model_with_ref --verifyta "D:\tool\programming\uppaal\UPPAAL-5.0.0\bin\verifyta.exe" --timeout 90
```
