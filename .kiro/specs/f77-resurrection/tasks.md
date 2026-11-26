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

## Phase 2: Remaining leaf kernels

- [ ] 9. Resurrect `DETERMINANT` + differential property (include near-singular `F`)
  - _Requirements: 3.2, 4.1_
- [ ] 10. Resurrect `TRANSPOSE` + property
  - _Requirements: 3.2, 4.1_
- [ ] 11. Resurrect `TENF` + property (check `N == 4` zero-fill branch)
  - _Requirements: 3.2, 4.1_

## Phase 2: `orchestrator/`

- [ ] 12. Create `orchestrator/` binary crate with a fixed-form F77 lexer (labels, continuation, comments, col 72 truncation)
  - _Requirements: 5.1_
- [ ] 13. Program-unit index and CALL/COMMON/INCLUDE dependency graph for `targets/bioumat`
  - _Requirements: 5.1_
- [ ] 14. Leaves-first scheduler
  - _Requirements: 5.2_
- [ ] 15. Per-routine pipeline: extraction entry, Rust draft, generated proptest, gate run, JSON report
  - _Requirements: 5.3, 5.5_
- [ ] 16. Enforce 5-attempt retry cap with blocker report
  - _Requirements: 5.4_
- [ ] 17. Resurrect `UMAT`: `ABA_PARAM.INC` shim generated in `build.rs`, `GO TO 80/90` loop -> structured `loop`, `&mut` state for `STATEV`/`DFGRD1`
  - _Requirements: 2.2, 3.4, 3.5_

## Phase 2: `web-demo/`

- [ ] 18. Static `web-demo/index.html` + ES module loading `oracle-harness/pkg`
  - _Requirements: 6.1, 6.4_
- [ ] 19. Deformation-gradient input form, `b = F F^T` output, error display
  - _Requirements: 6.2, 6.3_
