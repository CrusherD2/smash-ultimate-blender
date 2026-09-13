// SPDX-License-Identifier: GPL-2.0-or-later
// Rust adaptation of Blender v4.5.0 intern/iksolver:
// IK_QJacobianSolver.cpp, IK_QJacobian.cpp, IK_QSegment.cpp, IK_QTask.cpp.
// Original algorithm: Copyright 2001-2002 NaN Holding BV / Blender Authors.
// Restricted probe: serial chains, spherical joints, one position task,
// pole constraint, no locks, limits, stiffness, or translational DoFs.
use crate::math::*;
use serde::{Deserialize, Serialize};

#[derive(Clone, Deserialize)]
pub struct Segment {
    pub start: V,
    pub rest: M,
    pub basis: M,
    pub length: f64,
}
#[derive(Clone, Deserialize)]
pub struct Job {
    pub id: String,
    pub segments: Vec<Segment>,
    pub goal: V,
    pub pole: V,
    pub angle: f64,
    pub iterations: usize,
    #[serde(default)]
    pub backend: crate::math::Backend,
}
#[derive(Clone, Serialize)]
pub struct Output {
    pub id: String,
    pub changes: Vec<[[f32; 3]; 3]>,
    pub iterations: usize,
    pub residual: f64,
    pub converged: bool,
}

fn transforms(segments: &[Segment], root: M) -> (Vec<V>, Vec<M>, V) {
    let mut starts = Vec::with_capacity(segments.len());
    let mut rotations = Vec::with_capacity(segments.len());
    let mut rot = root;
    let mut end = [0.; 3];
    for s in segments {
        let start = add(end, mv(rot, s.start));
        rot = mm(mm(rot, s.rest), s.basis);
        end = add(start, mv(rot, [0., s.length, 0.]));
        starts.push(start);
        rotations.push(rot);
    }
    (starts, rotations, end)
}

/// Reject ill-conditioned starting geometry before using the native fast path.
/// This threshold only selects Blender fallback; it never relaxes equality.
pub(crate) fn fast_geometry(job: &Job) -> bool {
    if job.segments.len() != 2 {
        return false;
    }
    let (starts, rotations, end) = transforms(&job.segments, I);
    let separated = |a: V, b: V| {
        let product = dot(a, a) * dot(b, b);
        product.is_finite() && product > 1e-30 && dot(cross(a, b), cross(a, b)) > product * 1e-8
    };
    let direction = sub(end, starts[0]);
    let up = add(
        scale(col(rotations[0], 0), (job.angle as f32).cos() as f64),
        scale(col(rotations[0], 2), (job.angle as f32).sin() as f64),
    );
    separated(sub(starts[1], starts[0]), sub(end, starts[1]))
        && separated(direction, up)
        && separated(sub(job.goal, starts[0]), sub(job.pole, starts[0]))
}

fn pole_matrix(segments: &[Segment], goal: V, pole: V, angle: f64) -> M {
    let (starts, rotations, end) = transforms(segments, I);
    let dir = unit(sub(end, starts[0]));
    let up = add(
        // Blender stores m_poleangle as float: C++ selects the float
        // sin/cos overloads before promoting the scalar for Eigen's f64 vector.
        scale(col(rotations[0], 0), (angle as f32).cos() as f64),
        scale(col(rotations[0], 2), (angle as f32).sin() as f64),
    );
    let pole_dir = unit(sub(goal, starts[0]));
    let pole_up = unit(sub(pole, starts[0]));
    let x = unit(cross(dir, up));
    let px = unit(cross(pole_dir, pole_up));
    let mat = [x, cross(x, dir), scale(dir, -1.)];
    let polemat = [px, cross(px, pole_dir), scale(pole_dir, -1.)];
    mm(transpose(polemat), mat)
}

