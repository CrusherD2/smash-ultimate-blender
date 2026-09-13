// SPDX-License-Identifier: GPL-2.0-or-later
use crate::math::{M, V};

/// Replaced by the real Eigen::JacobiSVD shim call in Task 5.
pub fn eigen_svd(_columns: &[V]) -> (M, V, Vec<V>) {
    unimplemented!("Eigen backend arrives in Task 5")
}
