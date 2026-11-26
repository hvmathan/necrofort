# Tasks: F77 Resurrection

## Phase 1: Foundation (`oracle-harness/`)

- [x] 1. Verify toolchain (`gfortran`, `cargo`, `wasm-pack`, `wasm32-unknown-unknown`)
  - _Requirements: 4.4_
- [x] 2. Vendor BioUMAT into `targets/bioumat/` with upstream MIT `LICENSE.md`, unmodified
  - _Requirements: 1.1, 1.2, 1.4_
- [x] 3. Kiro steering (`f77-semantics.md`, `rust-wasm-rules.md`, `verification-loop.md`), this spec, and `on-rust-edit` hook
- [x] 4. Scaffold `oracle-harness/` as `cdylib` + `rlib` with `wasm-bindgen` and `proptest`
  - _Requirements: 3.2_
- [x] 5. `build.rs`: extract `TRANSPOSE`, `DETERMINANT`, `VMATMUL`, `TENF` verbatim, compile with `gfortran -std=legacy -c`, archive, link into tests only, skip on wasm32
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
- [x] 6. Resurrect `VMATMUL` in `src/lib.rs` (`#![forbid(unsafe_code)]`, `#[wasm_bindgen]`)
  - _Requirements: 3.1, 3.2, 3.3_
- [x] 7. `tests/differential_pbt.rs`: 2 properties x 1,024 cases vs the gfortran oracle
  - _Requirements: 4.1, 4.2, 4.3_
- [x] 8. Pass gate: `cargo test`, `cargo clippy --all-targets -- -D warnings`, `wasm-pack build --target web`
  - _Requirements: 4.4, 4.5_

## Phase 2: Remaining kernels and UMAT

- [x] 9. Resurrect `DETERMINANT` + differential properties (general and near-singular)
  - _Requirements: 3.2, 4.1_
- [x] 10. Resurrect `TRANSPOSE` + property (bit-identical)
  - _Requirements: 3.2, 4.1_
- [x] 11. Resurrect `TENF` + property (covers the `N == 4` zero-fill branch)
  - _Requirements: 3.2, 4.1_
- [x] 12. Resurrect `UMAT`: `ABA_PARAM.INC` stand-in generated in `build.rs`, `GO TO 80/90` loop -> structured `for`, `&mut UmatState`, `#[wasm_bindgen] umat`
  - _Requirements: 2.2, 3.4, 3.5_

## Phase 2: `orchestrator/` (Python)

- [x] 13. `f77_analyzer.py`: fixed-form lexer, units, signatures, implicit typing, COMMON, CALL graph, GO TO labels, hazards, spec JSON/Markdown
  - _Requirements: 5.1_
- [x] 14. Leaves-first scheduler
  - _Requirements: 5.2_
- [x] 15. `graph.py` state machine with the 4-check oracle gate and `run_log.json`
  - _Requirements: 5.3, 5.5_
- [x] 16. Counterexample-driven self-heal with a 5-attempt cap and blocker report; `--demo-bug`
  - _Requirements: 5.4_
- [x] 17. Unit tests (`pytest orchestrator/tests`)

## Phase 2: `web-demo/`

- [x] 18. React + Vite + Tailwind static app loading `oracle-harness/pkg`
  - _Requirements: 6.1, 6.4_
- [x] 19. Dashboard tab (source, spec, state graph, counterexample, PR) and Lab tab (F sliders, stress / `b` plots, DDSDDE, errors)
  - _Requirements: 6.2, 6.3_

## Later

- [ ] 20. `FLOW` (pore-fluid boundary condition) port
- [ ] 21. `SDVINI`: decide how to handle code that does not compile as written (`CALL RANDOM-NUMBER`, integer `.OR.`)
- [ ] 22. Pluggable LLM healer for fault classes beyond index offsets
