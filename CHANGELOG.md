# Changelog

Adds motion-list editing, live floor contact, reverse-foot and custom IK controls,
per-model animation folders, and contextual panel help. Substantially speeds up IK
matching and baking; fixes animation export state restoration, Blender 4.x F-Curve
handling, and several saved-rig and floor-contact edge cases.

> Add-on version 4.5.0 → 4.6.0. Supported on Blender 4.4 through 5.x.

## New features

### Motion-list integration

**Ultimate Motion List**, under Armature Data → Ultimate Animation Data, edits the
entry associated with the active action and can update it after a successful
animation export.

- Reads and writes `motion_list.bin`, `.yml`, and `.yaml` without an external
  converter
- Detects the nearest motion list beside an animation or up through its `motion`
  directory, with an explicit path override when needed
- Stores blend frames and Turn, Loop, and Move flags per action; a `Cancel Frame`
  timeline marker supplies the cancel frame
- Resolves Hash40 values through ParamLabels and sibling YAML, writes readable YAML
  labels, preserves unrelated fields, validates changes before export, and creates
  a first-write `.bak`
- Auto-syncs when the active action changes and leaves an existing entry untouched
  until its values have been synced or edited

### Live floor contact and reverse-foot IK

- **Live Floor Contact** protects calibrated heel, toe, palm, or finger points from
  crossing a world-Z floor while posing, playing, or scrubbing
- Per-limb planting, automatic marker-based planting, contact softness, horizontal
  resistance, floor alignment, rotation locking, and optional `Trans` height
  adjustment are driven non-destructively without baking or changing stretch keys
- Calibrations can be mirrored and stored with Armature Collection Presets; helpers
  begin hidden and all solver wiring is removed cleanly
- **Reverse heel lift:** rotate `FootRollIK` while leaving `FootIK` and `ToeIK`
  stationary to move the heel/ankle around the grounded terminal toe. `ToeIK`
  remains an independent rotation control for that toe
- Multi-joint feet gain **ToeBendIKL/R** for independent articulation between
  the foot and proximal toe, while the terminal toe remains anchored. Neutral
  bend preserves existing heel lift; the additional control and internal seed
  participate in matching, keying, scoped removal, and baking
- Toe-chain discovery follows parenting regardless of Blender's **Connected**
  flag. The deepest toe descendant is the pivot: `ToeL → BaseToeL` grounds
  `BaseToeL`, and longer chains ground their final toe bone. Equal-depth branches
  use a stable name tie-break because a single roll control has one pivot
- Corrected the pivot coordinate space when FK and IK foot rest axes differ.
  Fresh IK creation and matching apply the correction automatically; removed the
  separate repair button. Superseded toe constraints are cleaned up on upgrade
- Floor contact now shows enable, height, and per-limb Plant/Release controls;
  tuning lives under **Advanced**. Release clears toe pinning, and backward rolls
  protect the heel from penetrating the floor even when the toe is pinned

### Adaptive and custom IK

- **Stretch Chain** distributes an enabled IK stretch offset across the complete
  parent chain without scaling it; the root remains anchored
- Each arm chain has an independent, keyframable **ArmIK Pull** influence for
  drawing its bend bone toward the hand target during full-chain stretch
- **Custom IK Bones** creates a non-overlapping parent-chain setup from a selected
  root, bend bone, and endpoint. Custom chains use the existing Arms or Legs IK/FK
  switch and participate in matching, baking, removal, and floor-contact repair
- Custom-chain definitions can be saved and loaded as portable JSON presets

### Workflow and interface

- Animation-folder lists now belong to each armature and persist in the `.blend`;
  selecting an armature or one of its skinned meshes restores its folders and active
  selection without substituting a different costume directory
- Ultimate-tab panels provide contextual **?** links to the relevant README or
  focused guide, including nested and dynamically registered panels
- Magic Exo Skel is grouped inside Model Tools, and Expy mapping/binding plus all
  retargeting sections are kept together inside Retargeting

## Performance

- IK matching and baking use cached pose math and bulk F-Curve reads/writes, share
  evaluations across independent limbs, and preserve interpolation on untouched keys
- Finger-slider baking uses the same bulk path and remains compatible with Blender
  4.x action APIs
