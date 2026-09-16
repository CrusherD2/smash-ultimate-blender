# Can the correction barrier be removed? — 2026-09-15

Follow-up to `pole-refine-2026-09-15.md`, which ended by naming the one
regression the correction bones introduced: a whole-animation match went from
157 to 314 depsgraph evaluations, 10–14% slower, because
`_match_chain_steps` now reads the solved pose back out of Blender to compute
the residual. That doc called folding the read into the native path "the next
available speedup" and did not attempt it. This is the attempt.

Harness: `tests/probe_correction_barrier_blender.py`, which substitutes an
instrumented `_match_chain_steps` the way the benchmarks do. 632 chain-frames
(157 frames × 4 chains), Blender 4.5.7 and 5.2.1, shipped default native mode.
Raw JSON in `.tests/benchmarks/native-search-pose-<version>.json`.

## Verdict: declined. The 10% is not recoverable without a decision that is not mine to make

Two barriers per frame, one per purpose:

| barrier | why it exists |
|---|---|
| capture | mutes the IK constraint and evaluates, so `Solver` can read the pre-IK pose |
| correction | evaluates at the chosen pole angle, so the residual can be read back |

Neither survives scrutiny intact, and neither can be removed on the evidence
below without giving something up.

## Finding 1: the native search's own pose *is* Blender's, bit for bit

`Solver.search` already returns `(angle, matrices)` and `_match_chain_steps`
uses `found[0]` and discards `found[1]`. If that pose equals Blender's, the
correction could be computed from it directly.

**It does. 632 / 632 chain-frames bit-identical on both Blender versions** —
`pose_delta_worst` exactly `0.0`, and the correction basis the two routes would
key differs by exactly `0.0`.

This was previously unverified, and worth stating precisely because it is easy
to assume the corpus already covered it. It did not:

- Verification mode (`SUB_NATIVE_IK=1`) compares `sub_ik_solve_many`'s
  per-candidate output against Blender bit-for-bit — but the native-search gate
  requires `not verifying()`, so `search()` never runs in that mode.
- `tests/test_native_ik_search_blender.py` compares the keyed pole **angles**
  across the three paths, not the returned pose.
- Nothing consumes `found[1]`, so `native-default-2026-09-13.md`'s "every
  solved pose identical to Blender's" holds regardless of what it contains.

So the fact is new, and it is the one piece of good news here.

## Finding 2: the endpoint bone defeats it

`Solver` is built over `solver[:-1]`. The endpoint bone is outside the native
model entirely, and its correction is the **largest of the chain** —
`endpoint_translation_worst` 0.4135, which is essentially the whole 0.4154
pre-correction drift. It cannot be skipped.

The obvious derivation — that the endpoint sits at the parent solver bone's
tail, which the native pose already gives us — **is wrong**:

| measure | worst | median |
|---|---:|---:|
| endpoint vs parent-tail position | 0.3398 | 0.0707 |
| endpoint correction basis 3×3 vs identity | 9.65e-07 | — |

The 3×3 is identity to float32 noise, so the correction really is a pure
translation (which is why `to_quaternion().angle` reads a flat 0°). But the
translation is not the parent's tail: the endpoint carries `SUB IK End
Location` (a world-space `COPY_LOCATION` from the endpoint target) under a
stretch driver, plus the pull wiring, and those put it somewhere else.

Deriving it means modelling the endpoint bone and its three world-space
constraints — and the stretch/arm-pull/foot-control branches that gate them —
inside the Rust solver. That is a real project with its own corpus validation,
not a refactor, and the guard conditions are exactly where it would break
silently. Not attempted.

**Because the barrier is one per frame shared across all four chains, computing
`path[:-1]` natively saves nothing while `path[-1]` still needs it.** That is
what kills the cheap version.

## Finding 3: the capture barrier is *nearly* redundant, and "nearly" is the problem

Everything `Solver.__init__` reads at capture time could plausibly be known
arithmetically — the placement step wrote those poses itself, from `matrices`.
Measured against what Blender reports:

| quantity | worst delta |
|---|---:|
| pose-bone `head` vs `matrix.translation` | **0.0** |
| pose-bone `tail` vs `matrix @ (0, length, 0)` | **0.0** |
| chain parent world vs `matrices[parent]` | **0.0** |
| solver bone poses vs `matrices[name]` | 1.14e-05 |
| IK target control vs `matrices[path[-1]]` | 7.63e-06 |

Head, tail and the parent are exactly reconstructible. The poses and the target
are not: `pose_math.apply_world` writes a **float32** basis, and reading
`matrix` back recomposes through float32, so the float64 input does not survive
the round trip. 7.63e-06 is not a coincidence — it is the same float32 quantum
as the match's own residual drift.

Feeding the solver reconstructed inputs would therefore change the solved pose,
and so the keyed corrections, at the ~1e-5 level. In absolute terms that is
harmless: it is the same order as the drift the match already has. But it is
**not bit-identical**, and bit-equality against Blender is the bar this project
has held the native path to throughout — `evaluate_steps` literally compares
with `tuple(a) != tuple(b)`, and the corpus verdict is phrased as "exactly
0.0 on all 28".

Trading that invariant for 10% on one operation is a product decision. It is
recorded here rather than taken.

## What would actually move it

In rough order of cost:

1. **Accept a ~1e-5 output change** and drop the capture barrier. 314 → 157
   evaluations, back to pre-correction speed. Cheap to implement; costs the
   bit-equality invariant. Needs a decision, and a re-run of the residual gate
   with a tolerance rather than an equality.
2. **Model the endpoint bone in Rust** and drop the correction barrier instead.
   Keeps bit-equality. Weeks, not hours, and it widens the native surface into
   the stretch and foot-control branches.
3. **Leave it.** The correction bones bought a 54,000× accuracy improvement for
   10–14% wall time on one operation. That trade is not close.

Option 3 is in force.

## What this does not settle

- One fixture and one rig, 632 chain-frames. The bit-equality of `search()`'s
  pose is strong within that sample and unmeasured outside it; the corpus
  harness would widen it cheaply.
- The float32 round-trip explanation for Finding 3 is inferred from the
  magnitudes lining up with the known quantum, not from reading Blender's
  basis-storage code. If someone wants to act on option 1, confirm it first —
  if some of that 1.14e-05 is something other than storage precision, the
  option is worse than it looks.
