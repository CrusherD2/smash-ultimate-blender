# Adaptive IK pole search and a shippable native default — design spec

**Status:** accepted, 2026-09-13
**Builds on:**
- `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md` — where a match spends its time
- `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md` — the acceptance criterion this reuses
- `docs/benchmarks/phase-3-decision-2026-09-13.md` — why cross-frame parallelism was rejected
- `docs/superpowers/specs/2026-09-13-ik-candidate-evaluation-cost.md` — the preceding plan

## Problem

Two problems, one shared cause.

**The fast native path cannot ship.** `native/ik_match` already performs the pole
search without Blender, and is worth roughly 3x on matching and 2.1-2.3x on
import. It is off by default because its correctness bar is *bit-identity with
Blender's solver* — a claim its own README declines to make ("near-straight test
cases still differ", "can change results"). That bar cannot be proved over all
rigs, so the speed sits unusable.

**The default path is still slow, for everyone.** It performs about 4,292
Blender pose evaluations per match, roughly two-thirds of the runtime. The
native work does nothing for users outside Windows x64 on Blender 4.5/5.2 with
the bundled DLL — which is most users.

The shared cause is the definition of correctness. Holding output to *identity
with whatever Blender's fixed 12-step search happened to produce* blocks the
native path and forbids doing less work per frame.

## Approach

Adopt the outcome-based criterion already defined and used in this repo, then
spend it twice: once to make the search adaptive on the default path (helping
every user), and once to make the native path shippable (helping the platforms
it supports).

Three pieces, in order. Each is measurable alone.

1. **The gate.** Generalise the existing residual harness so it can judge any two
   match implementations, and widen the corpus so a verdict means something.
2. **Adaptive search.** Make the stopping rule depend on convergence rather than
   a fixed step count, never exceeding today's work.
3. **Native default.** Re-run the widened corpus against the native backend and,
   if it holds, enable it by default on supported platforms.

## Non-goals

- No new solver. `native/ik_match` exists, is validated on ten configurations,
  and is not being rewritten.
- No cross-frame parallelism. Rejected in `phase-3-decision-2026-09-13.md`:
  the native search is 12% of a match, so perfect 8-core scaling returns 1.12x.
- No full native rewrite of `match()`. That is the 6-8x option and it moves every
  guard and fallback across the FFI boundary. Out of scope here.
- No change to which rigs are eligible for any fast path.
- The playback solver stays Blender's. Matching must invert Blender's IK
  constraint because that is what evaluates the rig when an animator scrubs.

## R1 — The acceptance gate

### R1.1 The criterion

Reuse `native-ik-residual-criterion-2026-09-12.md` unchanged in substance:

- **Residual, per frame.** Sum over limb bones of the squared column differences
  between the solved pose and the FK source. This mirrors `error()` in
  `ik_channels` exactly, column-wise, so orientation and translation carry the
  weight the search gives them.
- **Pose, element-wise.** Equal residual does not prove equal pose; two poses can
  fit equally well. Compare solved matrices element by element and report the
  maximum difference.
- **Engagement assertion.** The run must assert the path under test actually ran.
  A run where guards silently declined must not be able to pass.

### R1.2 The tolerance, and where it comes from

The existing criterion is "no frame fits worse, at all". The native backend clears
it outright. **Adaptive search cannot**, by construction: stopping early accepts
an answer a longer search would have improved.

The tolerance is therefore taken from this project's own precedent. When
`_POLE_REFINE_STEPS` was cut from 18 to 12, the recorded basis was that "the
median limb error moves by nothing measurable on any clip and the worst frame is
identical to five decimals", and 10 steps was rejected for a 0.5% median
regression. That is the standard this project already applied to this exact knob.

A change passes when all of:

- **Worst frame:** no frame's residual exceeds the baseline's by more than 1e-5
  relative to that frame's baseline residual.
- **Median:** the median per-frame residual does not increase.
- **Total:** the clip's summed residual does not increase, so many small
  degradations cannot be traded for one improvement.
- **Pose displacement:** maximum per-bone world-space displacement against the
  baseline is reported for every run, and a change that moves any bone by more
  than 1e-4 world units fails regardless of residual.

Reported alongside, never as pass/fail alone: frames better, frames worse,
frames identical, and the evaluation count.

### R1.3 The corpus

The existing evidence is ten rig configurations of a single animation — its own
author names widening this as the prerequisite for flipping any default. Add:

- The six varied clips already used for the pole-step sweep.
- Shy Guy `a00wait1` on the 170-bone Shy Guy rig, distinct from the 131-bone
  test rig.
- One synthetic near-straight limb extension. Near-collinear geometry is where
  the pole search has least signal and where the native guards decline; it
  belongs in the corpus even if no shipped clip reaches it.

### R1.4 Harness shape

The current harness compares *Blender backend against native backend*. It must
instead compare **any two match implementations**, selected per run, so the same
gate judges adaptive-vs-current and native-vs-Blender without duplication.

## R2 — Adaptive pole search

Today: three seed candidates, then — unless the best already scores below
`_POLE_TOLERANCE` (1e-9, effectively never) — exactly `_POLE_REFINE_STEPS` (12)
golden-section steps, then a best-of-three among the final bracket.

Change **only the stopping rule**:

- Seeds, scoring, summation order and search order are untouched.
- Refine until the bracket is narrower than can move the result beyond R1.2's
  tolerance, or the residual improvement between iterations falls below it.
- **Hard cap at the current step count.** The adaptive search may never perform
  more evaluations than today, so worst-case cost equals today's cost.
- The previous frame's angle remains a seed. Continuous animation should make it
  a strong one, and a strong seed is what lets the bracket collapse early.

### R2.1 The known risk

`_match_chain_steps` records that Blender's solver warm-starts from the previous
evaluation, so the residual depends on the *path* through candidate angles, not
only on the angle. A shorter search may therefore return a *different* answer
rather than a less-refined one, and a previous three-probe analytic fit failed
for this reason.

This cannot be reasoned away; it is what the gate is for. If the corpus shows
early stopping is unsafe on the Blender path, R2 is abandoned there and applied
only to the native path, where solves are stateless and no such coupling exists.
That outcome is an acceptable result of this work, not a failure of it.

## R3 — Native backend on by default

No solver changes. Run the R1 corpus against the native backend on both supported
Blender versions. If it holds:

- Enable the native path by default where it is already gated to: Windows x64,
  Blender 4.5 and 5.2, bundled DLL present, existing dependency guards passing.
- Keep verification mode (`SUB_NATIVE_IK=1`) available.
- Keep every per-frame guard and fallback exactly as they are.
- Add an environment override to force it off.
- Changelog states plainly that results are no longer guaranteed bit-identical to
  the Blender backend on degenerate geometry.

If the widened corpus does not hold, the default does not flip and the corpus
findings are recorded. That is a valid outcome.

## Global constraints

- Blender 4.4, 4.5, 5.0, 5.1 and 5.2 keep working. Fast paths stay gated to
  `bpy.app.version[:2] in {(4, 5), (5, 2)}`.
- No new third-party dependency; no new Rust dependency.
- Every existing guard and fallback is preserved. This spec loosens an acceptance
  criterion, never a safety check.
- The graph-update count is no longer an invariant — R2 exists to reduce it — but
  every reduction must be attributable and gated. Report it for every run.
- `tests/test_ik_match_fast_blender.py` fails on Blender 4.4 for a pre-existing,
  unrelated reason (it asserts unconditionally that version-gated-off fast paths
  engaged). Out of scope; do not chase it.
- Work happens in the `ik-adaptive-search` worktree. The `animation-workflow`
  branch is not touched.
