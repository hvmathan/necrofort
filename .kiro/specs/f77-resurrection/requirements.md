# Requirements: F77 Resurrection

## Introduction

NecroFort translates legacy Fortran 77 numerical code into memory-safe Rust that
also compiles to WebAssembly. Every translated routine is proven equivalent to
the original by differential property-based testing against the original code
compiled with gfortran (the "oracle").

The first target is BioUMAT (`targets/bioumat/SUBROUTINES.FOR`, MIT, (c) 2019
Seyed Shayan Sajjadinia, upstream https://github.com/shayansss/bioumat at
commit `70c0ee3`): an Abaqus UMAT for multiphasic cartilage with Voigt-notation
tensor helpers.

The project has three components:

- `oracle-harness/`: Rust library of resurrected routines plus the differential test harness.
- `orchestrator/`: agent pipeline that picks the next routine, drafts the translation, and runs the verification gate.
- `web-demo/`: browser page that runs the wasm build of `oracle-harness`.

## Requirement 1: Authentic, permissively licensed targets

**User story:** As a maintainer, I want every Fortran target to be real legacy
code under a permissive license, so the project can be published under MIT.

1. WHEN a Fortran target is added THEN it SHALL be stored under `targets/<name>/` with its upstream license file unchanged.
2. The system SHALL only accept targets and dependencies licensed MIT, BSD-3-Clause, or Apache-2.0.
3. The system SHALL NOT include, port, or link ACM TOMS / CALGO code.
4. Upstream source files SHALL NOT be edited. Any compatibility shims (missing includes, extraction) SHALL be generated at build time.

## Requirement 2: Fortran oracle

**User story:** As a verifier, I want the original Fortran compiled as-is, so
tests compare against the real behaviour rather than my reading of it.

1. WHEN `oracle-harness` is built for a native target THEN `build.rs` SHALL compile the selected routines with `gfortran -std=legacy -c`.
2. WHEN the upstream file contains routines that do not compile under `-std=legacy` THEN `build.rs` SHALL extract only the routines under test, verbatim, and SHALL fail the build if a requested routine is missing.
3. The oracle object SHALL be linked only into test binaries, never into the library or the wasm artifact.
4. WHEN building for `wasm32-*` THEN `build.rs` SHALL skip the Fortran step.

## Requirement 3: Safe resurrected routines

**User story:** As a library user, I want the translated routines to be
memory-safe and callable from Rust and JavaScript.

1. `oracle-harness/src/lib.rs` SHALL declare `#![forbid(unsafe_code)]`.
2. Each resurrected routine SHALL be exposed as a pure Rust function and as a `#[wasm_bindgen]` entrypoint.
3. WHEN inputs would cause out-of-bounds access in the original THEN the Rust routine SHALL return an error instead of reading or writing out of bounds.
4. COMMON blocks and persisted locals SHALL be modelled as explicit structs passed by `&mut`.
5. GOTO-based control flow SHALL be replaced by structured control flow with the original labels documented.

## Requirement 4: Differential verification gate

**User story:** As a reviewer, I want automated evidence that each translation matches the original.

1. Each resurrected routine SHALL have at least one `proptest` property with at least 1,000 cases comparing Rust output with the oracle.
2. Generated inputs SHALL be finite and bounded (no NaN/Inf).
3. Comparisons SHALL use a tolerance derived from the floating-point error bound of the operation.
4. A pull request SHALL only be opened when `cargo test`, `cargo clippy -- -D warnings`, and `wasm-pack build --target web` all pass and the oracle compiles.
5. Fix-and-retry loops SHALL be capped at 5 attempts, after which the blocker is reported.

## Requirement 5: Orchestrator (Phase 2)

**User story:** As an operator, I want an agent pipeline that resurrects routines one by one without manual bookkeeping.

1. The orchestrator SHALL parse a target file and list its program units with their dependencies (CALL graph, COMMON usage, INCLUDEs).
2. The orchestrator SHALL schedule routines leaves-first (a routine is translated only after the routines it calls).
3. FOR each routine the orchestrator SHALL generate the Rust translation, the oracle extraction entry, and the differential test, then run the verification gate.
4. WHEN the gate fails 5 times for a routine THEN the orchestrator SHALL stop work on it and record the failing command and output.
5. The orchestrator SHALL run all verification locally.

## Requirement 6: Web demo (Phase 2)

**User story:** As a visitor, I want to run the resurrected code in my browser.

1. The web demo SHALL load the `wasm-pack --target web` output without a bundler.
2. The web demo SHALL let users enter a deformation gradient and show the computed Voigt tensor results.
3. WHEN the wasm routine returns an error THEN the page SHALL display the message instead of failing silently.
4. The web demo SHALL use only static assets.
