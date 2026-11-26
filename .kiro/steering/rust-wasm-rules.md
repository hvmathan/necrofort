---
inclusion: fileMatch
fileMatchPattern: ["oracle-harness/**", "orchestrator/**", "web-demo/**", "**/*.rs", "**/Cargo.toml"]
---

# Rust + WebAssembly Rules

## Safety

- `oracle-harness/src/lib.rs` must start with `#![forbid(unsafe_code)]`. `forbid`
  (not `deny`) so no inner `#[allow]` can re-enable it.
- The only `unsafe` in the workspace is the gfortran C-FFI oracle, and it lives
  strictly in `oracle-harness/tests/differential_pbt.rs`. Each `unsafe` block gets a
  `// SAFETY:` comment stating the buffer sizes the Fortran routine reads and writes.
- Library code never panics on user input: validate lengths and dimensions and
  return `Result<_, NecroError>`-style errors. `unwrap`/`expect` only in tests and `build.rs`.

## Translating F77 state

- Replace every `COMMON` block and persisted local with an explicit struct and pass
  it as `&mut State`. No `static mut`, `thread_local!`, `lazy_static`, or `OnceCell` globals.
- Fortran in/out arguments become `&mut` parameters, inputs become `&` or by value.
- Keep matrices as flat column-major `[f64; 9]` / `&[f64]` buffers so they can be
  passed to the oracle and across the wasm boundary without reshaping. Access them
  through a 1-based `at(a, i, j)` helper.
- Keep the Fortran routine name in the doc comment (`/// Resurrection of F77 VMATMUL`)
  and link the source file and line.

## WebAssembly boundary

- Each resurrected routine gets two layers:
  1. A pure Rust function (`vmatmul`) with idiomatic types, used by tests and other crates.
  2. A thin `#[wasm_bindgen]` entrypoint (`vmatmul_wasm`, exported to JS as `vmatmul`)
     taking `&[f64]` / `usize` and returning `Result<Vec<f64>, JsError>`.
- Do not call `JsError`/`JsValue` constructors from native tests; they only work on wasm32.
- Crates that ship to the browser use `crate-type = ["cdylib", "rlib"]`.
- `build.rs` must be a no-op for `wasm32-*` targets (gfortran cannot target wasm).

## Dependencies and licensing

- Project license: MIT. Third-party code and crates must be MIT, BSD-3-Clause, or
  Apache-2.0 (dual MIT/Apache-2.0 is fine).
- Never copy, port, or link ACM TOMS / CALGO code (ACM Software License, not OSI-permissive).
- Vendored Fortran targets keep their upstream `LICENSE` next to the source.

## Lint bar

- `cargo clippy --all-targets -- -D warnings` must be clean. Fix lints; do not blanket `#[allow]`.
- `cargo fmt` formatting.
