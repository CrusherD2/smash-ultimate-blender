// SPDX-License-Identifier: GPL-2.0-or-later
// Blender v4.5.0 iksolver_plugin.cc where_is_ik_bone and BLI matrix/vector
// arithmetic. Copyright NaN Holding BV / Blender Authors.
use crate::solver;
use serde::{Deserialize, Serialize};
pub type Mat4 = [[f32; 4]; 4];

#[derive(Clone, Deserialize)]
pub struct Case {
    #[serde(flatten)]
    pub job: solver::Job,
    pub parent: Mat4,
    pub deltas: Vec<Mat4>,
}

#[derive(Serialize)]
pub struct Result {
    #[serde(flatten)]
    pub kernel: solver::Output,
    pub matrices: Vec<Mat4>,
}

pub(crate) fn multiply(a: Mat4, b: Mat4) -> Mat4 {
    std::array::from_fn(|r| {
        std::array::from_fn(|c| {
            (a[r][0] * b[0][c] + a[r][1] * b[1][c]) + (a[r][2] * b[2][c] + a[r][3] * b[3][c])
        })
    })
}

fn length(a: Mat4, c: usize) -> f32 {
    ((a[0][c] * a[0][c] + a[1][c] * a[1][c]) + a[2][c] * a[2][c]).sqrt()
}

fn normalize(a: &mut Mat4, c: usize, target: f32) {
    let squared = (a[0][c] * a[0][c] + a[1][c] * a[1][c]) + a[2][c] * a[2][c];
    let factor = if squared > 1e-35 {
        target / squared.sqrt()
    } else {
        0.0
    };
    for row in a.iter_mut().take(3) {
        row[c] *= factor;
    }
}

pub fn solve(case: &Case) -> Result {
    let kernel = solver::solve(&case.job);
    assert_eq!(case.deltas.len(), kernel.changes.len());
    let mut parent = case.parent;
    let mut matrices = Vec::with_capacity(case.deltas.len());
    for (delta, change) in case.deltas.iter().zip(&kernel.changes) {
        let mut matrix = multiply(parent, *delta);
        let scales = [length(matrix, 0), length(matrix, 1), length(matrix, 2)];
        for axis in [0, 2] {
            normalize(&mut matrix, axis, scales[1]);
        }
        let mut rotation = [[0.0; 4]; 4];
        for r in 0..3 {
            rotation[r][..3].copy_from_slice(&change[r]);
        }
        rotation[3][3] = 1.0;
        matrix = multiply(matrix, rotation);
        for axis in [0, 2] {
            normalize(&mut matrix, axis, scales[axis] * length(rotation, axis));
        }
        matrices.push(matrix);
        parent = matrix;
    }
    Result { kernel, matrices }
}

/// Restrict the accelerator to Blender's minimum twelve-iteration solve.
/// Longer/unstable trajectories use Blender, without accepting an approximate
/// matrix. The diagnostic CLI still supports the full iteration count.
pub fn solve_fast(case: &Case) -> Result {
    let mut fast = case.clone();
    fast.job.iterations = fast.job.iterations.min(12);
    let mut result = solve(&fast);
    result.kernel.converged &= solver::fast_geometry(&case.job);
    result
}

/// Reference columns for one bone: four columns of four float32 components,
/// exactly the layout `matrix.col[i]` produces in mathutils.
pub type Columns = [[f32; 4]; 4];

/// Score one solved chain against the FK reference.
///
/// This has to reproduce `Vector.length_squared` exactly, because the score
/// decides which candidate angle wins. mathutils reaches it through
/// `len_squared_vn`, which squares each component in float32 and then
/// accumulates in double **iterating from the last component to the first**:
///
/// ```c
/// double len_squared_vn(const float *array, int size) {
///   double d = 0.0f;
///   const float *array_end = array + size;
///   while (array != array_end) { d += (double)square_f(*(--array_end)); }
///   return d;
/// }
/// ```
///
/// Accumulating the squares in float32, or running forwards, rounds
/// differently. On a rig with large coordinates that was enough to pick a
/// different angle on 9 of 157 frames.
fn score(matrices: &[Mat4], reference: &[Columns]) -> f64 {
    let mut total = 0.0f64;
    for (matrix, columns) in matrices.iter().zip(reference.iter()) {
        let mut bone = 0.0f64;
        for i in 0..4 {
            let mut squared = 0.0f64;
            for r in (0..4).rev() {
                let d = matrix[r][i] - columns[i][r];
                squared += (d * d) as f64;
            }
            bone += squared;
        }
        total += bone;
    }
    total
}

