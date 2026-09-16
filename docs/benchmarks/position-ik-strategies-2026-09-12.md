# IK matching strategies, exactness and the Rust verdict — 2026-09-12

This round answers three questions: what the Rust prototype's "tiny numerical
differences" actually were, which of the proposed non-Rust optimizations are
worth shipping, and whether Rust is worth keeping on top of them.

Two of the proposed optimizations now ship enabled by default and are exact.
Rust stays opt-in and experimental, because its differences are a correctness
problem rather than a tolerance problem.

## 1. What the "tiny numerical differences" are

They are not rounding noise that a tolerance could absorb. They come from
Blender's IK plugin solving the chain with Eigen's SVD-based pseudo-inverse,
whose arithmetic the Rust port does not reproduce bit for bit on degenerate and
slowly converging geometry.

The earlier work removed four *systematic* sources of difference — `mathutils`
double accumulation, reciprocal-based BLI/Eigen inversion, Blender rescaling
only the X/Z axes on IK basis changes, and the float pole angle selecting float
`sin`/`cos` overloads. With those corrected, all 1,884 fixed-angle and all
11,304 real-search evaluations matched exactly on 4.5 and 5.2.

What remained is the SVD itself:

- On a 10,000-pose randomized stress suite per Blender version, restricting
  acceptance to solves converging inside Blender's minimum twelve iterations
  gave 5,620 accepted results, all exactly equal, and 0 accepted mismatches.
- A targeted suite of exactly straight rest bones (bend angles 0 through 0.1 rad,
  seven goals, five pole angles; 245 cases per version) **disproved that rule**.
  After adding a geometry guard for near-collinear starts and degenerate pole
  frames, 32 of the 40 remaining native candidates still differed from Blender,
  with a largest difference of about **3.55e-15**.

3.55e-15 is small, but it is not zero, and the cases that produce it are exactly
the near-straight limb poses that real animation passes through. Under an
exact-match requirement the size of the difference is irrelevant: raising a
threshold to swallow it would convert an exactness guarantee into a tolerance
guarantee. Shipping native results by default would require reimplementing
Eigen's complete SVD arithmetic including its degenerate paths. Convergence
heuristics, geometry guards and multithreading do not substitute for that.

## 2. The proposed optimizations, separately and combined

Both ideas were prototyped, then implemented in production code in
`source/extras/ik_match_fast.py`:

- **`sample`** — eliminate per-frame `frame_set` + `view_layer.update()` during
  FK capture. Drives the action through `fcurve.evaluate(frame)` on a detached
  clone and composes local matrices with `convert_local_to_pose`.
- **`isolate`** — minimal isolated solve rig. Copies the armature into a
  temporary scene, prunes every bone outside the solver's dependency closure,
  runs the *existing* search there, and writes keys back to the original object.

Factorial benchmark, Blender 4.5.7 LTS, real fixture, median of three paired
runs, alternating order. **All 48 rows match the baseline's key and whole-rig
pose fingerprints exactly.**

| Variant | Match, 157 frames | vs baseline | Import, 372 frames | vs baseline |
|---|---:|---:|---:|---:|
| baseline (previous optimized code) | 2.6331 s | 1.00x | 7.2627 s | 1.00x |
| sample only | 2.4863 s | 1.06x | 7.0253 s | 1.03x |
| isolate only | 1.4201 s | 1.85x | 4.3262 s | 1.68x |
| **sample + isolate (shipping default)** | **1.2375 s** | **2.13x** | **4.0303 s** | **1.80x** |
| rust only | 1.2810 s | 2.06x | 4.4383 s | 1.64x |
| sample + rust | 1.1139 s | 2.36x | 4.1014 s | 1.77x |
| isolate + rust | 1.0289 s | 2.56x | 3.5586 s | 2.04x |
| sample + isolate + rust | 0.8212 s | 3.21x | 3.2567 s | 2.23x |

The same factorial on Blender 5.2.1 LTS, also 48 rows, also all exact:

| Variant | Match, 157 frames | vs baseline | Import, 372 frames | vs baseline |
|---|---:|---:|---:|---:|
| baseline (previous optimized code) | 2.7749 s | 1.00x | 7.7012 s | 1.00x |
| sample only | 2.6233 s | 1.06x | 7.5578 s | 1.02x |
| isolate only | 1.4247 s | 1.95x | 4.5162 s | 1.71x |
| **sample + isolate (shipping default)** | **1.3545 s** | **2.05x** | **4.3006 s** | **1.79x** |
| rust only | 1.1613 s | 2.39x | 3.9398 s | 1.95x |
| sample + rust | 1.0960 s | 2.53x | 3.8584 s | 2.00x |
| isolate + rust | 0.9250 s | 3.00x | 3.2529 s | 2.37x |
| sample + isolate + rust | 0.8483 s | 3.27x | 3.0539 s | 2.52x |

Read separately:

- **`isolate` is the win.** It carries 1.85x on its own — nearly as much as the
  entire Rust port — because it shrinks what the depsgraph re-evaluates at every
  one of the thousands of search barriers, rather than making each evaluation's
  arithmetic faster.
