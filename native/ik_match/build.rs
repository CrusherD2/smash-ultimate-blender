// SPDX-License-Identifier: GPL-2.0-or-later
//! Compiles the Eigen JacobiSVD shim.
//!
//! Eigen headers are located through SUB_IK_EIGEN_DIR, falling back to
//! `vendor/eigen`. The directory must be the one CONTAINING the `Eigen`
//! folder, so that `#include <Eigen/SVD>` resolves.
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-changed=eigen_shim/sub_ik_eigen_svd.cpp");
    println!("cargo:rerun-if-env-changed=SUB_IK_EIGEN_DIR");
    let eigen = std::env::var("SUB_IK_EIGEN_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("vendor/eigen"));
    // The Eigen backend is an opt-in comparison control, not a requirement.
    // Without headers the crate still builds and math::Backend::Eigen panics
    // with an explanation, rather than making the whole crate unbuildable.
    println!("cargo:rustc-check-cfg=cfg(no_eigen)");
    if !eigen.join("Eigen/SVD").exists() {
        println!("cargo:rustc-cfg=no_eigen");
        return;
    }
    let mut build = cc::Build::new();
    build
        .cpp(true)
        .file("eigen_shim/sub_ik_eigen_svd.cpp")
        .include(&eigen)
        .opt_level(2);
    if build.get_compiler().is_like_msvc() {
        // Identical source is not identical arithmetic unless the flags agree.
        // /fp:precise forbids reassociation; /fp:contract=off forbids fusing
        // a*b+c into an FMA, which rounds differently from the two operations.
        build
            .flag("/fp:precise")
            .flag("/fp:contract=off")
            .flag("/EHsc");
    } else {
        build.flag("-ffp-contract=off").flag("-fno-fast-math");
    }
    build.compile("sub_ik_eigen_svd");
}
