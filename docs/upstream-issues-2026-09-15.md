# Three failures in upstream `106b234..d0afdde` — 2026-09-15

All three reproduce on a **pure `upstream/animation-workflow` checkout** at
`d0afdde` with no local commits, so none is a merge artefact and none touches
the IK path. All three are fixed locally; this records what each actually was,
because in two of the three the obvious diagnosis was wrong.

Verified on Blender 4.5.7 and 5.2.1.

## 1. `test_component_matching_blender` — the failure injection stopped injecting

`d0afdde` added analytic matching paths (`_fit_transform_sliders`,
`_match_eyes`, `_match_look_target`) alongside the iterative `_fit`, which is
now reached only when `fit_controls and fit_names_fallback`. Those paths cover
every component kind the test builds, so `_fit` is never called and patching it
injected nothing — the block failed on its own
`AssertionError('Failure injection did not run')` while verifying no rollback at
all.

**Fix:** inject into `_match_look_target` instead. It runs for the test's
`LOOK_TARGET` component, and runs after `_helpers` has installed the temporary
input overrides that the rollback being checked has to undo.

## 2. `test_paired_raw_export_blender` — the rig snapshot was not deterministic

**Failed on 4.5 only; 5.2 passed.**

Not an ordering bug, despite `verify_raw_first` and the commit message. The raw
file genuinely is written before the bake. The payload simply differed between
two exports of the same rig, in five places:

```
/rig/data_props/sub_face_picker
/rig/data_props/sub_helper_bone_data
/rig/data_props/sub_swing_data
/rig/object_props/sub_shpc
/rig/object_props/sub_floor_contact/body_target
```

Each is an add-on PropertyGroup pointer, **absent** from the first snapshot and
present-but-empty in the second. (An early read of this reported them as `null`
in the first payload — that was an artefact of diffing with `dict.get`, not a
null in the file.) These pointers are materialised lazily: a rig whose swing
data nobody has touched has no such key, and one where something merely *read*
it has an empty one. Two exports straddling any such read disagree.

**Fix:** `raw_rig.prune_empty`, applied to `props()`. Recursively drops mappings
that carry no values, so an absent empty group and a present empty group
serialise the same. Restore-safe: `set_props` only assigns the keys a snapshot
carries, so both cases already left the property at its default.
`test_raw_rig_roundtrip_blender` still passes.

## 3. `test_face_expression_raw_blender` — the test did not key the way the add-on keys

**Failed on both versions.** Three hypotheses were wrong before the real cause
turned up; worth recording so nobody re-walks them:

- *Interpolation mode isn't round-tripping.* It is —
  `[(1.0, 1.0, 'LINEAR'), (3.0, 2.0, 'LINEAR')]` on both source and restored.
- *The `X if choice==N else 0` → `X)*(choice==N)` migration left the two
  construction paths with different driver forms.* It didn't — every driver
  expression is character-identical between the two rigs.
- *The restored rig is structurally different.* It isn't — variable
  definitions, weight-bone poses, constraints, parents and rest lengths all
  match.

The actual cause: the test keys `sub_face_expression` with a bare
`keyframe_insert`, which interpolates. Two keys at choice 1 and choice 2 leave
**frame 2 holding 1.5**, and the driver form is `strength*(choice==1)` — so at
1.5 *neither* pose is selected and each rig falls through to whatever leftover
unkeyed pose it happens to have. The source rig still carried
`Jaw.location.x = 0.4` from `pose('CAPTURE','Frown')`; the freshly restored rig
did not. The comparison was measuring test setup, not the round trip.

The add-on already gets this right: `component_matching` writes the channel
through `PoseKeyWriter(obj, interpolation='CONSTANT')` precisely because the
value is a discrete choice. **No product change was needed.**

**Fix:** key `CONSTANT` in the test, matching production. Frame 2 then holds
choice 1 unambiguously and the round trip is what gets measured.

## Also failing, but not from this range

`test_components_lifecycle_blender` fails on pure upstream at `106b234` too and
is recorded as known-red rather than a regression from these four commits. It
asserts `len(controllers) == 2`. Untouched here.
