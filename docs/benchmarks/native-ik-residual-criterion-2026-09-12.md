# Native backend under the residual criterion — 2026-09-12

Follow-up to `docs/benchmarks/eigen-svd-gate-2026-09-12.md`, which failed the
bit-identity gate. That gate asked whether the native solver's output is
bit-identical to Blender's on an adversarial synthetic suite. This asks the
question that decides shipping: **does the native backend reproduce the FK source
at least as well as Blender's backend, on every frame of real animation?**

## Verdict: PASS, and by more than the criterion required

On the real fixture the native backend does not merely fit equally well. Its
solved poses are **bit-identical** to the Blender backend's, on every frame, on
both supported Blender versions.

| | Blender 4.5.7 LTS | Blender 5.2.1 LTS |
|---|---|---|
| Frames compared | 157 | 157 |
| Frames fitting worse | **0** | **0** |
| Frames fitting better | 0 | 0 |
| Frames identical | **157** | **157** |
| Total residual, Blender backend | 25.731371392383128 | 25.731371392383128 |
| Total residual, native backend | 25.731371392383128 | 25.731371392383128 |
| **Max pose difference** | **0.0** | **0.0** |
| Native solves actually performed | 632 | 632 |

## What was measured

For each backend, the whole animation is matched from the same starting file and
the resulting pose is captured for every limb bone on every frame. Two
comparisons are then made.

**Residual.** Per frame, the sum over limb bones of the squared column
differences between the solved pose and the FK source. This mirrors `error()` in
`ik_channels` exactly — column-wise, so orientation and translation carry the
same weight the pole search gives them. It is the quantity the search minimises,
so "no frame fits worse" is a statement about the property users care about.

**Pose.** Equal residual does not by itself prove equal pose: two different poses
can fit the source equally well. The solved matrices are therefore also compared
element by element. The maximum difference is exactly zero.

The run asserts that the Blender pass created **no** native solvers and the
native pass created more than zero, so a run where the per-frame guards silently
declined cannot masquerade as a pass. 632 native solves occurred in each native
pass.

Test: `tests/test_native_ik_residual_blender.py`. Reports:
`.tests/benchmarks/native_ik/residual_4.5.json`, `residual_5.2.json`.

## Reconciling this with the failed bit-identity gate

Both results are correct; they measure different populations.

- The singular suite is a synthetic adversarial construction: exactly straight
  rest bones, bend angles from 0 to 0.1 rad, right-angle geometry. Its 33
  mismatches all occur in matrix elements whose operands are below 1e-6, the
  largest being 4.37e-08 — the float32 residue of a right-angle rotation, where
  the exact answer is zero. No mismatch there occurs in an element carrying a
  meaningful value.
- Real animation does not dwell on those degenerate configurations. Across 157
  frames and 632 native solves of actual content, the two backends do not differ
  at all.

So the native path's known divergence is confined to float32 noise on
mathematical zeros in synthetic degenerate poses, and does not appear in
practice on this fixture.

## Widened evidence: ten rig configurations, both versions

The single-rig result above was extended across the configurations
`tests/test_ik_match_fast_blender.py` constructs, plus limb subsets, via
`tests/test_native_ik_residual_matrix_blender.py`.

| Configuration | Limbs | Native solves | Frames worse | Max pose difference |
|---|---|---:|---:|---:|
| normal | BOTH | 632 | 0 | 0.0 |
| normal | ARMS | 318 | 0 | 0.0 |
| normal | LEGS | 318 | 0 | 0.0 |
| object_scale (non-uniform scale + rotation) | BOTH | 632 | 0 | 0.0 |
| parent_scale (animated non-uniform parent scale) | BOTH | 632 | 0 | 0.0 |
| inheritance (`ALIGNED` scale inheritance) | BOTH | 632 | 0 | 0.0 |
| stretch (stretch + stretch chain) | BOTH | 632 | 0 | 0.0 |
| arm_pull (0.7) | BOTH | 632 | 0 | 0.0 |
| animated_stretch (toggled per frame) | BOTH | 632 | 0 | 0.0 |
| foot_controls (rotated foot/toe) | BOTH | 632 | 0 | 0.0 |

Identical on **both** Blender 4.5.7 LTS and 5.2.1 LTS: 10 configurations each,
`native_engaged: 10`, `guards_declined: []`.

Every configuration actually exercised the native solver, including ones that
could plausibly have been rejected by the guards -- non-uniform object scale,
animated parent scale, and `ALIGNED` scale inheritance. None of the twenty runs
is a vacuous pass, and in none of them does the native output differ from
Blender's by any amount at all.

Reports: `.tests/benchmarks/native_ik/residual_matrix_4.5.json`,
`residual_matrix_5.2.json`.

## Scope and limits of this evidence

This is one source rig across ten configurations, 157 frames, on two Blender
versions. It is strong evidence that the native backend is safe for content like
this, and it is not a universal proof: every configuration derives from the same
baseline animation, so the frame content itself is not varied. The singular suite demonstrates that inputs exist where the
two backends differ, and the existing per-frame guards and fallbacks remain the
reason that is survivable.

Two consequences follow for anyone acting on this:

1. Enabling the native backend by default is now a defensible decision under the
   equal-or-better-residual criterion, but it should be accompanied by the
   verification mode staying available, and by a changelog note that results are
   no longer guaranteed bit-identical to the Blender backend on degenerate
   geometry.
2. Widening this evidence — more fixtures, more rigs, longer clips — is cheap now
   that the harness exists, and is the right thing to do before flipping the
   default.

## Consequence for the performance work

Phases 2-4 of `docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md` were
halted because the bit-identity gate failed. Under the criterion actually chosen
for this work, they are unblocked: the native solver can carry the whole-animation
drive without degrading the fit on any frame of this fixture.
