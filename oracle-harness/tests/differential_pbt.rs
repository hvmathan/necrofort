//! Differential property tests: Rust resurrection vs. the gfortran-compiled
//! original (the oracle), linked in by `build.rs`.
//!
//! This file holds the only `unsafe` code in the repository (the C-FFI calls
//! into the Fortran object).
//!
//! On a mismatch the failure reason is a single line
//! `NECRO_COUNTEREXAMPLE {json}` describing the routine, the mismatching output
//! entry, both values, and the (shrunk) inputs. `orchestrator/graph.py` parses
//! it for the self-heal step, so keep the format stable.

use std::cell::Cell;
use std::fmt::Debug;

use oracle_harness::{determinant, tenf, transpose, umat, vmatmul, Mat3, UmatState};
use proptest::prelude::*;
use proptest::test_runner::{Config, TestCaseError, TestError, TestRunner};

/// Cases per property. The verification gate requires at least 1,000.
const CASES: u32 = 1024;

/// Fills output buffers so we can detect entries a routine did not write.
const SENTINEL: f64 = -9.876_543_21e101;

const I3: Mat3 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];

// ---------------------------------------------------------------------------
// Oracle FFI (gfortran passes every argument by reference; INTEGER is 32-bit;
// each CHARACTER argument adds a hidden trailing length argument of type size_t).
// ---------------------------------------------------------------------------

extern "C" {
    fn transpose_(a: *const f64, at: *mut f64);
    fn determinant_(a: *const f64, det: *mut f64);
    fn vmatmul_(a: *const f64, b: *const f64, n: *const i32, c: *mut f64);
    fn tenf_(v: *const f64, n: *const i32, m: *mut f64);
    #[allow(clippy::too_many_arguments)]
    fn umat_(
        stress: *mut f64,
        statev: *mut f64,
        ddsdde: *mut f64,
        sse: *mut f64,
        spd: *mut f64,
        scd: *mut f64,
        rpl: *mut f64,
        ddsddt: *mut f64,
        drplde: *mut f64,
        drpldt: *mut f64,
        stran: *const f64,
        dstran: *const f64,
        time: *const f64,
        dtime: *const f64,
        temp: *const f64,
        dtemp: *const f64,
        predef: *const f64,
        dpred: *const f64,
        cmname: *const u8,
        ndi: *const i32,
        nshr: *const i32,
        ntens: *const i32,
        nstatv: *const i32,
        props: *const f64,
        nprops: *const i32,
        coords: *const f64,
        drot: *const f64,
        pnewdt: *mut f64,
        celent: *const f64,
        dfgrd0: *const f64,
        dfgrd1: *mut f64,
        noel: *const i32,
        npt: *const i32,
        layer: *const i32,
        kspt: *const i32,
        jstep: *const i32,
        kinc: *const i32,
        cmname_len: usize,
    );
}

fn oracle_transpose(a: &Mat3) -> Mat3 {
    let mut at = [SENTINEL; 9];
    // SAFETY: TRANSPOSE reads A(3,3) and writes AT(3,3); both buffers hold 9 f64.
    unsafe { transpose_(a.as_ptr(), at.as_mut_ptr()) };
    at
}

