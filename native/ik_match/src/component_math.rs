// SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.
// SPDX-FileCopyrightText: Blender Authors
// SPDX-License-Identifier: GPL-2.0-or-later
//! Scalar ports of Blender v4.5.0 constraint.cc and BLI math routines.
//! Matrices here are row-major (Blender's C arrays are column-major).
//! Keep float intermediates and explicit operation ordering; no fast-math.
pub type Mat = [[f32; 4]; 4];
pub fn identity() -> Mat {
    std::array::from_fn(|r| std::array::from_fn(|c| if r == c { 1.0 } else { 0.0 }))
}
/// mul_m4_m4m4's SSE2 add tree, also used by the existing IK port.
pub fn mul(a: Mat, b: Mat) -> Mat {
    crate::pose::multiply(a, b)
}
pub fn inverse(a: Mat) -> Option<Mat> {
    // Existing independently tested transcription of Blender's Eigen inverse.
    let determinant = det(a);
    if !determinant.is_finite() || determinant.abs() < 1e-30 {
        return None;
    }
    let result = crate::inverse4::inverse(a);
    result
        .iter()
        .flatten()
        .all(|v| v.is_finite())
        .then_some(result)
}
/// eulO_to_mat3, including double trig followed by float matrix storage.
pub fn euler(e: [f32; 3], order: usize) -> Mat {
    let (axes, parity) = match order {
        1 => ([0, 2, 1], true),
        2 => ([1, 0, 2], true),
        3 => ([1, 2, 0], false),
        4 => ([2, 0, 1], false),
        5 => ([2, 1, 0], true),
        _ => ([0, 1, 2], false),
    };
    let [i, j, k] = axes;
    let sign = if parity { -1.0 } else { 1.0 };
    let (si, ci) = (e[i] as f64 * sign).sin_cos();
    let (sj, cj) = (e[j] as f64 * sign).sin_cos();
    let (sh, ch) = (e[k] as f64 * sign).sin_cos();
    let cc = ci * ch;
    let cs = ci * sh;
    let sc = si * ch;
    let ss = si * sh;
    let mut m = identity();
    m[i][i] = (cj * ch) as f32;
    m[i][j] = (sj * sc - cs) as f32;
    m[i][k] = (sj * cc + ss) as f32;
    m[j][i] = (cj * sh) as f32;
    m[j][j] = (sj * ss + cc) as f32;
    m[j][k] = (sj * cs - sc) as f32;
    m[k][i] = -sj as f32;
    m[k][j] = (cj * si) as f32;
    m[k][k] = (cj * ci) as f32;
    m
}
/// loc_eulO_size_to_mat4's rotation, scale, location assembly.
pub fn trs(v: &[f64]) -> Mat {
    let mut m = euler([v[3] as f32, v[4] as f32, v[5] as f32], 0);
    for r in 0..3 {
        for c in 0..3 {
            m[r][c] *= v[c + 6] as f32;
        }
        m[r][3] = v[r] as f32;
    }
    m
}
fn dot(a: [f32; 3], b: [f32; 3]) -> f32 {
    (a[0] * b[0] + a[1] * b[1]) + a[2] * b[2]
}
fn normalized(a: [f32; 3]) -> ([f32; 3], f32) {
    let d = dot(a, a);
    if d > 1e-35 {
        let length = d.sqrt();
        let f = 1.0 / length;
        (a.map(|v| v * f), length)
    } else {
        ([0.0; 3], 0.0)
    }
}
fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
pub fn det(m: Mat) -> f32 {
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
}
pub fn sizes(m: Mat) -> [f32; 3] {
    std::array::from_fn(|c| dot([m[0][c], m[1][c], m[2][c]], [m[0][c], m[1][c], m[2][c]]).sqrt())
}
/// Blender orthogonalize_m4_stable with bone Y as the primary axis.
pub fn orthogonalize(mut m: Mat, normalize: bool) -> Mat {
    let mut y = [m[0][1], m[1][1], m[2][1]];
    let mut x = [m[0][0], m[1][0], m[2][0]];
    let mut z = [m[0][2], m[1][2], m[2][2]];
    let length = dot(y, y);
    if length > 0.0 {
        let ax = -dot(x, y) / length;
        let az = -dot(z, y) / length;
        for i in 0..3 {
            x[i] += y[i] * ax;
            z[i] += y[i] * az;
        }
        if normalize {
            let factor = 1.0 / length.sqrt();
            y = y.map(|v| v * factor);
        }
    }
    let (mut nx, lx) = normalized(x);
    let (mut nz, lz) = normalized(z);
    let cosine = dot(nx, nz);
    if cosine.abs() > 1e-4 && cosine.abs() < 1.0 - f32::EPSILON {
        let angle = cosine.acos();
        let target = angle + (std::f32::consts::FRAC_PI_2 - angle) / 2.0;
        for i in 0..3 {
            nx[i] += nz[i] * -cosine;
        }
        let factor = target.sin() / dot(nx, nx).sqrt();
        nx = nx.map(|v| v * factor);
        for i in 0..3 {
            nx[i] += nz[i] * target.cos();
        }
        nz = normalized(cross(cross(nx, nz), nx)).0;
        if !normalize {
            let factor = angle.sin().sqrt();
            x = nx.map(|v| v * (lx * factor));
            z = nz.map(|v| v * (lz * factor));
        }
    }
    if normalize {
        x = nx;
        z = nz;
    }
    for r in 0..3 {
        m[r][0] = x[r];
        m[r][1] = y[r];
        m[r][2] = z[r];
    }
    m
}
/// mat3_to_eulO, preserving Blender's alternate-solution and gimbal threshold.
fn euler_pair(mut m: Mat, order: usize) -> ([f32; 3], [f32; 3]) {
    for c in 0..3 {
        let column = normalized([m[0][c], m[1][c], m[2][c]]).0;
        for r in 0..3 {
            m[r][c] = column[r];
        }
    }
    let (axes, parity) = match order {
        1 => ([0, 2, 1], true),
        2 => ([1, 0, 2], true),
        3 => ([1, 2, 0], false),
        4 => ([2, 0, 1], false),
        5 => ([2, 1, 0], true),
        _ => ([0, 1, 2], false),
    };
    let [i, j, k] = axes;
    let cy = m[i][i].hypot(m[j][i]);
    let mut a = [0.0; 3];
    let mut b = [0.0; 3];
    if cy > 0.0000375 {
        a[i] = m[k][j].atan2(m[k][k]);
        a[j] = (-m[k][i]).atan2(cy);
        a[k] = m[j][i].atan2(m[i][i]);
        b[i] = (-m[k][j]).atan2(-m[k][k]);
        b[j] = (-m[k][i]).atan2(-cy);
        b[k] = (-m[j][i]).atan2(-m[i][i]);
    } else {
        a[i] = (-m[j][k]).atan2(m[j][j]);
        a[j] = (-m[k][i]).atan2(cy);
        b = a;
    }
    if parity {
        a = a.map(|v| -v);
        b = b.map(|v| -v);
    }
    (a, b)
}
pub fn to_euler(m: Mat, order: usize) -> [f32; 3] {
    let (a, b) = euler_pair(m, order);
    if a.iter().map(|v| v.abs()).sum::<f32>() > b.iter().map(|v| v.abs()).sum::<f32>() {
        b
    } else {
        a
    }
}
pub fn compatible(mut angles: [f32; 3], old: [f32; 3]) -> [f32; 3] {
    let tau = 2.0 * std::f32::consts::PI;
    let mut delta = [0.0; 3];
    for i in 0..3 {
        delta[i] = angles[i] - old[i];
        if delta[i] > std::f32::consts::PI {
            angles[i] -= (delta[i] / tau + 0.5).floor() * tau;
        } else if delta[i] < -std::f32::consts::PI {
            angles[i] += (-delta[i] / tau + 0.5).floor() * tau;
        }
        delta[i] = angles[i] - old[i];
    }
    for i in 0..3 {
        if delta[i].abs() as f64 > std::f64::consts::PI
            && (delta[(i + 1) % 3].abs() as f64) < std::f64::consts::FRAC_PI_2
            && (delta[(i + 2) % 3].abs() as f64) < std::f64::consts::FRAC_PI_2
        {
            angles[i] += if delta[i] > 0.0 { -tau } else { tau };
        }
    }
    angles
}
fn mul3(a: Mat, b: Mat) -> Mat {
    let mut out = identity();
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] = (a[r][0] * b[0][c] + a[r][1] * b[1][c]) + a[r][2] * b[2][c];
        }
    }
    out
}
pub fn copy_rotation(
    owner: Mat,
    target: Mat,
    axes: [bool; 3],
    invert: [bool; 3],
    order: usize,
    mode: &str,
) -> Mat {
    let mut size = sizes(owner);
    let mut oldrot = owner;
    for c in 0..3 {
        let col = normalized([owner[0][c], owner[1][c], owner[2][c]]).0;
        for r in 0..3 {
            oldrot[r][c] = col[r];
        }
    }
    if det(oldrot) < 0.0 {
        for r in 0..3 {
            for c in 0..3 {
                oldrot[r][c] = -oldrot[r][c];
            }
        }
        size = size.map(|v| -v);
    }
    let old = to_euler(owner, order);
    let (a, b) = euler_pair(orthogonalize(target, true), order);
    let a = compatible(a, old);
    let b = compatible(b, old);
    let distance = |angles: [f32; 3]| (0..3).map(|i| (angles[i] - old[i]).abs()).sum::<f32>();
    let mut angles = if distance(a) > distance(b) { b } else { a };
    for i in 0..3 {
        if !axes[i] {
            angles[i] = if mode == "REPLACE" || mode == "OFFSET" {
                old[i]
            } else {
                0.0
            };
        } else {
            if mode == "OFFSET" {
                let mut rotation = [0.0; 3];
                rotation[i] = old[i];
                angles = to_euler(mul3(euler(angles, order), euler(rotation, order)), order);
            }
            if invert[i] {
                angles[i] = -angles[i];
            }
        }
    }
    if mode == "ADD" {
        for i in 0..3 {
            angles[i] += old[i];
        }
    }
    let mut rotation = euler(compatible(angles, old), order);
    if mode == "BEFORE" {
        rotation = mul3(rotation, oldrot);
    } else if mode == "AFTER" {
        rotation = mul3(oldrot, rotation);
    }
    let mut out = owner;
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] = rotation[r][c] * size[c];
        }
    }
    out
}
pub fn filter_transform(matrix: Mat, channels: [bool; 9], order: usize) -> Mat {
    let mut angles = to_euler(matrix, order);
    let mut size = sizes(matrix);
    for i in 0..3 {
        if !channels[i + 3] {
            angles[i] = 0.0;
        }
        if !channels[i + 6] {
            size[i] = 1.0;
        }
    }
    let mut out = euler(angles, order);
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] *= size[c];
        }
        out[r][3] = if channels[r] { matrix[r][3] } else { 0.0 };
    }
    out
}
fn wrap_angle(angle: f32) -> f32 {
    let b = (angle as f64 * (0.5 / std::f64::consts::PI) + 0.5) as f32;
    (((b - b.floor()) - 0.5) as f64 * (2.0 * std::f64::consts::PI)) as f32
}
fn clamp_angle(angle: f32, low: f32, high: f32) -> f32 {
    if (high - low) as f64 >= 2.0 * std::f64::consts::PI {
        return angle;
    }
    if high <= low {
        return low;
    }
    let a = wrap_angle(low - angle);
    let b = wrap_angle(high - angle);
    if a < b {
        angle + 0.0_f32.max(a).min(b)
    } else if b >= 0.0 || a <= 0.0 {
        angle
    } else if b.abs() < a.abs() {
        angle + b
    } else {
        angle + a
    }
}
pub fn limit_rotation(
    m: Mat,
    low: [f64; 3],
    high: [f64; 3],
    axes: [bool; 3],
    order: usize,
    legacy: bool,
) -> Mat {
    let mut m = orthogonalize(m, false);
    if !axes.iter().any(|v| *v) {
        return m;
    }
    let size = sizes(m);
    let mut angles = to_euler(m, order);
    for c in 0..3 {
        if axes[c] {
            angles[c] = if legacy {
                angles[c].max(low[c] as f32).min(high[c] as f32)
            } else {
                clamp_angle(angles[c], low[c] as f32, high[c] as f32)
            };
        }
    }
    let rotation = euler(angles, order);
    for r in 0..3 {
        for c in 0..3 {
            m[r][c] = rotation[r][c] * size[c];
        }
    }
    m
}
/// transform_evaluate: decompose with mat3_to_rot_size, rotate, restore scale.
/// This deliberately retains nonorthogonal normalized columns, as Blender does.
pub fn transform_after(local: Mat, angles: [f32; 3], order: usize) -> Mat {
    let mut rot = identity();
    let mut size = [0.0; 3];
    for c in 0..3 {
        let (column, length) = normalized([local[0][c], local[1][c], local[2][c]]);
        size[c] = length;
        for r in 0..3 {
            rot[r][c] = column[r];
        }
    }
    if det(rot) < 0.0 {
        for r in 0..3 {
            for c in 0..3 {
                rot[r][c] = -rot[r][c];
            }
        }
        for s in &mut size {
            *s = -*s;
        }
    }
    let newrot = euler(angles, order);
    let mut out = identity();
    // mul_m3_m3m3 uses the scalar three-term sum, not the 4x4 SSE tree.
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] = ((rot[r][0] * newrot[0][c] + rot[r][1] * newrot[1][c])
                + rot[r][2] * newrot[2][c])
                * size[c];
        }
        out[r][3] = local[r][3];
    }
    out
}
/// damptrack_do_transform: parallel/opposite directions and near-pole precision.
/// Fractional influence is handled by Blender's reference path until its generic
/// matrix interpolation has a separately verified port.
pub fn damped_track(matrix: Mat, target: [f32; 3], axis: usize, negative: bool) -> Mat {
    let sign = if negative { -1.0 } else { 1.0 };
    let (tarvec, len) = normalized(target);
    if len == 0.0 {
        return matrix;
    }
    let (mut obvec, len) = normalized([
        matrix[0][axis] * sign,
        matrix[1][axis] * sign,
        matrix[2][axis] * sign,
    ]);
    if len == 0.0 {
        obvec = [0.0; 3];
        obvec[axis] = sign;
    }
    // Blender's cross_high_precision promotes the products to double.
    let a = obvec.map(f64::from);
    let b = tarvec.map(f64::from);
    let cross = [
        (a[1] * b[2] - a[2] * b[1]) as f32,
        (a[2] * b[0] - a[0] * b[2]) as f32,
        (a[0] * b[1] - a[1] * b[0]) as f32,
    ];
    let (mut raxis, norm) = normalized(cross);
    let mut angle = dot(obvec, tarvec).clamp(-1.0, 1.0).acos();
    if norm < f32::EPSILON {
        if (angle as f64).abs() < std::f64::consts::PI - 0.01_f32 as f64 {
            return matrix;
        }
        angle = std::f64::consts::PI as f32;
        let next = (axis + if negative { 3 } else { 0 } + 1) % 6;
        let sign = if next >= 3 { -1.0 } else { 1.0 };
        let c = next % 3;
        let tmp = [
            matrix[0][c] * sign,
            matrix[1][c] * sign,
            matrix[2][c] * sign,
        ];
        let (vector, n) = normalized(self::cross(obvec, tmp));
        if n == 0.0 {
            return matrix;
        }
        raxis = vector;
    } else if norm < 0.1 {
        angle = if angle as f64 > std::f64::consts::FRAC_PI_2 {
            (std::f64::consts::PI - norm.asin() as f64) as f32
        } else {
            norm.asin()
        };
    }
    // axis_angle_normalized_to_mat3_ex, preserving its multiplication ordering.
    let (s, c) = angle.sin_cos();
    let ico = 1.0 - c;
    let [x, y, z] = raxis;
    let n00 = (x * x) * ico;
    let n01 = (x * y) * ico;
    let n11 = (y * y) * ico;
    let n02 = (x * z) * ico;
    let n12 = (y * z) * ico;
    let n22 = (z * z) * ico;
    let rot = [
        [n00 + c, n01 - z * s, n02 + y * s],
        [n01 + z * s, n11 + c, n12 - x * s],
        [n02 - y * s, n12 + x * s, n22 + c],
    ];
    let mut out = matrix;
    for r in 0..3 {
        for c in 0..3 {
            out[r][c] =
                (rot[r][0] * matrix[0][c] + rot[r][1] * matrix[1][c]) + rot[r][2] * matrix[2][c];
        }
    }
    out
}