fn sdls(backend: Backend, j: &[V], beta: V) -> Vec<f64> {
    let (u, w, v) = svd(backend, j);
    let norms: Vec<_> = j.iter().map(|&r| norm(r)).collect();
    let mut theta = vec![0.; j.len()];
    let max_change = std::f64::consts::FRAC_PI_4;
    for i in 0..3 {
        if w[i] <= 1e-10 {
            continue;
        }
        let wi = 1. / w[i];
        let uc = col(u, i);
        let alpha = dot(uc, beta) * wi;
        let n = norm(uc);
        let mut m = 0.;
        let mut maximum: f64 = 0.;
        for k in 0..j.len() {
            m += v[k][i].abs() * norms[k];
            maximum = maximum.max((v[k][i] * alpha).abs());
        }
        m *= wi;
        let gamma = if n < m {
            max_change * (n / m)
        } else {
            max_change
        };
        let damp = if gamma < maximum { gamma / maximum } else { 1. };
        for k in 0..j.len() {
            theta[k] += 0.80 * damp.min(1.) * (v[k][i] * alpha);
        }
    }
    let maximum = theta.iter().fold(0f64, |a, v| a.max(v.abs()));
    if maximum > max_change {
        let damp = max_change / (max_change + maximum);
        for v in &mut theta {
            *v *= damp;
        }
    }
    theta
}

pub fn solve(job: &Job) -> Output {
    assert!(!job.segments.is_empty() && job.segments.len() <= 16);
    assert!(job.iterations > 0 && job.iterations <= 10000);
    let total = job
        .segments
        .iter()
        .map(|s| norm(s.start) + s.length)
        .sum::<f64>();
    let scale = if total == 0. {
        1.
    } else {
        (1. / total) as f32 as f64
    };
    let mut segments = job.segments.clone();
    for s in &mut segments {
        s.start = crate::math::scale(s.start, scale);
        s.length *= scale;
    }
    let goal = crate::math::scale(job.goal, scale);
    let pole = crate::math::scale(job.pole, scale);
    let root = pole_matrix(&segments, goal, pole, job.angle as f32 as f64);
    let clamp = total / (2. * segments.len() as f64) * scale;
    let mut count = 0;
    let mut converged = false;
    for iteration in 0..job.iterations {
        let (starts, rotations, end) = transforms(&segments, root);
        let mut beta = sub(goal, end);
        let len = norm(beta);
        if len > clamp {
            beta = crate::math::scale(beta, clamp / len);
        }
        let mut j = Vec::with_capacity(segments.len() * 3);
        for i in 0..segments.len() {
            for axis in 0..3 {
                j.push(cross(sub(starts[i], end), col(rotations[i], axis)));
            }
        }
        let theta = sdls(job.backend, &j, beta);
        let mut maximum = 0f64;
        for (i, s) in segments.iter_mut().enumerate() {
            let delta = [theta[i * 3], theta[i * 3 + 1], theta[i * 3 + 2]];
            maximum = maximum.max(delta.iter().fold(0f64, |a, x| a.max(x.abs())));
            s.basis = mm(s.basis, rodrigues(delta));
        }
        count = iteration + 1;
        if maximum < 1e-3 && iteration > 10 {
            converged = true;
            break;
        }
    }
    segments[0].basis = mm(
        mm(mm(inverse(segments[0].rest), root), segments[0].rest),
        segments[0].basis,
    );
    let changes = segments
        .iter()
        .zip(&job.segments)
        .map(|(s, initial)| mm(transpose(initial.basis), s.basis).map(|r| r.map(|v| v as f32)))
        .collect();
    let (_, _, end) = transforms(&segments, I);
    Output {
        id: job.id.clone(),
        changes,
        iterations: count,
        residual: norm(sub(end, goal)) / scale,
        converged,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reachable_target() {
        let job = Job {
            id: "test".into(),
            backend: crate::math::Backend::Approximate,
            segments: vec![
                Segment {
                    start: [0.; 3],
                    rest: I,
                    basis: rodrigues([0., 0., 0.4]),
                    length: 1.,
                },
                Segment {
                    start: [0.; 3],
                    rest: I,
                    basis: rodrigues([0., 0., -0.8]),
                    length: 1.,
                },
            ],
            goal: [0., 1.5, 0.],
            pole: [1., 0.5, 0.],
            angle: 0.,
            iterations: 200,
        };
        let out = solve(&job);
        assert!(out.residual < 0.002, "{}", out.residual);
        assert!(out.iterations >= 12);
    }
}
