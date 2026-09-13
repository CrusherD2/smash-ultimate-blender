// SPDX-License-Identifier: GPL-2.0-or-later
// Deliberately scalar f64 arithmetic. No fast-math or fused multiply-add.
pub type V = [f64; 3];
pub type M = [[f64; 3]; 3];
pub const I: M = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]];
pub fn add(a: V, b: V) -> V {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
pub fn sub(a: V, b: V) -> V {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
pub fn scale(a: V, s: f64) -> V {
    [a[0] * s, a[1] * s, a[2] * s]
}
pub fn dot(a: V, b: V) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
pub fn norm(a: V) -> f64 {
    dot(a, a).sqrt()
}
pub fn unit(a: V) -> V {
    let n = norm(a);
    if n < 1e-20 {
        [0.; 3]
    } else {
        a.map(|x| x / n)
    }
}
pub fn cross(a: V, b: V) -> V {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
pub fn col(a: M, i: usize) -> V {
    [a[0][i], a[1][i], a[2][i]]
}
pub fn transpose(a: M) -> M {
    [col(a, 0), col(a, 1), col(a, 2)]
}
pub fn mv(a: M, b: V) -> V {
    [dot(a[0], b), dot(a[1], b), dot(a[2], b)]
}
pub fn mm(a: M, b: M) -> M {
    let mut c = [[0.; 3]; 3];
    for r in 0..3 {
        for i in 0..3 {
            c[r][i] = dot(a[r], col(b, i));
        }
    }
    c
}
pub fn inverse(a: M) -> M {
    let x = cross(a[1], a[2]);
    let y = cross(a[2], a[0]);
    let z = cross(a[0], a[1]);
    let det = dot(a[0], x);
    assert!(det.abs() > 1e-30, "singular rest basis");
    transpose([scale(x, 1. / det), scale(y, 1. / det), scale(z, 1. / det)])
}
pub fn rodrigues(d: V) -> M {
    let theta = norm(d);
    if theta.abs() < 1e-20 {
        return I;
    }
    let w = scale(d, 1. / theta);
    let s = theta.sin();
    let c = theta.cos();
    let k = 1. - c;
    let (x, y, z) = (w[0], w[1], w[2]);
    [
        [c + x * x * k, -z * s + x * y * k, y * s + x * z * k],
        [z * s + x * y * k, c + y * y * k, -x * s + y * z * k],
        [-y * s + x * z * k, x * s + y * z * k, c + z * z * k],
    ]
}

/// Which SVD implementation decides each damped-least-squares step.
///
/// `Approximate` is the one-sided Jacobi implementation in this file. It is
/// NOT bit-compatible with Blender and remains the default.
/// `Eigen` calls Blender's own Eigen::JacobiSVD through the C++ shim.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Backend {
    #[default]
    Approximate,
    Eigen,
}

/// Dispatch to the selected backend. The two must be interchangeable at this
/// boundary so they can be compared directly on identical inputs.
pub fn svd(backend: Backend, columns: &[V]) -> (M, V, Vec<V>) {
    match backend {
        Backend::Approximate => approximate_svd(columns),
        Backend::Eigen => crate::eigen::eigen_svd(columns),
    }
}

/// Thin SVD of a 3-by-N Jacobian using one-sided Jacobi sweeps on J^T.
/// Same mathematical decomposition as Eigen, but not claimed bit-compatible
/// with Eigen's QR preconditioner and Jacobi implementation.
pub fn approximate_svd(columns: &[V]) -> (M, V, Vec<V>) {
    let mut a = columns.to_vec();
    let mut u = I;
    for _ in 0..64 {
        let mut changed = false;
        for p in 0..3 {
            for q in p + 1..3 {
                let mut aa = 0.;
                let mut bb = 0.;
                let mut ab = 0.;
                for row in &a {
                    aa += row[p] * row[p];
                    bb += row[q] * row[q];
                    ab += row[p] * row[q];
                }
                if ab.abs() <= f64::EPSILON * (aa * bb).sqrt() {
                    continue;
                }
                let tau = (bb - aa) / (2. * ab);
                let t = if tau >= 0. {
                    1. / (tau + (1. + tau * tau).sqrt())
                } else {
                    -1. / (-tau + (1. + tau * tau).sqrt())
                };
                let c = 1. / (1. + t * t).sqrt();
                let s = c * t;
                for row in &mut a {
                    let (x, y) = (row[p], row[q]);
                    row[p] = c * x - s * y;
                    row[q] = s * x + c * y;
                }
                for row in &mut u {
                    let (x, y) = (row[p], row[q]);
                    row[p] = c * x - s * y;
                    row[q] = s * x + c * y;
                }
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    let w: V = std::array::from_fn(|i| a.iter().map(|r| r[i] * r[i]).sum::<f64>().sqrt());
    let mut order = [0, 1, 2];
    order.sort_by(|&i, &j| w[j].total_cmp(&w[i]));
    let sorted_u = std::array::from_fn(|r| std::array::from_fn(|c| u[r][order[c]]));
    let sorted_w = order.map(|i| w[i]);
    let v = a
        .iter()
        .map(|row| {
            std::array::from_fn(|c| {
                if sorted_w[c] > 0. {
                    row[order[c]] / sorted_w[c]
                } else {
                    0.
                }
            })
        })
        .collect();
    (sorted_u, sorted_w, v)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reconstruct_svd() {
        let a = vec![
            [1., 2., 3.],
            [4., -2., 1.],
            [0.5, 2., 7.],
            [1., 1., -2.],
            [2., 2., 2.],
            [0., 1., 0.],
        ];
        let (u, w, v) = approximate_svd(&a);
        for (r, row) in a.iter().enumerate() {
            for i in 0..3 {
                let value = (0..3).map(|j| u[i][j] * w[j] * v[r][j]).sum::<f64>();
                assert!((value - row[i]).abs() < 1e-12);
            }
        }
    }
    #[test]
    fn backend_dispatch_matches_approximate() {
        let a = vec![
            [0.3, -1.2, 0.7],
            [2.0, 0.1, -0.4],
            [-0.6, 0.9, 1.5],
            [0.05, 0.02, -0.01],
        ];
        let direct = approximate_svd(&a);
        let dispatched = svd(Backend::Approximate, &a);
        assert_eq!(direct.0, dispatched.0);
        assert_eq!(direct.1, dispatched.1);
        assert_eq!(direct.2, dispatched.2);
    }
    #[test]
    fn backend_defaults_to_approximate() {
        assert_eq!(Backend::default(), Backend::Approximate);
    }
    #[test]
    fn eigen_reconstructs_the_input() {
        let a = vec![
            [0.3, -1.2, 0.7],
            [2.0, 0.1, -0.4],
            [-0.6, 0.9, 1.5],
            [0.05, 0.02, -0.01],
        ];
        let (u, w, v) = svd(Backend::Eigen, &a);
        // A^T == U * diag(w) * V^T, so every input row is recoverable.
        for (row, vrow) in a.iter().zip(v.iter()) {
            for i in 0..3 {
                let rebuilt: f64 = (0..3).map(|k| u[i][k] * w[k] * vrow[k]).sum();
                assert!((rebuilt - row[i]).abs() < 1e-12, "{} vs {}", rebuilt, row[i]);
            }
        }
    }
    #[test]
    fn eigen_orders_singular_values_descending() {
        let a = vec![[0.3, -1.2, 0.7], [2.0, 0.1, -0.4], [-0.6, 0.9, 1.5]];
        let (_, w, _) = svd(Backend::Eigen, &a);
        assert!(w[0] >= w[1] && w[1] >= w[2], "{:?}", w);
    }
    #[test]
    fn rotation_preserves_length() {
        let r = rodrigues([0.3, -0.4, 0.1]);
        assert!((norm(mv(r, [1., 2., 3.])) - 14f64.sqrt()).abs() < 1e-14);
    }
}
