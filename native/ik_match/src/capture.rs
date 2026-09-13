// SPDX-License-Identifier: GPL-2.0-or-later
// Blender v4.5.0 execute_posetree input conversion. Blender Authors.
use crate::{
    inverse4,
    pose::{self, Mat4},
    solver::{Job, Segment},
};
use serde::Deserialize;
type Mat3 = [[f32; 3]; 3];
type Vec3 = [f32; 3];

#[derive(Deserialize)]
pub struct Input {
    pub parent: Mat4,
    pub poses: Vec<Mat4>,
    pub rests: Vec<Mat3>,
    pub heads: Vec<Vec3>,
    pub tails: Vec<Vec3>,
    pub lengths: Vec<f32>,
    pub object: Mat4,
    pub target: Mat4,
    pub pole: Mat4,
    pub iterations: usize,
    /// Unrecognised values deserialize to Approximate, so a typo in the
    /// environment override cannot silently enable an unverified solver.
    #[serde(default)]
    pub backend: crate::math::Backend,
}
fn dot(a: Vec3, b: Vec3) -> f32 {
    (a[0] * b[0] + a[1] * b[1]) + a[2] * b[2]
}
fn col(a: Mat3, c: usize) -> Vec3 {
    [a[0][c], a[1][c], a[2][c]]
}
fn transpose(a: Mat3) -> Mat3 {
    [col(a, 0), col(a, 1), col(a, 2)]
}
fn mul(a: Mat3, b: Mat3) -> Mat3 {
    std::array::from_fn(|r| std::array::from_fn(|c| dot(a[r], col(b, c))))
}
fn upper(a: Mat4) -> Mat3 {
    std::array::from_fn(|r| std::array::from_fn(|c| a[r][c]))
}
fn normalized(mut a: Mat3) -> Mat3 {
    for c in 0..3 {
        let v = col(a, c);
        let d = dot(v, v);
        let factor = if d > 1e-35 { 1.0 / d.sqrt() } else { 0.0 };
        for row in &mut a {
            row[c] *= factor;
        }
    }
    a
}
fn inverse3(a: Mat3) -> Mat3 {
    let mut adj = [[0.0; 3]; 3];
    for (r, row) in adj.iter_mut().enumerate() {
        for (c, x) in row.iter_mut().enumerate() {
            let rows: Vec<_> = (0..3).filter(|&i| i != c).collect();
            let cols: Vec<_> = (0..3).filter(|&i| i != r).collect();
            *x = (a[rows[0]][cols[0]] * a[rows[1]][cols[1]]
                - a[rows[0]][cols[1]] * a[rows[1]][cols[0]])
                * if (r + c) % 2 == 0 { 1.0 } else { -1.0 };
        }
    }
    let det = (a[0][0] * adj[0][0] + a[0][1] * adj[1][0]) + a[0][2] * adj[2][0];
    assert!(det != 0.0 && det.is_finite());
    let inv = 1.0 / det;
    adj.map(|r| r.map(|v| v * inv))
}

pub fn convert(input: Input) -> pose::Case {
    let n = input.poses.len();
    assert!(n > 0 && n <= 16 && input.iterations > 0 && input.iterations <= 10000);
    assert!([
        input.rests.len(),
        input.heads.len(),
        input.tails.len(),
        input.lengths.len()
    ]
    .iter()
    .all(|&v| v == n));
    let mut segments = Vec::with_capacity(n);
    let mut deltas = Vec::with_capacity(n);
    for i in 0..n {
        let prior = if i == 0 {
            input.parent
        } else {
            input.poses[i - 1]
        };
        let rotation = upper(input.poses[i]);
        let y = col(rotation, 1);
        let length = input.lengths[i] * dot(y, y).sqrt();
        let inverse_parent = inverse3(normalized(upper(prior)));
        let basis = mul(
            transpose(input.rests[i]),
            mul(inverse_parent, normalized(rotation)),
        );
        let start = if i == 0 {
            [0.0; 3]
        } else {
            let diff = std::array::from_fn(|j| input.heads[i][j] - input.tails[i - 1][j]);
            inverse_parent.map(|r| dot(r, diff))
        };
        segments.push(Segment {
            start: start.map(f64::from),
            rest: input.rests[i].map(|r| r.map(f64::from)),
            basis: basis.map(|r| r.map(f64::from)),
            length: length as f64,
        });
        deltas.push(pose::multiply(inverse4::inverse(prior), input.poses[i]));
    }
    let mut root = input.parent;
    let normalized_parent = normalized(upper(root));
    for r in 0..3 {
        root[r][..3].copy_from_slice(&normalized_parent[r]);
        root[r][3] = input.heads[0][r];
    }
    // Only affine object/pose matrices are admitted by the capture adapter.
    assert!(root[3] == [0.0, 0.0, 0.0, 1.0]);
    let goal_inverse = inverse4::inverse(pose::multiply(input.object, root));
    let goal = pose::multiply(goal_inverse, pose::multiply(input.object, input.target));
    let pole = pose::multiply(goal_inverse, pose::multiply(input.object, input.pole));
    pose::Case {
        job: Job {
            id: String::new(),
            segments,
            goal: std::array::from_fn(|i| goal[i][3] as f64),
            pole: std::array::from_fn(|i| pole[i][3] as f64),
            angle: 0.0,
            iterations: input.iterations,
            backend: input.backend,
        },
        parent: input.parent,
        deltas,
    }
}
