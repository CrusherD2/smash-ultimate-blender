# Eigen SVD exactness gate — 2026-09-12

Phase 1 go/no-go gate from
`docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md`.

## Verdict: FAIL — and the design's premise is falsified

Compiling Blender's own `Eigen::JacobiSVD` into the native module did **not**
reduce mismatches against Blender. It changed them from 32 cases to 33, with the
same worst-case magnitude.

The approximated SVD was not the reason the native backend fails bit-exactness.
Phases 2-4 must not be built on that assumption.

## What was built

Real `Eigen::JacobiSVD` 3.4.0 is now compiled through a C++ shim
(`native/ik_match/eigen_shim/sub_ik_eigen_svd.cpp`) and callable from Rust as
`math::Backend::Eigen`, in Blender's `3 x ndof` Jacobian orientation. The
previous one-sided Jacobi implementation is retained as
`math::Backend::Approximate` and remains the default. Both are selectable at
runtime through `SUB_NATIVE_SVD`.

Eigen headers are located at build time through `SUB_IK_EIGEN_DIR`. They are
deliberately **not vendored into this repository**: the gate did not justify
adding 6.7 MB of headers.

Blender patches its vendored Eigen in exactly one file,
`Eigen/src/SparseCore/SparseDenseProduct.h`, which dense `JacobiSVD` does not
touch, so upstream Eigen 3.4.0 is equivalent for the 4.5 path. The shim does not
need Blender's `intern/iksolver` sources: the Rust port already transcribes that
logic, and the SVD was the only component previously described as approximated.

## Layer 1 — differential harness

136,512 real `(J, beta)` pairs captured from a complete `BOTH` match on the
fixture, both backends run over every one of them.

| Quantity | Result |
|---|---|
| `theta` (the damped-least-squares step that feeds the solve) | max difference **1.94e-16** |
| `theta` bit-identical | 0 of 136,512 |
| U, sign-canonicalized | max difference 2.48e-13 |
| V, sign-canonicalized | max difference 2.36e-13 |
| singular values | max difference 2.00e-15 |

A first version of this harness compared U and V directly and reported
differences near 2.0. That was measuring the SVD sign ambiguity, not accuracy: a
decomposition is unique only up to a simultaneous sign flip of each paired
`(u_i, v_i)` column. `sdls` uses `v[k][i] * dot(u_i, beta)` and `.abs()`
elsewhere, so it is sign invariant. The harness now canonicalizes signs and
reports `theta`, which is the quantity that actually matters.

## Layer 3 — Blender ground truth, near-straight singular suite, Blender 4.5.7

245 cases per backend.

| | Approximate | Eigen |
|---|---:|---:|
| Native candidates | 40 | 40 |
| Geometry/iteration fallbacks | 205 | 205 |
| **Mismatches against Blender** | **32** | **33** |
| Worst absolute difference | 3.552713678800501e-15 | 3.552713678800501e-15 |
| Differing matrix elements | 113 | 116 |

32 of the failing cases are common to both backends. Swapping a hand-written
approximation for Eigen's real implementation moved one case the wrong way.

## Why: the differences are noise on mathematically-zero elements

Every one of the 116 differing elements under the Eigen backend has operands
below 1e-6. The largest operand magnitude anywhere in the set is 4.37e-08; the
median is 2.52e-20.

| Worst differing elements | Blender | Native | Difference |
|---|---:|---:|---:|
| `upper[2][2]` | -4.371138e-08 | -4.371138e-08 | 3.553e-15 |
| `lower[2][2]` | -4.371138e-08 | -4.371138e-08 | 3.553e-15 |
| `lower[2][3]` | -4.922406e-10 | -4.922405e-10 | 5.551e-17 |
| `upper[2][0]` | +7.482609e-17 | +6.209982e-17 | 1.273e-17 |

`-4.371138e-08` is the float32 residue of a right-angle rotation — the value
float32 produces where the exact answer is zero. The difference on it, 3.553e-15
against an operand of 4.37e-08, is a relative difference of about 8e-08, which
is float32 epsilon (1.19e-07) territory.

**Elements where both operands exceed 1e-6: zero.** Not one mismatch occurs in a
matrix element carrying a meaningful value.

So the native path already agrees with Blender everywhere that matters
numerically, and disagrees only in the float32 rounding residue of near-straight,
right-angle geometry. The cause lies in the single/double precision boundaries of
the pose pipeline — `capture.rs` (`Mat3 = [[f32; 3]; 3]`), `pose.rs`
(`Mat4` is float32) and `inverse4.rs` (float32 packets) — not in the solver's
linear algebra.

## Consequences

1. **Phases 2-4 are not started.** Their justification assumed the SVD was the
   blocker.
2. **The problem is smaller than the earlier report implied.** The remaining
   obstacle is a localized precision-boundary question in near-zero rotation
   elements, not a reimplementation of Eigen's SVD including degenerate paths.
   That is a materially more tractable target.
3. **The earlier attribution was wrong.** `math.rs`'s self-declared caveat about
   not being bit-compatible with Eigen was honest about itself, but the drift was
   attributed to it without testing that attribution. This gate tested it.
4. **The Eigen backend is kept**, selectable and unused by default. It costs
   nothing, and it is the control that makes the next investigation meaningful.

## Recommended next probe

Compare the native and Blender values for the same near-straight case at each
stage of the pose pipeline rather than only at the output, to identify the first
stage at which the float32 residue diverges. If it is a single conversion,
matching Blender's precision there may close the gap entirely — at which point
the existing, already-benchmarked native speedup becomes shippable by default.

## Reproduction

```
SUB_IK_EIGEN_DIR=<dir containing Eigen/> python native/ik_match/build.py
SUB_NATIVE_SVD=eigen python tests/run_blender_test.py --blender <4.5> tests/test_native_ik_singular_blender.py
cargo run --release --bin svd_diff -- <capture.jsonl>
```

Capture with `SUB_NATIVE_IK=experimental SUB_IK_SVD_CAPTURE=<path>` during a
match. Eigen 3.4.0 source SHA-256
`8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72`. Built with
MSVC 14.29, `/fp:precise /fp:contract=off /O2`.
