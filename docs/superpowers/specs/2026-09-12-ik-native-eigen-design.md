# Native Eigen IK solver and whole-animation matching — design

Status: approved 2026-09-12. Supersedes the acceleration strategy in
`docs/benchmarks/position-ik-strategies-2026-09-12.md`, which this design
builds on rather than replaces.

## Problem

IK matching is 2.02-2.27x faster than the pre-optimization code and exact, but
the target is closer to 10x. Two things block it.

**The inner loop still runs in Blender and in Python.** A cProfile run of a
157-frame two-limb match shows where the 4.254 s goes:

| Component | Time | Share |
|---|---:|---:|
| `_evaluate_match_steps` (depsgraph evaluation) | 2.887 s | 68% |
| Python search (`_match_chain_steps`, `error`, `best`) | ~0.61 s | 14% |
| Sampling and setup | ~0.5 s | 12% |
| Key writing (`fcurve_bulk`) | ~0.14 s | 3% |

Removing the depsgraph alone caps the speedup at about 3.1x, which is why the
Rust accelerator plateaued at 2-3x: it made the arithmetic faster while leaving
Python and the depsgraph in the loop. Reaching 10x requires the whole per-frame
pole search to run natively, with Python present only to sample FK in and write
keys out.

**The native solver is not bit-compatible with Blender.** It cannot be enabled
by default, so none of its speed is available to users. `native/ik_match/src/math.rs:79`
documents the cause in its own words: the SVD uses one-sided Jacobi sweeps and is
"not claimed bit-compatible with Eigen's QR preconditioner and Jacobi
implementation." Everything else in the port was transcribed faithfully —
`inverse4.rs` is a scalar transcription of Eigen's `InverseSize4.h` — but the
one component that decides each solve is an approximation. The observed
consequence is 32 of 40 native candidates differing from Blender on a
near-straight-chain suite, largest difference approximately 3.55e-15.

## Approach

Stop reimplementing Eigen and compile the real thing. Blender's `intern/iksolver`
is GPL-2.0-or-later and this add-on is GPL, so its sources and the Eigen version
Blender vendors can be built directly into the native module behind the existing
C ABI. Exactness stops being a property to test for and becomes structural.

Then remove Blender and Python from the search loop, and parallelize across
frames.

## Goals

- The native backend produces results bit-identical to Blender's, verified
  against ground truth, so it can be enabled by default.
- Matching and import reach roughly 6-7x over the pre-optimization baseline,
  with 10x dependent on what Phase 4 measures.
- Every step is reversible and separately measurable; no phase is built on an
  unverified assumption from the phase before it.

## Non-goals

- Analytic closed-form two-bone IK. It would exceed 10x but abandons Blender's
  damped-least-squares behavior and diverges on unreachable targets. Held in
  reserve; not in scope.
- Platforms beyond Windows x64, and Blender versions beyond 4.5 and 5.2. Widening
  the version gate is tracked separately.
- Chains other than the independent generated two-bone chains the native path
  already restricts itself to. All existing guards in `ik_native.supported()`
  remain.

## Exactness criterion

Two different guarantees apply to two different parts of this work, and
conflating them is the main correctness risk.

**The solver must be bit-identical.** The Eigen backend's output must equal
Blender's component for component. This is the acceptance gate for Phase 1 and it
admits no tolerance.

**The search may find a different angle, if it is equal or better.** Phase 3
replaces the previous-frame pole-angle seed with a deterministic per-frame
candidate set so that each frame becomes a pure function of its own inputs, which
is what makes frames parallelizable. That seed currently decides which local
minimum some frames land in, so results can differ from today's output by
approximately 1e-15 on those frames.

Because output fingerprints therefore stop being a valid pass/fail signal for
Phase 3, they are replaced by a stricter test: **for every frame,
`residual_new <= residual_old`.** The new search may never fit worse than the
current one on any frame. This is checked per frame, not in aggregate.

Phases 1 and 2 keep fingerprint equality as their acceptance test, since neither
changes the search.

## Design

### SVD backend seam

`math.rs:82` exposes the entire boundary:

```rust
pub fn svd(columns: &[V]) -> (M, V, Vec<V>)
```

It has one call site, `sdls()` in `solver.rs:90`. A trait with this signature
gets two implementations:

- `ApproximateSvd` — today's one-sided Jacobi sweeps, moved unchanged out of
  `math.rs`. Retained as the experimental control, not deleted.
- `EigenSvd` — real `Eigen::JacobiSVD` through a thin C++ shim.

Backend selection travels in the capture struct, with an environment override, so
one DLL runs both and switching needs no rebuild. The default remains
`ApproximateSvd` until Phase 1's evidence justifies changing it.

### Jacobian orientation

Blender's `IK_QJacobian` stores the Jacobian as `(3 * ntasks) x ndof` and runs
`JacobiSVD` on that orientation. The Rust port operates on the transpose
(`j: &[V]` is `ndof x 3`), which swaps the roles of U and V. That is
mathematically equivalent and numerically different.

