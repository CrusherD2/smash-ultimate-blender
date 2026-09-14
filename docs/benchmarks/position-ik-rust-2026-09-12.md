# Rust native IK prototype — 2026-09-12

Historical first prototype. The corrected and integrated accelerator is recorded
in [round 2](position-ik-rust-round2-2026-09-12.md); the findings below describe
the earlier implementation.

Result: the isolated Rust kernel is fast and deterministic across thread counts,
but **does not reproduce Blender exactly**. It is not enabled in the addon.
These measurements establish feasibility of native computation, not a completed
exact replacement or an end-to-end import speedup.

## Measured timings

Windows release build, Rust 1.89.0, Rayon native thread pool. Real Sceptile rig,
157 frames × four limbs × three pole angles = 1,884 evaluations per batch.

| Runtime | Blender dependency-graph evaluations | Rust, one thread | Rust, four threads |
|---|---:|---:|---:|
| Blender 4.5.7 LTS fixture capture | 2.934284 s | 0.015733 s | 0.004209 s |
| Blender 5.2.1 LTS fixture capture | 2.533779 s | 0.015554 s | 0.004245 s |

Four threads improve the Rust kernel by 3.74× and 3.66× respectively. Blender
values are the sum of one pass of timed dependency-graph updates after setting
each pole angle. Rust values are medians of seven batches after a warmup, with
pool creation, input/output, JSON parsing, capture and reconstruction excluded.
These columns deliberately measure different boundaries: Blender includes the
dependency graph, Rust includes just independent numerical solves. They are
not interchangeable measurements of the complete Position IK Controls operation.

The prior exact production implementation remains the latest accepted result:
3.110 s for the 157-frame matching benchmark and 8.270 s for its 372-frame import
benchmark, as recorded in `position-ik-round2-2026-09-12.md`. No new end-to-end
speedup is claimed by this prototype.

## Compatibility results

Both Blender versions produced the same reported error distribution:

- Exactly identical reconstructed solver matrices: **0 / 1,884** cases.
- Median maximum matrix-element error per case: `1.430511474609375e-6`.
- Worst maximum matrix-element error: `9.5367431640625e-6`.
- Worst case: `FootIKR@17/0.35`.
- Rust one-thread and four-thread outputs: identical; repeated batches identical.

The difference is small, but it fails the user's exact-match requirement. The
probe checks solver matrices, not final control keys or whole-rig poses, so even
a passing result here would only be the first acceptance gate. The strict
Blender 5.2 run returned failure as intended. Rust's three numerical unit tests,
format check and tracked diff whitespace check passed.

## Implementation and remaining obstacle

`native/ik_match` implements the restricted spherical-joint SDLS solver in Rust,
with a Rayon pool operating on detached numeric inputs. No worker reads or
writes Blender data. The prototype has no production integration or installer
changes. It follows Blender v4.5.0 IK sources, including pole alignment, damping,
iteration thresholds and f32 conversion boundaries.

Its one-sided Jacobi SVD is mathematically equivalent to the required
decomposition but does not reproduce Eigen's arithmetic sequence. The Python
export/reconstruction boundary also needs independent validation. The measured
differences have not yet been isolated to either component. Simply relaxing
tolerances, increasing solver iterations or enabling more threads would not
establish exactness.

The next engineering step toward an exact Rust backend is a diagnostic build
of Blender that exposes pre-solve inputs and raw basis changes, allowing the
conversion boundary and solver to be compared separately. Then reproduce the
relevant Eigen decomposition and float operation ordering in Rust. Only after
those match should the complete pole search and output-key comparison be added.
Per-frame previous-angle candidates must retain their existing ordering;
parallelizing arbitrary frames is not justified by this independent-job probe.

Reproduction instructions and source attribution are in
`native/ik_match/README.md`. Raw summaries are
`position-ik-rust-4.5-2026-09-12.json` and
`position-ik-rust-5.2-2026-09-12.json`.
