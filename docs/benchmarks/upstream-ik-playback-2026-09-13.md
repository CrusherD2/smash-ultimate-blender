# Upstream IK playback changes, reviewed and partially adopted

Date: 2026-09-13
Upstream: `CrusherD2/smash-ultimate-blender@animation-workflow`, three commits
ahead of our merge base `089a760`.

## What the contributor's number actually measures

The reported "30-frame headless test improved from 0.61s to 0.10s" is
`PLAYBACK_SECONDS` from `tests/profile_ik_reference_blender.py`, which upstream
added in `ec2de9b`. It times 30 `scene.frame_set` calls on a private reference
blend (`SUB_REFERENCE_BLEND`, default `~/Downloads/Untitled3.blend`).

The 0.61s baseline is a regression upstream introduced one day earlier, in
`5916353`:

* `5916353` gave `_set_ik_bone_visibility` a `sub_independent_ik` branch and
  called it from the `frame_change` handler `_sync_ik_fk_visibility` for every
  independent-IK armature, on every frame. The branch assigns `bone.hide`
  unconditionally. Each write tags the `Armature` datablock, so every frame
  re-evaluated the whole pose, IK solver included.
* `ec2de9b` fixed it two ways: write `bone.hide` only when the value changes,
  and cache `(data pointer, bone count, arms bucket, legs bucket)` per object so
  the handler skips the pass entirely when nothing changed.

**This does not apply to us.** At `089a760`, and therefore on
`animation-workflow` here, `_sync_ik_fk_visibility` does a plain `continue` for
`sub_independent_ik` armatures and `_set_ik_bone_visibility` has no
independent-IK branch at all. We never do the per-frame work that produced the
0.61s, so there is no 6x waiting to be recovered. Taking `ec2de9b`'s two hunks
alone would be a no-op; taking them together with `5916353`'s feature would add
the work and then guard it.

## What we did adopt

`ec2de9b` also prunes zero-weight pull constraints in `ik_channels.wire()` and
`ik_channels.wire_arm_pulls()`. Both build `TRANSFORM` constraints whose
`to_max_*` is a geometry-derived weight, and both produce weights that are
exactly zero at chain endpoints:

* `wire()` — the chain root has `distances[0] / total == 0.0`, so its
  `PULL_TARGET` and `PULL_END` constraints contribute nothing.
* `wire_arm_pulls()` — `u == 0` at both the chain root and the chain end, so all
  four `SUB IK Arm Pull` terms contribute nothing at those bones.

A zero `to_max` contributes nothing at any influence, so removing the
constraint and its scripted influence driver is exact, not an approximation.
This is independent of the visibility regression and applies cleanly to our
`ik_channels.py` (our branch's changes to that file all start below `wire()`).

## Measurements

`tests/benchmark_ik_playback_blender.py` (added here), Blender 4.5.7,
`.tests/benchmarks/ik_apply/out/baseline.blend`, three paired runs in
alternating order, 30 `frame_set` calls after a 3-frame warmup.

| variant | constraints | drivers | run 0 | run 1 | run 2 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| before | 92 | 68 | 0.0668 | 0.0680 | 0.0666 | 0.0671 |
| after | 68 | 44 | 0.0628 | 0.0632 | 0.0637 | 0.0632 |

24 constraints and 24 scripted drivers removed, on a 131-bone rig. Playback is
5.8% faster and the direction holds in all three pairs. The absolute gain is
small because this fixture is much lighter than the reference rig upstream
profiled; the removed count scales with chain count, not rig size.

`tests/benchmark_position_ik_blender.py` with
`SUB_MATCH_COMPARE_SOURCE`, phases `BOTH` and `CURRENT`, two runs: the `keys`
and `poses` fingerprints are identical before and after, confirming no
behaviour change. Match timing is unchanged (`BOTH` 1.30s before, 1.33s after --
within noise); the match path does not depend on these constraints, so the win
is playback only.

## Not adopted

* `5916353` / `ec2de9b` visibility work -- see above.
* Correction bones (`BL_SUB_IK_MATCH_`), progressive scale, per-target custom IK
  removal, `control_appearance.py`, `custom_components.py`, `rig_export.py`.
  These are features, not performance, and they touch `ik_channels.py` in the
  same regions our native solver work rewrote. They need a separate merge.
