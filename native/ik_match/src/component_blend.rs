// SPDX-FileCopyrightText: Blender Authors
// SPDX-License-Identifier: GPL-2.0-or-later
//! Polar matrix interpolation following Blender math_matrix/math_rotation.
//! SVD uses the existing independent Jacobi implementation, not Blender callbacks.
use crate::component_math::{det, identity, Mat};
fn polar(m: Mat) -> Option<(Mat, Mat)> {
    let columns: Vec<[f64; 3]> = (0..3)
        .map(|c| std::array::from_fn(|r| m[r][c] as f64))
        .collect();
    let (u, s, v) = crate::math::approximate_svd(&columns);
    if s.iter().any(|v| !v.is_finite() || *v < 1e-20) {
        return None;
    }
    let mut rotation = identity();
    let mut stretch = identity();
    for r in 0..3 {
        for c in 0..3 {
            rotation[r][c] = (0..3).map(|k| u[r][k] * v[c][k]).sum::<f64>() as f32;
            stretch[r][c] = (0..3).map(|k| v[r][k] * s[k] * v[c][k]).sum::<f64>() as f32;
        }
    }
    if det(rotation) < 0.0 {
        for r in 0..3 {
            for c in 0..3 {
                rotation[r][c] = -rotation[r][c];
                stretch[r][c] = -stretch[r][c];
            }
        }
    }
    Some((rotation, stretch))
}
fn quaternion(m: Mat) -> [f32; 4] {
    let axis = if m[2][2] < 0.0 {
        if m[0][0] > m[1][1] {
            1
        } else {
            2
        }
    } else if m[0][0] < -m[1][1] {
        3
    } else {
        0
    };
    let mut q = [0.0; 4];
    if axis == 0 {
        let s = 2.0 * ((1.0 + m[0][0] + m[1][1]) + m[2][2]).sqrt();
        q[0] = 0.25 * s;
        q[1] = (m[2][1] - m[1][2]) / s;
        q[2] = (m[0][2] - m[2][0]) / s;
        q[3] = (m[1][0] - m[0][1]) / s;
    } else {
        let i = axis - 1;
        let j = (i + 1) % 3;
        let k = (i + 2) % 3;
        let mut s = 2.0 * ((1.0 + m[i][i] - m[j][j]) - m[k][k]).sqrt();
        if m[k][j] < m[j][k] {
            s = -s;
        }
        q[axis] = 0.25 * s;
        q[0] = (m[k][j] - m[j][k]) / s;
        q[j + 1] = (m[i][j] + m[j][i]) / s;
        q[k + 1] = (m[i][k] + m[k][i]) / s;
    }
    let length = q.iter().map(|v| v * v).sum::<f32>();
    if (length - 1.0).abs() >= 0.0006 {
        let scale = 1.0 / length.sqrt();
        q = q.map(|v| v * scale);
    }
    q
}
fn rotation(q: [f32; 4]) -> Mat {
    let [w, x, y, z] = q.map(|v| v as f64 * std::f64::consts::SQRT_2);
    let mut m = identity();
    m[0][0] = (1.0 - y * y - z * z) as f32;
    m[0][1] = (x * y - w * z) as f32;
    m[0][2] = (x * z + w * y) as f32;
    m[1][0] = (x * y + w * z) as f32;
    m[1][1] = (1.0 - x * x - z * z) as f32;
    m[1][2] = (y * z - w * x) as f32;
    m[2][0] = (x * z - w * y) as f32;
    m[2][1] = (y * z + w * x) as f32;
    m[2][2] = (1.0 - x * x - y * y) as f32;
    m
}
pub fn interpolate(a: Mat, b: Mat, t: f32) -> Option<Mat> {
    let (ra, pa) = polar(a)?;
    let (rb, pb) = polar(b)?;
    let mut qa = quaternion(ra);
    let qb = quaternion(rb);
    let mut cosine = ((qa[0] * qb[0] + qa[1] * qb[1]) + qa[2] * qb[2]) + qa[3] * qb[3];
    if cosine < 0.0 {
        cosine = -cosine;
        qa = qa.map(|v| -v);
    }
    let (wa, wb) = if cosine.abs() < 1.0 - 1e-4 {
        let angle = cosine.acos();
        let sine = angle.sin();
        (((1.0 - t) * angle).sin() / sine, (t * angle).sin() / sine)
    } else {
        (1.0 - t, t)
    };
    let rot = rotation(std::array::from_fn(|i| wa * qa[i] + wb * qb[i]));
    let mut stretch = identity();
    for r in 0..3 {
        for c in 0..3 {
            stretch[r][c] = (1.0 - t) * pa[r][c] + t * pb[r][c];
        }
    }
    let mut out = identity();
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] =
                (rot[r][0] * stretch[0][c] + rot[r][1] * stretch[1][c]) + rot[r][2] * stretch[2][c];
        }
        out[r][3] = (1.0 - t) * a[r][3] + t * b[r][3];
    }
    Some(out)
}
