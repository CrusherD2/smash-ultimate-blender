# Position IK Controls performance

Measured September 12, 2026 in background Blender 5.2.1 LTS on Windows,
using the existing Sceptile rig/animation fixture. Each operation starts from
a freshly reopened fixture with arms and legs IK enabled. Three runs per
operation and revision; table values are medians. Rig creation, Blender startup,
and validation are outside the timed interval. Import timing includes the actual
animation import and automatic IK rematch. No concurrent Blender benchmarks ran.

| Operation | Frames | Before | After | Speedup |
| --- | ---: | ---: | ---: | ---: |
| Position arms and legs | 157 | 14.952 s | 4.729 s | 3.16× |
| Position arms only | 157 | 7.303 s | 4.686 s | 1.56× |
| Position legs only | 157 | 6.728 s | 4.750 s | 1.42× |
| Position current frame, arms and legs | 1 | 0.109 s | 0.063 s | 1.72× |
| Import animation with IK enabled | 372 | 35.265 s | 12.119 s | 2.91× |

The full-animation dialog operation takes 68% less time on this fixture;
automatic import/rematching takes 66% less time. These are headless operation
times, not measurements of interactive redraw or undo overhead. Long imports
still take seconds, and rigs with custom dependencies may retain serial solving.

## Change

The matcher already had a scheduler that shares dependency-graph evaluations
between independent chains. Its safety predicate still described an older rig:
three-bone chains, simple influence drivers, and direct solver outputs. Modern
stretch drivers, positional arm-pull outputs, reverse-foot/toe controls, and
intermediate bones forced generated rigs into the serial path. Existing pole
keys on unselected limbs also prevented arms-only/legs-only batching.

The predicate now resolves each limb's complete FK, solver, pull, foot, toe,
and descendant dependencies; recognizes generated property-only drivers;
verifies each IK constraint's entire chain; and permits pole-angle animation
on independently owned unselected limbs. It ignores only the output constraints
that matching keeps muted. External targets, cross-limb reads, pose-dependent
drivers, animated custom constraint settings, and incomplete legacy solvers
still fall back. Custom constraint spaces are included in dependency checking.

Neither the pole search, its iteration count, nor its error tolerance changed.
Both the dialog operator and animation-import rematching use this predicate.

## Validation

- All 15 before/after benchmark comparisons produced identical key coordinates
  and interpolation settings across every action channel.
- `test_ik_match_batch_blender.py` compares serial and batched matches from the
  same saved rig/action. Arms, legs, and both produce identical keys and a maximum
  deform-bone matrix difference of **0.0** throughout the animation in Blender
  5.2 and 4.5, using their version-compatible fixtures.
- The same test exercises generated drivers and fallback behavior for cross-limb
  constraints, external targets, pose-reading drivers, animated constraint
  settings, and invalid/incomplete solvers.
- The existing FK-fidelity test passes: worst residual 0.415416, median 0.039412,
  consistent with the fixture's previously recorded arm-matching approximation.

The benchmark also records whole-rig pose hashes, including unkeyed internal
bones. Those hashes differ between revisions, whose initial control-creation
evaluations now differ. They are diagnostic, not a claimed exact-pose check;
the saved-state regression above tests actual deform-bone playback equivalence.

## Reproduction

Use `tests/run_blender_test.py` to isolate Blender's user profile. Before editing,
save a copy of `source/extras/ik_channels.py`. Point `SUB_MATCH_SOURCE` at that
copy and set `SUB_MATCH_LABEL=before`; then run:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' tests/benchmark_position_ik_blender.py
```

Repeat after unsetting `SUB_MATCH_SOURCE` and setting `SUB_MATCH_LABEL=after`.
The benchmark defaults to three repetitions and
`.tests/benchmarks/ik_apply/out/baseline.blend`; `SUB_MATCH_RUNS` and
`SUB_BASELINE_BLEND` override these. The fixture must retain its
`bench_second_anim` path to an available importable animation.

Raw timings and source hashes are in
[position-ik-2026-09-12.json](position-ik-2026-09-12.json).
Source hashes use UTF-8 after universal-newline normalization. Machine-local
logs and the original source snapshot are under `.tests/benchmarks/`.