fn oracle_determinant(a: &Mat3) -> f64 {
    let mut det = SENTINEL;
    // SAFETY: DETERMINANT reads A(3,3) (9 f64) and writes one f64 to DET.
    unsafe { determinant_(a.as_ptr(), &mut det) };
    det
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

/// Calls the Fortran oracle with `N = v.len()`.
fn oracle_tenf(v: &[f64]) -> Mat3 {
    // TENF reads V(1..4) unconditionally and V(5..6) only when N == 6.
    assert!(v.len() >= 4, "oracle needs N >= 4");
    let n = i32::try_from(v.len()).expect("N fits in INTEGER*4");
    let mut m = [SENTINEL; 9];
    // SAFETY: reads stay within V(1..min(N,6)) and `v` holds N >= 4 values;
    // M(3,3) is a 9-element buffer.
    unsafe { tenf_(v.as_ptr(), &n, m.as_mut_ptr()) };
    m
}

/// Everything the Fortran UMAT writes, plus `DFGRD1` after the call.
struct OracleUmat {
    stress: Vec<f64>,
    ddsdde: Vec<f64>,
    statev: Vec<f64>,
    dfgrd1_after: Mat3,
}

fn oracle_umat(f: &Mat3, ntens: usize, statev_in: &[f64]) -> OracleUmat {
    assert!(ntens == 4 || ntens == 6, "oracle needs NTENS 4 or 6");
    assert!(statev_in.len() >= 12, "oracle needs NSTATV >= 12");
    let mut stress = vec![SENTINEL; ntens];
    let mut ddsdde = vec![SENTINEL; ntens * ntens];
    let mut statev = statev_in.to_vec();
    let (mut sse, mut spd, mut scd, mut rpl, mut drpldt, mut pnewdt) =
        (0.0, 0.0, 0.0, 0.0, 0.0, 1.0);
    let mut ddsddt = vec![0.0; ntens];
    let mut drplde = vec![0.0; ntens];
    let stran = vec![0.0; ntens];
    let dstran = vec![0.0; ntens];
    let time = [0.0; 2];
    let (dtime, temp, dtemp, celent) = (1.0, 0.0, 0.0, 1.0);
    let predef = [0.0; 1];
    let dpred = [0.0; 1];
    let cmname = [b' '; 80];
    let ndi: i32 = 3;
    let nshr = i32::try_from(ntens - 3).expect("small");
    let ntens_i = i32::try_from(ntens).expect("small");
    let nstatv = i32::try_from(statev.len()).expect("small");
    let props = [0.0; 1];
    let nprops: i32 = 1;
    let coords = [0.0; 3];
    let drot = I3;
    let dfgrd0 = I3;
    let mut dfgrd1 = *f;
    let (noel, npt, layer, kspt, kinc): (i32, i32, i32, i32, i32) = (1, 1, 1, 1, 1);
    let jstep: [i32; 4] = [1, 0, 0, 0];
    // SAFETY: every array argument points to a live buffer at least as large as
    // its Fortran dimension: STRESS/DDSDDT/DRPLDE/STRAN/DSTRAN(NTENS),
    // DDSDDE(NTENS,NTENS), STATEV(NSTATV), TIME(2), PREDEF(1), DPRED(1),
    // PROPS(NPROPS=1), COORDS(3), DROT/DFGRD0/DFGRD1(3,3), JSTEP(4). NTENS is 4 or 6
    // and NSTATV >= 12 (asserted), which keeps UMAT's internal indexing in bounds.
    // CMNAME is 80 bytes with its hidden length passed last. Scalars are locals
    // that outlive the call; the routine keeps no pointers.
    unsafe {
        umat_(
            stress.as_mut_ptr(),
            statev.as_mut_ptr(),
            ddsdde.as_mut_ptr(),
            &mut sse,
            &mut spd,
            &mut scd,
            &mut rpl,
            ddsddt.as_mut_ptr(),
            drplde.as_mut_ptr(),
            &mut drpldt,
            stran.as_ptr(),
            dstran.as_ptr(),
            time.as_ptr(),
            &dtime,
            &temp,
            &dtemp,
            predef.as_ptr(),
            dpred.as_ptr(),
            cmname.as_ptr(),
            &ndi,
            &nshr,
            &ntens_i,
            &nstatv,
            props.as_ptr(),
            &nprops,
            coords.as_ptr(),
            drot.as_ptr(),
            &mut pnewdt,
            &celent,
            dfgrd0.as_ptr(),
            dfgrd1.as_mut_ptr(),
            &noel,
            &npt,
            &layer,
            &kspt,
            jstep.as_ptr(),
            &kinc,
            cmname.len(),
        );
    }
    OracleUmat {
        stress,
        ddsdde,
        statev,
        dfgrd1_after: dfgrd1,
    }
}

// ---------------------------------------------------------------------------
// Harness helpers
// ---------------------------------------------------------------------------

fn json_num(x: f64) -> String {
    if x.is_finite() {
        format!("{x:?}")
    } else {
        format!("\"{x}\"")
    }
}

fn json_arr(xs: &[f64]) -> String {
    let parts: Vec<String> = xs.iter().map(|&x| json_num(x)).collect();
    format!("[{}]", parts.join(","))
}

/// Builds the structured failure consumed by the orchestrator's self-heal step.
fn mismatch(
    routine: &str,
    entry: &str,
    rust: f64,
    oracle: f64,
    tol: f64,
    inputs: &[(&str, &[f64])],
) -> TestCaseError {
    let inputs: Vec<String> = inputs
        .iter()
        .map(|(k, v)| format!("\"{k}\":{}", json_arr(v)))
        .collect();
    TestCaseError::fail(format!(
        "NECRO_COUNTEREXAMPLE {{\"routine\":\"{routine}\",\"entry\":\"{entry}\",\"rust\":{},\"oracle\":{},\"tol\":{},\"inputs\":{{{}}}}}",
        json_num(rust),
        json_num(oracle),
        json_num(tol),
        inputs.join(",")
    ))
}

/// `|rust - oracle| <= tol`, with both values required to be finite.
fn close(rust: f64, oracle: f64, tol: f64) -> bool {
    rust.is_finite() && oracle.is_finite() && (rust - oracle).abs() <= tol
}

fn runner() -> TestRunner {
    TestRunner::new(Config {
        cases: CASES,
        max_global_rejects: 8 * CASES,
        failure_persistence: None,
        ..Config::default()
    })
}

/// Runs one property for [`CASES`] cases and reports the count. On failure the
/// panic message carries the shrunk counterexample.
fn run_property<S>(name: &str, strategy: S, test: impl Fn(S::Value) -> Result<(), TestCaseError>)
where
    S: Strategy,
    S::Value: Debug,
{
    let cases = Cell::new(0u32);
    let result = runner().run(&strategy, |v| {
        cases.set(cases.get() + 1);
        test(v)
    });
    match result {
        Ok(()) => {}
        Err(TestError::Fail(reason, value)) => panic!(
            "{name} FAILED (after {} evaluations incl. shrinking)\n{reason}\nminimal failing input: {value:?}",
            cases.get()
        ),
        Err(TestError::Abort(reason)) => panic!("{name} aborted: {reason}"),
    }
    let n = cases.get();
    println!("{name}: {n} cases passed");
    assert!(n >= CASES, "only {n} cases ran");
}

/// Bounded, finite matrix entries (no NaN / Inf).
fn mat3(lo: f64, hi: f64) -> impl Strategy<Value = Mat3> {
    prop::array::uniform9(lo..hi)
}

/// Deformation gradient `F = I + H` with `det(F)` in `[0.5, 2.0]`.
fn deformation_gradient() -> impl Strategy<Value = Mat3> {
    prop_oneof![mat3(-0.15, 0.15), mat3(-0.45, 0.45)]
        .prop_map(|h| {
            let mut f = h;
            for i in 0..3 {
                f[i + 3 * i] += 1.0;
            }
            f
        })
        .prop_filter("det(F) in [0.5, 2.0]", |f| {
            let d = determinant(f);
            (0.5..=2.0).contains(&d)
        })
}

fn entry2(name: &str, i: usize, j: usize) -> String {
    format!("{name}({i},{j})")
}

// ---------------------------------------------------------------------------
// TRANSPOSE
// ---------------------------------------------------------------------------

#[test]
fn transpose_matches_oracle() {
    run_property("transpose_matches_oracle", mat3(-1.0e3, 1.0e3), |a| {
        let rust = transpose(&a);
        let fort = oracle_transpose(&a);
        for k in 0..9 {
            // Pure data movement: must be bit-identical.
            if rust[k].to_bits() != fort[k].to_bits() {
                return Err(mismatch(
                    "TRANSPOSE",
                    &entry2("AT", k % 3 + 1, k / 3 + 1),
                    rust[k],
                    fort[k],
                    0.0,
                    &[("A", &a)],
                ));
            }
        }
        Ok(())
    });
}

// ---------------------------------------------------------------------------
// DETERMINANT
// ---------------------------------------------------------------------------

/// Forward error bound for the 6-term cofactor sum of triple products:
/// `16 * EPS * sum |a*b*c|`.
fn det_tol(a: &Mat3) -> f64 {
    let b = a.map(f64::abs);
    let at = |i: usize, j: usize| b[(i - 1) + 3 * (j - 1)];
    let s = at(1, 1) * at(2, 2) * at(3, 3)
        + at(1, 1) * at(2, 3) * at(3, 2)
        + at(2, 1) * at(1, 2) * at(3, 3)
        + at(2, 1) * at(1, 3) * at(3, 2)
        + at(3, 1) * at(1, 2) * at(2, 3)
        + at(3, 1) * at(1, 3) * at(2, 2);
    16.0 * f64::EPSILON * s + f64::MIN_POSITIVE
}

fn check_determinant(a: &Mat3) -> Result<(), TestCaseError> {
    let rust = determinant(a);
    let fort = oracle_determinant(a);
    let tol = det_tol(a);
    if !close(rust, fort, tol) {
        return Err(mismatch("DETERMINANT", "DET", rust, fort, tol, &[("A", a)]));
    }
    Ok(())
}

#[test]
fn determinant_matches_oracle_general() {
    run_property(
        "determinant_matches_oracle_general",
        mat3(-1.0e3, 1.0e3),
        |a| check_determinant(&a),
    );
}

#[test]
fn determinant_matches_oracle_near_singular() {
    // Third column = alpha*col1 + beta*col2 + tiny noise: heavy cancellation, so
    // any change in evaluation order shows up immediately.
    let strategy = (
        mat3(-10.0, 10.0),
        -2.0..2.0f64,
        -2.0..2.0f64,
        prop::array::uniform3(-1.0e-9..1.0e-9f64),
    );
    run_property(
        "determinant_matches_oracle_near_singular",
        strategy,
        |(m, alpha, beta, noise)| {
            let mut a = m;
            for i in 0..3 {
                a[i + 6] = alpha * a[i] + beta * a[i + 3] + noise[i];
            }
            check_determinant(&a)
        },
    );
}

// ---------------------------------------------------------------------------
// VMATMUL
// ---------------------------------------------------------------------------

/// Indices of C (0-based) that VMATMUL writes for a given N.
fn vmatmul_writes(n: usize, k: usize) -> bool {
    k < 4 || (n == 6 && k < 6)
}

/// Written entries must agree within the forward error bound of a 3-term dot
/// product, `8 * EPS * sum_k |A(i,k)| * |B(k,j)|` (computed with the same routine on
/// |A|, |B|). Unwritten entries must still hold the sentinel bit pattern in both.
fn check_vmatmul(a: &Mat3, b: &Mat3, n: usize) -> Result<(), TestCaseError> {
    let mut rust = vec![SENTINEL; n];
    let mut fort = vec![SENTINEL; n];
    vmatmul(a, b, &mut rust).map_err(|e| TestCaseError::fail(e.to_string()))?;
    oracle_vmatmul(a, b, &mut fort);

    let abs_a: Mat3 = a.map(f64::abs);
    let abs_b: Mat3 = b.map(f64::abs);
    let mut scale = vec![0.0; n];
    vmatmul(&abs_a, &abs_b, &mut scale).map_err(|e| TestCaseError::fail(e.to_string()))?;

    let n_f = [n as f64];
    let inputs: [(&str, &[f64]); 3] = [("A", a), ("B", b), ("N", &n_f)];
    for k in 0..n {
        let entry = format!("C({})", k + 1);
        if vmatmul_writes(n, k) {
            let tol = 8.0 * f64::EPSILON * scale[k] + f64::MIN_POSITIVE;
            if !close(rust[k], fort[k], tol) {
                return Err(mismatch("VMATMUL", &entry, rust[k], fort[k], tol, &inputs));
            }
        } else if rust[k].to_bits() != SENTINEL.to_bits() || fort[k].to_bits() != SENTINEL.to_bits()
        {
            return Err(mismatch("VMATMUL", &entry, rust[k], fort[k], 0.0, &inputs));
        }
    }
    Ok(())
}

#[test]
fn vmatmul_matches_oracle_general() {
    run_property(
        "vmatmul_matches_oracle_general",
        (mat3(-1.0e3, 1.0e3), mat3(-1.0e3, 1.0e3), 4usize..=8),
        |(a, b, n)| check_vmatmul(&a, &b, n),
    );
}

#[test]
fn vmatmul_matches_oracle_left_cauchy_green() {
    // UMAT usage: BVEC = VMATMUL(F, F^T) with F = I + H near identity.
    run_property(
        "vmatmul_matches_oracle_left_cauchy_green",
        (mat3(-0.5, 0.5), prop_oneof![Just(4usize), Just(6usize)]),
        |(h, n)| {
            let mut f = h;
            for i in 0..3 {
                f[i + 3 * i] += 1.0;
            }
            let ft = transpose(&f);
            check_vmatmul(&f, &ft, n)?;
            let mut bvec = vec![0.0; n];
            vmatmul(&f, &ft, &mut bvec).map_err(|e| TestCaseError::fail(e.to_string()))?;
            for (k, v) in bvec.iter().take(3).enumerate() {
                prop_assert!(*v >= 0.0, "diagonal b({0},{0}) = {1:e} < 0", k + 1, v);
            }
            Ok(())
        },
    );
}

// ---------------------------------------------------------------------------
// TENF
// ---------------------------------------------------------------------------

#[test]
fn tenf_matches_oracle() {
    run_property(
        "tenf_matches_oracle",
        (4usize..=8).prop_flat_map(|n| prop::collection::vec(-1.0e3..1.0e3f64, n)),
        |v| {
            let rust = tenf(&v).map_err(|e| TestCaseError::fail(e.to_string()))?;
            let fort = oracle_tenf(&v);
            for k in 0..9 {
                // Pure data movement (or literal zero): must be bit-identical, and the
                // oracle must have written all nine entries.
                if rust[k].to_bits() != fort[k].to_bits() {
                    return Err(mismatch(
                        "TENF",
                        &entry2("M", k % 3 + 1, k / 3 + 1),
                        rust[k],
                        fort[k],
                        0.0,
                        &[("V", &v)],
                    ));
                }
            }
            Ok(())
        },
    );
}

// ---------------------------------------------------------------------------
// UMAT
// ---------------------------------------------------------------------------

/// Physically meaningful `STATEV` for BioUMAT, padded with arbitrary filler that
/// UMAT must leave untouched.
fn bioumat_statev() -> impl Strategy<Value = Vec<f64>> {
    (
        prop_oneof![Just(1.0f64), Just(2.0), Just(5.0)], // STATEV(1) material type
        0.3..0.9f64,                                     // STATEV(2) RH
        0.05..0.3f64,                                    // STATEV(3) NS0
        0.0..std::f64::consts::FRAC_PI_2,                // fibril angle -> STATEV(4), (5)
        -0.3..0.3f64,                                    // STATEV(6)
        0.005..0.06f64,                                  // STATEV(8) ALPHA1
        12usize..=16,                                    // NSTATV
        prop::collection::vec(-10.0..10.0f64, 16),       // filler
    )
        .prop_map(|(kind, rh, ns0, phi, s6, alpha1, nstatv, filler)| {
            let mut s = filler;
            s.truncate(nstatv);
            s[0] = kind;
            s[1] = rh;
            s[2] = ns0;
            s[3] = phi.sin();
            s[4] = phi.cos();
            s[5] = s6;
            s[7] = alpha1;
            s
        })
}

#[test]
fn umat_matches_oracle() {
    // (bit-identical entries, compared entries) across STRESS, DDSDDE and STATEV.
    let tally = Cell::new((0u64, 0u64));
    let count = |r: f64, o: f64| {
        let (same, total) = tally.get();
        tally.set((same + u64::from(r.to_bits() == o.to_bits()), total + 1));
    };
    run_property(
        "umat_matches_oracle",
        (
            deformation_gradient(),
            prop_oneof![Just(4usize), Just(6usize)],
            bioumat_statev(),
        ),
        |(f, ntens, statev)| {
            let mut state = UmatState::new(ntens, statev.clone())
                .map_err(|e| TestCaseError::fail(e.to_string()))?;
            umat(&f, &mut state).map_err(|e| TestCaseError::fail(e.to_string()))?;
            let fort = oracle_umat(&f, ntens, &statev);

            let ntens_f = [ntens as f64];
            let inputs: [(&str, &[f64]); 3] =
                [("DFGRD1", &f), ("NTENS", &ntens_f), ("STATEV", &statev)];

            // Tolerances: both sides run the same operations in the same order
            // through the same libm (log, pow), so results are expected to be
            // bit-identical. The bound allows 64 ULP of the stress magnitude for
            // the stress, and the same absolute error amplified by the
            // forward-difference factor 2/EP for DDSDDE.
            let s_scale = 1.0 + fort.stress.iter().fold(0.0f64, |m, x| m.max(x.abs()));
            let tol_s = 64.0 * f64::EPSILON * s_scale;
            let tol_d = tol_s * 2.0 / oracle_harness::UMAT_PERTURBATION;

            for k in 0..ntens {
                count(state.stress[k], fort.stress[k]);
                if !close(state.stress[k], fort.stress[k], tol_s) {
                    let e = format!("STRESS({})", k + 1);
                    return Err(mismatch(
                        "UMAT",
                        &e,
                        state.stress[k],
                        fort.stress[k],
                        tol_s,
                        &inputs,
                    ));
                }
            }
            for c in 0..ntens {
                for r in 0..ntens {
                    let k = r + ntens * c;
                    count(state.ddsdde[k], fort.ddsdde[k]);
                    if !close(state.ddsdde[k], fort.ddsdde[k], tol_d) {
                        let e = entry2("DDSDDE", r + 1, c + 1);
                        return Err(mismatch(
                            "UMAT",
                            &e,
                            state.ddsdde[k],
                            fort.ddsdde[k],
                            tol_d,
                            &inputs,
                        ));
                    }
                }
            }
            for (k, s_in) in statev.iter().enumerate() {
                let e = format!("STATEV({})", k + 1);
                let (r, o) = (state.statev[k], fort.statev[k]);
                count(r, o);
                if (9..12).contains(&k) {
                    if !close(r, o, tol_s) {
                        return Err(mismatch("UMAT", &e, r, o, tol_s, &inputs));
                    }
                } else if r.to_bits() != o.to_bits() || r.to_bits() != s_in.to_bits() {
                    // Entries UMAT does not write must survive unchanged.
                    return Err(mismatch("UMAT", &e, r, o, 0.0, &inputs));
                }
            }
            // The original perturbs DFGRD1 in place; it must restore it exactly.
            prop_assert_eq!(fort.dfgrd1_after.map(f64::to_bits), f.map(f64::to_bits));
            Ok(())
        },
    );
    let (same, total) = tally.get();
    println!("umat_matches_oracle: bit-identical {same}/{total} output entries");
}

#[test]
fn oracle_is_linked_and_sane() {
    let mut c = [SENTINEL; 6];
    oracle_vmatmul(&I3, &I3, &mut c);
    assert_eq!(c, [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]);
    assert_eq!(oracle_determinant(&I3), 1.0);
    assert_eq!(oracle_transpose(&I3), I3);
    assert_eq!(oracle_tenf(&[1.0, 1.0, 1.0, 0.0]), I3);
}
