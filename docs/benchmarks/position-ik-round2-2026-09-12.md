# Position IK Controls: second optimization pass

This pass preserves the previous match results exactly. It does not change
the pole search, its iteration count, tolerance, or floating-point summation
order. It is an optimization of the existing matcher, not a new claim that
two-bone IK reproduces every possible FK pose perfectly.

## Paired benchmarks

Background Blender 5.2.1 LTS on Windows, same real rig fixtures as
[round one](position-ik-2026-09-12.md). Three before/after pairs per operation,
alternating variant order between repetitions in one Blender process. Each
measurement reopens the original fixture and recreates its controls. Setup,
startup, and validation are excluded; animation import includes automatic
IK rematching. No other Blender tests or benchmarks ran concurrently.

“Before” here is the already optimized matcher from round one. Medians:

| Operation | Before this pass | After | Time reduction |
| --- | ---: | ---: | ---: |
| Match arms and legs, 157 frames | 4.345 s | 3.110 s | 28.4% |
| Match arms only, 157 frames | 3.959 s | 2.903 s | 26.7% |
| Match legs only, 157 frames | 4.090 s | 2.993 s | 26.8% |
| Match current frame | 0.068 s | 0.061 s | 9.5% |
| Import with IK, 372 frames | 10.657 s | 8.270 s | 22.4% |
| Match arms and legs with subdivision level 2 | 3.903 s | 2.895 s | 25.8% |

The subdivision case adds a Simple subdivision modifier at level 2 to each
mesh before timing. It is a separate three-pair run, not a direct comparison
of model complexity against the normal run. These remain synchronous,
headless measurements; interactive undo/redraw overhead is not included.

## Changes

1. During multi-frame matching of a verified independent rig, defer downstream
   mesh evaluation. Temporarily disable viewport evaluation only for local mesh
   objects parented to the rig or deformed by its Armature modifier. Preserve
   and restore their visibility flags and imported Smash visibility driver
   mute states, including on exceptions. Meshes with custom visibility drivers,
   keyed visibility, or NLA tracks are left alone. Linked mesh objects and
   rigs that fail the dependency safety check keep the ordinary path.
2. Cache the sampled reference matrix columns for each chain/frame and read
   each evaluated bone matrix once per error probe. The vector operations and
   sums stay in exactly the same order as before.

The profile before this pass spent most of its time in dependency-graph
evaluations during pole refinement. Experiments with only disabling Armature
modifiers or using a cached dependency-graph update did not deliver comparable
improvements; no reduction in solver work was accepted.

## Exactness and restoration

- All **18 before/after pairs** (15 normal, three subdivision) have identical
  key-coordinate/interpolation hashes and identical whole-rig pose hashes,
  sampled over every frame. These are exact comparisons, not tolerance tests.
- Serial-versus-batched regression tests still report **0.0** maximum
  deform-bone matrix difference for arms, legs, and both.
- `test_ik_match_mesh_deferral_blender.py` compares keys, all pose matrices,
  and evaluated mesh vertices with strict equality. It covers an additional
  subdivision modifier, imported animated visibility, custom visibility drivers,
  keyed visibility, NLA, pre-hidden objects, and injected exceptions through
  both the deferral scope and the real matching operation.
- The mesh/visibility/restoration test passes in Blender **5.2 and 4.5**.

The guard prevents geometry deferral when the rig has external/cross-limb
dependencies or pose-dependent drivers. Unusual rigs may therefore see less
improvement rather than taking an unverified shortcut.

## Reproduce

Run `tests/benchmark_position_ik_blender.py` through
`tests/run_blender_test.py`, as in the first report. Set:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:SUB_MATCH_COMPARE_SOURCE = '<saved round-one ik_channels.py>'
$env:SUB_MATCH_LABEL = 'round2_paired'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' tests/benchmark_position_ik_blender.py
```

For the subdivision case, additionally set `SUB_MATCH_PHASES=BOTH`,
`SUB_MATCH_SUBDIVISION=2`, and use another label. Default repetition count is
three. `SUB_BASELINE_BLEND` chooses a version-compatible fixture.

[Raw paired measurements and source hashes](position-ik-round2-2026-09-12.json)
are archived alongside this report. Source hashes normalize line endings.
