# Fresh Shy Guy foot IK: actual-workflow diagnosis

Blender 5.2.1 LTS, Windows, current ik-upgrades checkout, Rust explicitly disabled.
Freshly import `Shy-Guy-Moveset/romfs/fighter/pacman/model/body/c40`, remove
existing IK using the operator's default bake setting, create new foot IK,
enable legs, and import `motion/body/c40/a00wait1.nuanmb`. The new-foot-IK
position dialog is suppressed in the background process; matching is measured
explicitly after animation import. Model files are copied to a disposable test
directory before import; original assets are not modified.

The resulting rig has 170 bones, 37 mesh objects, two selected leg chains, and
240 animation frames. Both direct FK sampling and isolated solving activate.
There is no fast-path fallback in this clean reproduction.

## Paired results

Three runs per variant and operation, alternating order. Both variants use the
current code and batched matching; `_fast=False` disables direct sampling and
isolated solving. This comparison measures those optimizations, not a rollback
of all previous optimizations. Each pair starts from the same saved fixture.

| Operation | Fast paths off | Fast paths on | Speedup |
|---|---:|---:|---:|
| Automatic IK matching during animation import | 3.9115 s | 1.8537 s | 2.11x |
| Position IK Controls, legs, whole animation | 3.9671 s | 1.8361 s | 2.16x |

All six pairs preserve exact key-coordinate/interpolation and whole-rig pose
fingerprints. Measurements are headless and exclude interactive viewport redraw
and dialog/undo overhead; a longer live-session delay needs live-session evidence.

## Where the remaining delay goes

Explicitly timed calls to `view_layer.update()` inside the existing search
scheduler, with the default Blender solver:

| Operation | Total | Search graph updates | Time inside updates | Share |
|---|---:|---:|---:|---:|
| Import | 1.9486 s | 4,292 | 1.2514 s | 64.2% |
| Match | 1.7369 s | 4,292 | 1.1398 s | 65.6% |

These are separate instrumented runs, not the median paired timings above.
The import cProfile run spent 1.932 s of 2.028 s inside the IK-refresh stage;
`import_model_anim` itself took 0.089 s. The animation file loader is therefore
not the main cause of this pause.

cProfile attributes substantial RNA/C evaluation time to `evaluate_steps`' own
time instead of displaying an obvious `view_layer.update` entry. The explicit
timer establishes that this is graph-update time, not all Python orchestration.
The earlier Phase 3 report profiled experimental Rust and cannot establish the
remaining bottleneck, or an optimization ceiling, for the default exact backend.

The present change halves the wait; it does not make matching interactive.
Further work should measure reducing the cost of these existing candidate
evaluations while preserving the search's arithmetic and order. Changing candidate
selection, or enabling unverified Rust, would not meet the exact-output condition.
No production solver behavior was changed during this diagnosis.

## Reproduce

Run with `tests/run_blender_test.py --blender <Blender 5.2 executable>`:

1. `tests/reproduce_shyguy_ik_blender.py` — original workflow and activation trace.
2. `tests/benchmark_shyguy_match_blender.py` — paired timings, fingerprints, profiles.
3. `tests/profile_shyguy_updates_blender.py` — explicit search-update timing.

Artifacts under `.tests/benchmarks/shyguy_ik_repro/`: `diagnostic.json`,
`paired.json`, `graph_time.json`, `import_profile.txt`, `match_profile.txt`,
`fresh_foot_ik.blend`, and `matched_wait.blend`. Profiles and full scene fixtures
are local diagnostic artifacts and are not included in the source distribution.
