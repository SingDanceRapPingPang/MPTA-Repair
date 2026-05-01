# Cleanup manifest

This project is now named **MPTA-Repair**: Multi-Property Timed Automata Repair.
It is focused on constructing and validating multi-property timed-automata datasets under `models/model_with_ref` and `models/curated_model_with_properties`.

Removed as unrelated generated or legacy material:

- `models/dataset/`: previous faulty/mutated dataset output.
- `models/mutated_model/`: previous mutation-paper material and generated assets.
- `build/`, `.pytest_cache/`, `__pycache__/`: generated caches/build output.
- `node_modules/`, `package.json`, `package-lock.json`, `create_ppt.js`: PPT generation tooling unrelated to the dataset pipeline.
- `copy_dataset.py`, `copy_models.py`: old one-off copy helpers.
- `fault_injection.py`: previous mutation injection script; future mutation should be rebuilt on top of the normalized dataset.
- `main.py`, `main.spec`, `src/train.py`, `src/test.py`: old application/PyInstaller entry points.
- `src/config/`, `src/example_usage.py`, `src/README.md`, `src/resources/`, `src/utils/trace_analyse.py`: old app, pyuppaal example, and counterexample-analysis material.
