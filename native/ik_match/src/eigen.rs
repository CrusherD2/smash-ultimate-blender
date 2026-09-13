// SPDX-License-Identifier: GPL-2.0-or-later
//! Bridge to Blender's own Eigen::JacobiSVD, compiled from Eigen's headers.
use crate::math::{M, V};

#[cfg(not(no_eigen))]
extern "C" {
    fn sub_ik_eigen_svd(jacobian: *const f64, ndof: usize, u: *mut f64, w: *mut f64, v: *mut f64);
}

/// Built without Eigen headers. Selecting this backend is a configuration
/// error rather than a fallback: silently using the approximate solver under
/// the name "eigen" would invalidate any comparison made against it.
#[cfg(no_eigen)]
pub fn eigen_svd(_columns: &[V]) -> (M, V, Vec<V>) {
    panic!("this build has no Eigen backend; rebuild with SUB_IK_EIGEN_DIR set")
}

/// `columns` is ndof rows of 3, that is, the TRANSPOSE of Blender's Jacobian.
///
/// Blender runs JacobiSVD on the 3 x ndof orientation, so transpose back
/// before handing it over. Feeding Eigen this crate's orientation would swap
/// the roles of U and V and change the rounding, which is exactly the class of
/// difference the Eigen backend exists to eliminate.
#[cfg(not(no_eigen))]
pub fn eigen_svd(columns: &[V]) -> (M, V, Vec<V>) {
    let ndof = columns.len();
    assert!(ndof > 0, "the Jacobian must have at least one degree of freedom");
    let mut jacobian = vec![0.0f64; 3 * ndof];
    for (c, row) in columns.iter().enumerate() {
        for r in 0..3 {
            jacobian[r * ndof + c] = row[r];
        }
    }
    let mut u = [0.0f64; 9];
    let mut w = [0.0f64; 3];
    let mut v = vec![0.0f64; ndof * 3];
    unsafe {
        sub_ik_eigen_svd(
            jacobian.as_ptr(),
            ndof,
            u.as_mut_ptr(),
            w.as_mut_ptr(),
            v.as_mut_ptr(),
        );
    }
    let u: M = std::array::from_fn(|r| std::array::from_fn(|c| u[r * 3 + c]));
    let v: Vec<V> = (0..ndof)
        .map(|r| std::array::from_fn(|c| v[r * 3 + c]))
        .collect();
    (u, w, v)
}