The Eigen backend must reproduce **Blender's** orientation, not the Rust port's.
This is the single likeliest source of a subtle mismatch, and the differential
harness below is designed to localize it if it occurs.

### Build

- Vendor `intern/iksolver` and `extern/eigen3` under `native/ik_match/`, with
  GPL and MPL notices staged the way `build.py` already stages dependency
  licenses.
- Compile through the `cc` crate from `build.rs` with `/fp:precise`, FMA
  contraction disabled, `/O2`, and no fast-math. Identical source does not imply
  identical arithmetic unless the flags agree.
- **Settled before any code is written:** whether Blender 4.5 and 5.2 vendor the
  same Eigen version and the same iksolver sources. If they diverge, the build
  produces one binary per Blender version and `ik_native.get_factory()` selects
  between them. This changes the build's shape, so it is resolved first.

### Whole-animation native drive (Phase 2)

Today `_match_chain_steps` yields a `Request` per candidate angle, and
`ik_native.evaluate_steps` round-trips each result back through `ctypes` into
`mathutils.Matrix` objects. That is Python work per candidate, on top of a
depsgraph evaluation per barrier in the non-experimental modes.

Phase 2 replaces this with a single FFI call per operation carrying every frame
and every chain: sampled FK targets in, final pole angles and matrices out. The
pole search moves wholly inside the native module, keeping its current candidate
order and convergence behavior. Python retains `sample_fk` and the bulk key
writer and nothing else in the loop.

### Parallel frames (Phase 3)

With the previous-frame seed replaced by a deterministic per-frame candidate set,
frames become independent pure functions and are dispatched across `rayon`.

The earlier finding that four threads were 9% slower measured the wrong axis: it
threaded at most four tiny solves within a single frame, where dispatch overhead
dominates. Across 157 or 372 frames the ratio is entirely different.

## Accuracy plan

Four layers, tightest first. Each localizes failures the layer below it can only
report.

1. **Differential SVD harness.** Capture every real `(J, beta)` pair from a full
   match and import of the fixture (approximately 11.3k evaluations at 12-20
   iterations each, so 150-250k SVD calls), serialize them, and run both backends
   over all of them. Report max and mean componentwise delta in U, W, V and in
   the resulting `theta`. Pure native, no Blender, so it runs in seconds and is
   re-runnable on every change.
2. **Solver level.** The same captured problems solved end to end under each
   backend, compared against Blender's matrices.
3. **Blender ground truth.** The existing suites run under both backends on both
   versions: the 245-case near-straight singular suite, the 10,000-pose
   randomized stress suite, the 12 scenario tests, and the 48-row factorial
   fixture.
4. **Acceptance gate.** The Eigen backend must produce **zero mismatches against
   Blender across every suite**. Not smaller deltas — zero. A failure here means
   the flag alignment or the Jacobian orientation is wrong, and layer 1 identifies
   which.

## Phases

**Phase 0 — handler cost.** `motion_list_auto_sync_handler`,
`_stage_light_depsgraph_update` and `auto_detect_smash_armature` each fire 2,827
times during a single match, costing about 0.12 s (3%). Mute them during
matching. Independent of everything else and contained.

**Phase 1 — backend seam, Eigen backend, differential harness. Go/no-go gate.**
Stop and report before proceeding. If the Eigen backend cannot reach zero
mismatches against Blender, this design's premise is wrong and the remaining
phases are reassessed rather than built on it.

**Phase 2 — whole-animation native drive.** Removes the 68% depsgraph share and
the 14% Python search share. Acceptance: fingerprint equality.

**Phase 3 — deterministic per-frame candidates and parallel frames.**
Acceptance: equal-or-better residual per frame.

**Phase 4 — sampling and key-writing trim.** What stands between roughly 6x and
10x.

Because Phase 1 is a gate whose outcome determines whether Phases 2-4 are worth
building, the implementation plan covers **Phases 0 and 1 only**. Phases 2-4 are
planned after Phase 1 reports.

## Risks

- **Phase 1 may fail.** MSVC and Blender's official build may not produce
  identical floating-point arithmetic from identical source. This is measured,
  not assumed, and it is why Phase 1 is a gate.
- **Per-version binaries.** If 4.5 and 5.2 vendor different Eigen or iksolver
  sources, the build and the loader both grow a version axis.
- **10x is not guaranteed.** The profile supports 6-7x with confidence. The
  remainder depends on Phase 4 findings about sampling and key writing.
- **Phase 3 changes output.** Some frames will differ from today's by
  approximately 1e-15. This is accepted deliberately, bounded by the
  equal-or-better residual test, and must be recorded in the changelog.

## Acceptance criteria

- Eigen backend: zero mismatches against Blender on all four accuracy layers,
  both versions.
- Native matching enabled by default, with the existing fallback guards intact
  and unchanged.
- Phases 1 and 2: output fingerprints identical to current.
- Phase 3: per-frame residual equal or better than current on every frame of the
  fixture.
- Benchmarks recorded per phase, separately and combined, on both 4.5 and 5.2,
  in the established `docs/benchmarks/` format.
- `ApproximateSvd` retained and selectable.
