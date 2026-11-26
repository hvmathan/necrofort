//! Differential property tests: Rust resurrection vs. the gfortran-compiled
//! original (the oracle), linked in by `build.rs`.
//!
//! This file holds the only `unsafe` code in the repository (the C-FFI calls
//! into the Fortran object).

use oracle_harness::{vmatmul, Mat3};
use std::cell::Cell;

use proptest::prelude::*;
use proptest::test_runner::{Config, TestCaseError, TestRunner};

/// Cases per property. The verification gate requires at least 1,000.
const CASES: u32 = 1024;

/// Fills the output buffer so we can detect entries the routine did not write.
const SENTINEL: f64 = -9.876_543_21e101;

extern "C" {
    /// `SUBROUTINE VMATMUL(A,B,N,C)` from targets/bioumat/SUBROUTINES.FOR.
    /// gfortran passes every argument by reference; default INTEGER is 32-bit.
    fn vmatmul_(a: *const f64, b: *const f64, n: *const i32, c: *mut f64);
}

/// Calls the Fortran oracle with `N = c.len()`.
fn oracle_vmatmul(a: &Mat3, b: &Mat3, c: &mut [f64]) {
    // VMATMUL writes C(1..4) unconditionally; shorter buffers would be UB.
    assert!(c.len() >= 4, "oracle needs N >= 4");
    let n = i32::try_from(c.len()).expect("N fits in INTEGER*4");
    // SAFETY: `a` and `b` point to 9 f64 values (A(3,3), B(3,3)), which is all
    // VMATMUL reads. It writes C(1..4), plus C(5..6) only when N == 6, so with
    // c.len() >= 4 (and == 6 for the extra writes) every write is in bounds.
    // `n` is a valid i32 that outlives the call. The routine keeps no pointers.
    unsafe { vmatmul_(a.as_ptr(), b.as_ptr(), &n, c.as_mut_ptr()) }
}

/// Indices of C (0-based) that VMATMUL writes for a given N.
fn written(n: usize, k: usize) -> bool {
    k < 4 || (n == 6 && k < 6)
}

/// Compares Rust and oracle outputs for one input.
///
/// Written entries must agree within the forward error bound of a 3-term dot
/// product, `8 * EPS * sum_k |A(i,k)| * |B(k,j)|` (computed with the same routine on
/// |A|, |B|). Unwritten entries must still hold the sentinel bit pattern in both.
fn check_case(a: &Mat3, b: &Mat3, n: usize) -> Result<(), TestCaseError> {
    let mut rust = vec![SENTINEL; n];
    let mut fort = vec![SENTINEL; n];
    vmatmul(a, b, &mut rust).map_err(|e| TestCaseError::fail(e.to_string()))?;
    oracle_vmatmul(a, b, &mut fort);

    let abs_a: Mat3 = a.map(f64::abs);
    let abs_b: Mat3 = b.map(f64::abs);
    let mut scale = vec![0.0; n];
    vmatmul(&abs_a, &abs_b, &mut scale).map_err(|e| TestCaseError::fail(e.to_string()))?;

    for k in 0..n {
        if written(n, k) {
            let tol = 8.0 * f64::EPSILON * scale[k] + f64::MIN_POSITIVE;
            let diff = (rust[k] - fort[k]).abs();
            prop_assert!(
                rust[k].is_finite() && diff <= tol,
                "N={} C({}) rust={:e} oracle={:e} diff={:e} tol={:e}",
                n,
                k + 1,
                rust[k],
                fort[k],
                diff,
                tol
            );
        } else {
            prop_assert_eq!(
                rust[k].to_bits(),
                SENTINEL.to_bits(),
                "rust wrote C({})",
                k + 1
            );
            prop_assert_eq!(
                fort[k].to_bits(),
                SENTINEL.to_bits(),
                "oracle wrote C({})",
                k + 1
            );
        }
    }
    Ok(())
}

fn runner() -> TestRunner {
    TestRunner::new(Config {
        cases: CASES,
        failure_persistence: None,
        ..Config::default()
    })
}

/// Bounded, finite matrix entries (no NaN / Inf).
fn mat3(lo: f64, hi: f64) -> impl Strategy<Value = Mat3> {
    prop::array::uniform9(lo..hi)
}

#[test]
fn vmatmul_matches_oracle_general() {
    let cases = Cell::new(0u32);
    runner()
        .run(
            &(mat3(-1.0e3, 1.0e3), mat3(-1.0e3, 1.0e3), 4usize..=8),
            |(a, b, n)| {
                cases.set(cases.get() + 1);
                check_case(&a, &b, n)
            },
        )
        .unwrap();
    let cases = cases.get();
    println!("vmatmul_matches_oracle_general: {cases} cases passed");
    assert!(cases >= CASES, "only {cases} cases ran");
}

#[test]
fn vmatmul_matches_oracle_left_cauchy_green() {
    // UMAT usage: BVEC = VMATMUL(F, F^T) with F = I + H near identity.
    let cases = Cell::new(0u32);
    runner()
        .run(
            &(mat3(-0.5, 0.5), prop_oneof![Just(4usize), Just(6usize)]),
            |(h, n)| {
                cases.set(cases.get() + 1);
                let mut f = h;
                for i in 0..3 {
                    f[i + 3 * i] += 1.0;
                }
                let mut ft = [0.0; 9];
                for i in 0..3 {
                    for j in 0..3 {
                        ft[j + 3 * i] = f[i + 3 * j];
                    }
                }
                check_case(&f, &ft, n)?;

                let mut bvec = vec![0.0; n];
                vmatmul(&f, &ft, &mut bvec).map_err(|e| TestCaseError::fail(e.to_string()))?;
                for (k, v) in bvec.iter().take(3).enumerate() {
                    prop_assert!(*v >= 0.0, "diagonal b({0},{0}) = {1:e} < 0", k + 1, v);
                }
                Ok(())
            },
        )
        .unwrap();
    let cases = cases.get();
    println!("vmatmul_matches_oracle_left_cauchy_green: {cases} cases passed");
    assert!(cases >= CASES, "only {cases} cases ran");
}

#[test]
fn oracle_is_linked_and_sane() {
    let i3: Mat3 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];
    let mut c = [SENTINEL; 6];
    oracle_vmatmul(&i3, &i3, &mut c);
    assert_eq!(c, [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]);
}
