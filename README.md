# necrofort
NecroFort: Autonomous Kiro agent swarm resurrecting 1978 Fortran 77 into safe Rust + WebAssembly verified by gfortran + proptest

## Layout

| Path | What |
|------|------|
| `targets/bioumat/` | BioUMAT Fortran 77 source (MIT), unmodified |
| `oracle-harness/` | Safe Rust ports (`TRANSPOSE`, `DETERMINANT`, `VMATMUL`, `TENF`, `UMAT`) + gfortran differential proptests + wasm entrypoints |
| `orchestrator/` | `f77_analyzer.py` (fixed-form parser -> Kiro spec) and `graph.py` (Parse -> Spec -> Transmute -> Oracle Gate -> Self-Heal -> PR state machine) |
| `web-demo/` | React + Vite + Tailwind UI: swarm dashboard and live WASM BioUMAT lab |
| `.kiro/` | Steering, spec, and hooks |

## Run it

Requires gfortran, Rust with `wasm32-unknown-unknown`, wasm-pack, Python 3.10+, Node 20+ (see `Dockerfile`).

```sh
cd oracle-harness && cargo test && cargo clippy --all-targets -- -D warnings && wasm-pack build --target web && cd ..
python3 -m pytest orchestrator/tests
python3 orchestrator/graph.py --demo-bug      # plants a 1-based-index bug, catches and heals it, writes orchestrator/out/run_log.json
cd web-demo && npm ci && npm run build        # or: npm run dev
```