- **`sample` is small but free.** 1.06x alone; it only removes the capture pass,
  which was never the dominant cost. It contributes more in combination (isolate
  1.85x, combined 2.13x) because a pruned rig makes capture a larger share.
- **The two compose.** They attack disjoint costs, so the combination is close to
  multiplicative.
- **The two versions rank Rust differently.** On 4.5 the exact combination beats
  Rust alone on both phases (2.13x vs 2.06x, 1.80x vs 1.64x). On 5.2 Rust alone is
  ahead (2.39x vs 2.05x matching, 1.95x vs 1.79x import), because 5.2's depsgraph is
  cheaper, which shrinks what pruning can save while leaving the arithmetic saving
  intact. This does not change the verdict: the faster of the two on 5.2 is the one
  that is not exact.

### A third idea that was measured and rejected

Replaying the animation without touching the scene frame during the *solve* loop
(the "one depsgraph evaluation" variant, `update`/`replay` in the prototype runs)
measured **neutral to slower** — 2.909 s vs 2.882 s baseline for matching, and
8.05 s vs 7.93 s for import. The solver must re-evaluate after each candidate
pole angle regardless, so removing `frame_set` alone saves nothing. It is not
shipped.

## 3. Shipping result

Default configuration, no Rust, paired against the previous optimized code
(source `3620c9f3` to `be53d8a5`), median of three:

| Blender | Operation | Before | After | Speedup |
|---|---|---:|---:|---:|
| 4.5.7 LTS | Both limbs, 157 frames | 2.9344 s | 1.2900 s | **2.27x** |
| 4.5.7 LTS | Import, 372 frames | 8.1078 s | 4.3075 s | **1.88x** |
| 5.2.1 LTS | Both limbs, 157 frames | 3.0321 s | 1.5001 s | **2.02x** |
| 5.2.1 LTS | Import, 372 frames | 8.1249 s | 4.6645 s | **1.74x** |

Key and whole-rig pose fingerprints are identical before and after in every
phase on both versions.

## 4. Verdict on Rust

**Keep it, opt-in and experimental; do not ship it enabled, and do not delete it.**

- It is no longer the only way to get most of that speed. `sample + isolate`
  reaches 2.02-2.27x while remaining exact, which the Rust path cannot claim.
  Rust alone is still slightly ahead on 5.2 (2.39x), but only by giving up
  exactness, which is the requirement that decides this.
- It is not unfixable, but fixing it means reimplementing Eigen's SVD arithmetic
  bit for bit, degenerate paths included. That is a large, separate effort.
- It still composes usefully: stacked on the exact optimizations it reaches
  3.21x matching / 2.23x import. Deleting it would throw away working,
  benchmarked infrastructure that becomes shippable the moment the SVD work is
  done.

Selection policy is unchanged from the previous report:

- no override / `SUB_NATIVE_IK=0` — exact Blender backend (default)
- `SUB_NATIVE_IK=1` — native candidates verified component by component against
  Blender, Blender's matrices used; exact but about 20% slower than the default
- `SUB_NATIVE_IK=experimental` — unverified native results; must not be used when
  exact matching is required

## Exactness coverage for the shipped path

`sample` and `isolate` both fall back to the ordinary scene evaluation whenever
their guards cannot prove equivalence: unsupported handlers, NLA or multi-slot
actions, non-`REPLACE` blending, unmuted constraints on sampled bones, duplicate
or foreign F-curve channels, pose-dependent drivers, transformed objects with
constraint stacks, non-legacy IK solvers, auto-IK, and any pruning that would
alter a retained rest matrix.

The fast path is additionally gated to whole-animation, keyed, batched matching of
at least 16 frames on Blender 4.5 and 5.2 (`bpy.app.version[:2] in {(4, 5), (5, 2)}`),
the two versions where exactness was verified. Blender 4.4 and any future 5.x keep
the previous optimized path until they are verified the same way; widening that gate
is the obvious next step.

Verified exact on both 4.5.7 and 5.2.1: 12 scenarios each (`normal`, `stretch`,
`animated_stretch`, `arm_pull`, `foot_controls`, `inheritance`, `parent_scale`,
`object_scale`, `handler`, `no_keys`, `current`, `rematch`) plus an
animated-object case, the batch-matching and mesh-deferral regression suites,
and the 48-row factorial fixture comparison above.

## Artifacts

- `.tests/benchmarks/position_fast_factorial_45.json`, `..._52.json` — 48 factorial
  rows per version with fingerprints and implementation hashes
- `.tests/benchmarks/position_production_fast_45.json`, `..._52.json` — paired
  production runs
- `.tests/benchmarks/position_strategies_45.json`,
  `position_strategies_final_45.json` — prototype-stage strategy comparisons,
  including the rejected replay variant
- Harnesses: `tests/benchmark_ik_fast_factorial_blender.py`,
  `tests/benchmark_ik_strategies_blender.py`, `tests/benchmark_ik_replay_blender.py`
- Tests: `tests/test_ik_match_fast_blender.py`,
  `tests/test_ik_isolated_strategies_blender.py`,
  `tests/test_ik_direct_exact_blender.py`, `tests/test_native_ik_singular_blender.py`
