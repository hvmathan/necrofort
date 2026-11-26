---
inclusion: always
---

# Verification Loop (mandatory gate)

No pull request is opened, and no task is marked done, unless all four checks
pass locally. Run them in this order; a failure stops the gate.

| # | Check | Command (from repo root) | Pass criteria |
|---|-------|--------------------------|---------------|
| 1 | Fortran oracle compiles | `gfortran -std=legacy -ffp-contract=off -c <extracted kernels>.f` (run by `oracle-harness/build.rs`) | exit 0, no errors |
| 2 | Differential property tests | `cd oracle-harness && cargo test` | every test passes; each `proptest!` property runs >= 1,000 cases (`ProptestConfig::with_cases(1024)`) |
| 3 | Lints | `cd oracle-harness && cargo clippy --all-targets -- -D warnings` | zero warnings |
| 4 | Wasm build | `cd oracle-harness && wasm-pack build --target web` | `pkg/` produced with `.wasm` + JS glue |

## Rules

- All runs are local. Do not offload verification to paid or remote CI to save time.
- Retry budget: at most 5 fix-and-retry attempts for the whole gate. After the
  fifth failed attempt, stop and report the exact failing command, its error
  output, and what was tried. Do not keep looping.
- Property inputs are bounded, finite ranges (for example `-1.0e3..1.0e3` for
  `f64`). Never feed NaN or Inf unless the property is specifically about them.
- Tolerance is tight and justified: compare with an error bound derived from the
  operation (e.g. `8 * f64::EPSILON * sum(|a_ik| * |b_kj|)` for a 3-term dot
  product), not an arbitrary `1e-6`.
- Tests compare the Rust implementation against the gfortran-compiled original
  (the oracle), not against a re-derivation of the math.
- Do not weaken a property, shrink the case count, or widen a tolerance to make a
  failure go away. Investigate the mismatch first and record the cause.

## Sandbox notes

In Kiro Web sandboxes the root filesystem may be read-only. If `gfortran`,
`wasm-pack`, or the `wasm32-unknown-unknown` target are missing, install them into
a writable directory outside the repo (for example `/projects/sandbox/.toolchain`)
and export `PATH`, `RUSTUP_HOME`, `CARGO_HOME`, `LIBRARY_PATH`, and
`XDG_CACHE_HOME`. The repo `Dockerfile` provides the full toolchain for normal use.
