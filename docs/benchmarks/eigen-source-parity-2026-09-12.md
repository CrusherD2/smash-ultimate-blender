# Eigen and iksolver source parity, Blender 4.5.7 vs 5.2.1 — 2026-09-12

Task 2 of `docs/superpowers/plans/2026-09-12-ik-native-eigen-phase-0-1.md`.
Determines whether the native Eigen backend can ship as one binary or needs one
per Blender version.

## Verdict

**`PER_VERSION_BINARY`** — and by a wider margin than the plan anticipated. The
two Blender versions do not merely vendor different revisions of the same Eigen;
5.2 does not vendor Eigen at all.

## Eigen

| Blender | Where Eigen comes from | Version |
|---|---|---|
| 4.5.7 LTS | vendored in-tree at `extern/Eigen3/` | 3.4.0 (`EIGEN_WORLD/MAJOR/MINOR = 3/4/0`) |
| 5.2.1 LTS | external precompiled dependency, `bf::dependencies::eigen` | unreleased master commit `8a1083e9bf41b91fdea6546681f806154efdc25a` |

`extern/Eigen3/` is absent from the 5.2.1 tree. `intern/iksolver/CMakeLists.txt`
in 5.2.1 links `bf::dependencies::eigen`, and
`build_files/build_environment/cmake/versions.cmake` pins that dependency to a
GitLab archive of the commit above, with the comment "latest on 2025-12-05
didn't build, picked a slightly older commit" and
`EIGEN_HASH cc28a84fdec496c6777596350ea805519bf10f717d21044ae6ba3dd562183a26`.

A stale comment in 5.2.1's root `CMakeLists.txt` still refers to
`./extern/Eigen3/Eigen/src/Core/util/Memory.h`. It does not reflect the tree.

This matters because Eigen's `JacobiSVD` changed between 3.4.0 and post-3.4
master. The two Blender versions are therefore running materially different SVD
code, not two builds of the same code.

## iksolver

SHA-256 prefixes of the files that decide a solve, fetched from the
`blender/blender` GitHub mirror at tags `v4.5.7` and `v5.2.1`:

| File | 4.5.7 | 5.2.1 | Same |
|---|---|---|---|
| `intern/iksolver/intern/IK_QJacobian.cpp` | `269be81da0d43ff7` | `8252c7b13cd7fb5b` | no |
| `intern/iksolver/intern/IK_QJacobianSolver.cpp` | `6e9bab34b6157e83` | `6e9bab34b6157e83` | yes |
| `intern/iksolver/intern/IK_QSegment.cpp` | `6c11b15aaa1cb8cd` | `6c11b15aaa1cb8cd` | yes |
| `intern/iksolver/intern/IK_QTask.cpp` | `9e9803cc93209b69` | `f820322565b8aa1e` | no |

Two of the four differ, `IK_QJacobian.cpp` among them — the file that builds the
Jacobian and calls `JacobiSVD`.

## Consequences for the plan

1. Task 4 vendors two source sets: `vendor/4.5/` (Eigen 3.4.0 + 4.5.7 iksolver)
   and `vendor/5.2/` (Eigen at commit `8a1083e9` + 5.2.1 iksolver).
2. Task 4 builds two shims, producing either two DLLs or one DLL exporting two
   symbols. `ik_native.get_factory()` selects on `bpy.app.version[:2]`, which it
   already reads.
3. Eigen is header-only and needed only at build time. The shipped artifact is
   still a DLL, so the add-on's download size is unaffected as long as packaging
   continues to exclude `native/ik_match/vendor/`. Repository size grows.
4. Task 8's gate must pass independently on each version. A pass on one says
   nothing about the other, because the underlying SVD code differs.

## Method

All files fetched from `https://raw.githubusercontent.com/blender/blender/<tag>/<path>`.
`projects.blender.org` returns 403 to non-browser clients; the GitHub mirror
serves the same tagged content. Directory listings via the GitHub contents API.
No full source tarball was downloaded.
