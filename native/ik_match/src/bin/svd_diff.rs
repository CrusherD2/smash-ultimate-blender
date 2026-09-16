// SPDX-License-Identifier: GPL-2.0-or-later
//! Runs both SVD backends over inputs captured from a real match and reports
//! the spread. Accuracy layer 1 of the design: pure native, no Blender, so it
//! runs in seconds and localizes a failure the end-to-end suites can only
//! report.
//!
//! A singular value decomposition is unique only up to a simultaneous sign
//! flip of each paired (u_i, v_i) column, so comparing U and V componentwise
//! measures sign convention rather than accuracy. Two quantities are reported
//! instead:
//!
//!   * `theta`, the damped-least-squares step that actually feeds the solve.
//!     `sdls` uses v[k][i] * dot(u_i, beta), which is sign invariant, so any
//!     difference here is real.
//!   * sign-canonicalized U and V, for localizing where a real difference
//!     originates when theta does differ.
use sub_ik_match_native::math::{svd, Backend, M, V};
use sub_ik_match_native::solver::sdls;

#[derive(serde::Deserialize)]
struct Case {
    j: Vec<V>,
    beta: V,
}

/// Flip each paired column so the largest-magnitude entry of u_i is positive.
/// Leaves the decomposition mathematically identical.
fn canonicalize(u: &mut M, v: &mut [V]) {
    for i in 0..3 {
        let mut lead = 0usize;
        for r in 1..3 {
            if u[r][i].abs() > u[lead][i].abs() {
                lead = r;
            }
        }
        if u[lead][i] < 0.0 {
            for r in 0..3 {
                u[r][i] = -u[r][i];
            }
            for row in v.iter_mut() {
                row[i] = -row[i];
            }
        }
    }
}

fn main() {
    let path = std::env::args().nth(1).expect("usage: svd_diff <capture.jsonl>");
    let text = std::fs::read_to_string(&path).expect("capture unreadable");
    let mut count = 0usize;
    let (mut max_u, mut max_w, mut max_v, mut max_theta) = (0f64, 0f64, 0f64, 0f64);
    let mut theta_identical = 0usize;
    let mut svd_identical = 0usize;
    let mut worst_line = 0usize;
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let case: Case = serde_json::from_str(line).expect("malformed capture line");
        let (mut ua, wa, mut va) = svd(Backend::Approximate, &case.j);
        let (mut ue, we, mut ve) = svd(Backend::Eigen, &case.j);
        canonicalize(&mut ua, &mut va);
        canonicalize(&mut ue, &mut ve);
        let mut worst = 0f64;
        for r in 0..3 {
            for c in 0..3 {
                let d = (ua[r][c] - ue[r][c]).abs();
                max_u = max_u.max(d);
                worst = worst.max(d);
            }
            let d = (wa[r] - we[r]).abs();
            max_w = max_w.max(d);
            worst = worst.max(d);
        }
        for (ra, re) in va.iter().zip(ve.iter()) {
            for c in 0..3 {
                let d = (ra[c] - re[c]).abs();
                max_v = max_v.max(d);
                worst = worst.max(d);
            }
        }
        if worst == 0.0 {
            svd_identical += 1;
        }
        let ta = sdls(Backend::Approximate, &case.j, case.beta);
        let te = sdls(Backend::Eigen, &case.j, case.beta);
        let mut theta_delta = 0f64;
        for (a, e) in ta.iter().zip(te.iter()) {
            theta_delta = theta_delta.max((a - e).abs());
        }
        if theta_delta == 0.0 {
            theta_identical += 1;
        }
        if theta_delta > max_theta {
            max_theta = theta_delta;
            worst_line = count;
        }
        count += 1;
    }
    println!(
        "SVD_DIFF cases={count} theta_bit_identical={theta_identical} max_theta={max_theta:e} \
         svd_bit_identical={svd_identical} max_u={max_u:e} max_w={max_w:e} max_v={max_v:e} \
         worst_theta_line={worst_line}"
    );
}