/// The pole search from `ik_channels._match_chain_steps`, moved beside the
/// solver so a chain costs one call per frame rather than one per candidate.
///
/// Returns `None` when any evaluated candidate fails to converge or the
/// geometry guard rejects it, which is the same condition that makes the
/// per-candidate path fall back to Blender. The caller must then run the
/// Python search unchanged.
pub fn search(
    case: &mut Case,
    reference: &[Columns],
    seeds: [f64; 3],
    tolerance: f64,
    refine_steps: usize,
) -> Option<(f64, Vec<Mat4>)> {
    if reference.len() != case.deltas.len() {
        return None;
    }
    // Keyed on the unrounded angle, as the Python memo is.
    let mut memo: Vec<(f64, f64)> = Vec::new();
    let mut converged = true;

    fn evaluate(
        case: &mut Case,
        memo: &mut Vec<(f64, f64)>,
        converged: &mut bool,
        reference: &[Columns],
        angle: f64,
    ) -> f64 {
        if let Some(&(_, cached)) = memo.iter().find(|(a, _)| *a == angle) {
            return cached;
        }
        // Blender stores pole_angle as a float property, so the solver sees a
        // float32 value however precisely the search computed it.
        let rounded = angle.sin().atan2(angle.cos()) as f32;
        case.job.angle = rounded as f64;
        let result = solve_fast(case);
        if !result.kernel.converged
            || result
                .matrices
                .iter()
                .flatten()
                .flatten()
                .any(|v| !v.is_finite())
        {
            *converged = false;
        }
        let value = score(&result.matrices, reference);
        memo.push((angle, value));
        value
    }

    // Python's min() returns the first of equal scores, so compare strictly.
    fn pick(
        case: &mut Case,
        memo: &mut Vec<(f64, f64)>,
        converged: &mut bool,
        reference: &[Columns],
        candidates: &[f64],
    ) -> f64 {
        let mut best = candidates[0];
        let mut best_score = evaluate(case, memo, converged, reference, candidates[0]);
        for &candidate in &candidates[1..] {
            let value = evaluate(case, memo, converged, reference, candidate);
            if value < best_score {
                best = candidate;
                best_score = value;
            }
        }
        best
    }

    let mut angle = pick(case, &mut memo, &mut converged, reference, &seeds);
    if evaluate(case, &mut memo, &mut converged, reference, angle) > tolerance {
        let (mut lo, mut hi) = (angle - 0.2, angle + 0.2);
        let ratio = (5.0_f64.sqrt() - 1.0) * 0.5;
        let (mut a, mut b) = (hi - ratio * (hi - lo), lo + ratio * (hi - lo));
        let mut fa = evaluate(case, &mut memo, &mut converged, reference, a);
        let mut fb = evaluate(case, &mut memo, &mut converged, reference, b);
        for _ in 0..refine_steps {
            if fa < fb {
                hi = b;
                b = a;
                fb = fa;
                a = hi - ratio * (hi - lo);
                fa = evaluate(case, &mut memo, &mut converged, reference, a);
            } else {
                lo = a;
                a = b;
                fa = fb;
                b = lo + ratio * (hi - lo);
                fb = evaluate(case, &mut memo, &mut converged, reference, b);
            }
        }
        angle = pick(case, &mut memo, &mut converged, reference, &[angle, a, b]);
    }
    if !converged {
        return None;
    }
    let rounded = angle.sin().atan2(angle.cos()) as f32;
    case.job.angle = rounded as f64;
    let result = solve_fast(case);
    if !result.kernel.converged {
        return None;
    }
    Some((angle, result.matrices))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::math::{rodrigues, I};
    use crate::solver::{Job, Segment};

    fn case() -> Case {
        let identity: Mat4 = [
            [1., 0., 0., 0.],
            [0., 1., 0., 0.],
            [0., 0., 1., 0.],
            [0., 0., 0., 1.],
        ];
        Case {
            job: Job {
                id: "test".into(),
                backend: crate::math::Backend::Approximate,
                segments: vec![
                    Segment { start: [0.; 3], rest: I, basis: rodrigues([0., 0., 0.4]), length: 1. },
                    Segment { start: [0.; 3], rest: I, basis: rodrigues([0., 0., -0.7]), length: 1. },
                ],
                goal: [0.9, 1.2, 0.1],
                pole: [0.4, 0.6, 1.5],
                angle: 0.0,
                iterations: 12,
            },
            parent: identity,
            deltas: vec![identity, identity],
        }
    }

    fn columns_at(case: &mut Case, angle: f64) -> Vec<Columns> {
        case.job.angle = (angle.sin().atan2(angle.cos()) as f32) as f64;
        let result = solve_fast(case);
        result
            .matrices
            .iter()
            .map(|m| std::array::from_fn(|c| std::array::from_fn(|r| m[r][c])))
            .collect()
    }

    #[test]
    fn search_recovers_the_angle_its_reference_was_built_from() {
        let mut subject = case();
        let target = 0.35_f64;
        let reference = columns_at(&mut subject, target);
        let (angle, _) = search(&mut subject, &reference, [target, -target, 0.0], 1e-9, 12)
            .expect("the reachable case should converge");
        assert!((angle - target).abs() < 1e-6, "{angle} vs {target}");
    }

    #[test]
    fn search_ties_take_the_first_candidate() {
        let mut subject = case();
        let reference = columns_at(&mut subject, 0.0);
        // Identical seeds and a tolerance nothing can exceed: the refinement
        // never runs and the first candidate must survive unchanged, which is
        // what Python's min() does on equal scores.
        let (angle, _) = search(&mut subject, &reference, [0.25, 0.25, 0.25], f64::INFINITY, 12)
            .expect("the reachable case should converge");
        assert_eq!(angle, 0.25);
    }

    #[test]
    fn search_rejects_a_mismatched_reference_length() {
        let mut subject = case();
        assert!(search(&mut subject, &[], [0., 0., 0.], 1e-9, 12).is_none());
    }
}