- Across Blender 4.4, 4.5, and 5.2 test runs, the Bake & Remove IK speed improved
  by around **11.6×**
- Pole refinement now converges in 12 steps with unchanged measured worst-frame
  fidelity and approximately **1.18×** faster matching
- Whole-animation matching samples FK from F-Curves instead of stepping the scene
  frame, and runs the pole search on a minimal isolated copy of the rig containing
  only the solver's dependency closure. Both fall back to ordinary scene evaluation
  whenever their guards cannot prove equivalence, so output is bit-for-bit identical
- Together these make matching about **2.27×** faster on Blender 4.5 and **2.02×**
  on 5.2, and animation import with active IK about **1.88×** and **1.74×** faster
- These fast paths now also cover single-chain matches, not only multi-limb
  batches; matching a lone leg or arm can reach the same sampled/isolated path
  a two-limb match does
- `SUB_IK_DIAG=1` reports per-stage timings (sampling, isolation, placement,
  the pole search, and writing keys) for a match, for diagnosing slow rigs
  without instrumenting the code by hand
- Fast-path rejections now name the specific reason they fell back (a foreign
  frame handler, an unsupported constraint, a muted solver, and so on)
  instead of a single generic no
- Three candidate reductions to the isolated clone's dependency graph
  (dropping unused action channels, collapsing B-Bone segments, and
  unparenting ancestor bones that only carry inherited pose) were measured
  against the exact baseline on a 170-bone, 240-frame fixture and rejected:
  the rig's existing dependency closure already prunes 170 bones to 20 before
  any of them run, one bought no measurable speed, and another was twice as
  slow because it forced a full fallback. None were adopted; see
  `docs/benchmarks/isolated-dependencies-2026-09-13.md` for the measurements
- A bundled Rust accelerator for generated two-bone chains is now **on by default**
  on Windows x64 under Blender 4.5 and 5.2, roughly halving import and match times
  again on top of the fast paths above. It was previously off because its bar was
  bit-identity with Blender's solver, which it could not claim on near-straight
  chains; it was adopted against an outcome-based gate instead, after 28 corpus
  runs across two rigs, two animations and both supported Blender versions each
  produced poses identical to the ones Blender's backend produces — including a
  clip generated specifically to be near-straight, where the accelerator's own
  guards handed the hardest chain-frames back to Blender and the composed result
  still matched. Unsupported platforms, Blender versions, rig features and
  constraint setups keep Blender's path exactly as before, as does every existing
  per-frame fallback; see `docs/benchmarks/native-default-2026-09-13.md`
- `SUB_NATIVE_IK=0` turns the accelerator off everywhere, `SUB_NATIVE_IK=1` still
  verifies every native candidate against Blender (exact, but slower than either
  default), and `SUB_NATIVE_IK=experimental` remains accepted as the explicit
  spelling of what an unset variable now does. Because a corpus is evidence and
  not a proof, **results are no longer guaranteed bit-identical to Blender's
  backend on degenerate geometry** — synthetic near-collinear poses exist where
  the two differ, in matrix elements whose exact value is zero. Use
  `SUB_NATIVE_IK=1` or `=0` where exactness must be guaranteed rather than
  measured
- Add-on Preferences now has a **Use Native IK Accelerator** toggle, on by
  default, for turning the accelerator off without setting an environment
  variable before launching Blender. An explicitly set `SUB_NATIVE_IK` (even
  `=1` or `=experimental`) always overrides the preference; a rig whose
  guards decline heavily is the main reason to untick it, falling back to
  Blender's own solver

## Bug fixes

- **Animation export** — single and batch exports run synchronously without modal,
  timer, or progress UI state, restore the active actions, slots, frame/subframe, and
  auto-key setting even after failures, and clear stale SAP data between batch clips
- **F-Curves** — fixed creation against Blender 4.x layered-action APIs, fail clearly
  when a transform basis cannot be derived, and retain untouched key interpolation
  during bulk channel writes
- **IK rigs** — saved rigs are upgraded with missing positional outputs without
  rematching their animation; custom chains are removed with their selected switch
  group, and floor contact safely skips incomplete legacy solver chains
- **Animation selection** — checkbox dragging and filtered Shift-range selection stay
  aligned with the visible action list

## Other changes

- Removed the redundant **Bake and Exit** option from the Expy Kit bake dialogs
