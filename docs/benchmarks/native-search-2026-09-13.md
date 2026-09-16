# Native pole search (Phase 2) — 2026-09-13

Phase 2 of `docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md`: the
per-frame pole search moved out of Python. A chain now costs one `sub_ik_search`
call per frame instead of roughly 28 generator round-trips through `ctypes`.

## Result

Measured with `SUB_NATIVE_IK=experimental`, comparing `SUB_NATIVE_SEARCH=0`
(per-candidate, the previous native path) against `=1` (whole search). Median of
three paired runs per version and phase.

| Blender | Operation | Per-candidate | Native search | Gain |
|---|---|---:|---:|---:|
| 4.5.7 LTS | Both limbs, 157 frames | 1.0213 s | 0.8690 s | **1.18x** |
| 4.5.7 LTS | Import, 372 frames | 3.7679 s | 3.4075 s | **1.11x** |
| 5.2.1 LTS | Both limbs, 157 frames | 1.0704 s | 0.8426 s | **1.27x** |
| 5.2.1 LTS | Import, 372 frames | 3.6412 s | 3.3317 s | **1.09x** |

This is in line with what the profile predicted and no better. The Python search
was about 14% of a match, and removing the per-candidate marshalling on top of it
buys roughly what that share was worth. It does not move the work materially
closer to 10x on its own.

Reading these against the Blender-backend factorial baselines (2.6331 s / 7.2627 s
on 4.5, 2.7749 s / 7.7012 s on 5.2) puts matching around 3.0-3.3x and import
around 2.1-2.3x. Those are cross-series ratios from different benchmark runs, so
treat them as indicative rather than paired measurements.

## Exactness

Established by three independent measures rather than by the benchmark's
fingerprints, for the reason in the next section.

1. **Keyed pole angles.** `tests/test_native_ik_search_blender.py` matches the
   fixture three ways -- Blender backend, native per-candidate, native whole
   search -- and compares every keyed `pole_angle` curve. Identical on both
   versions, with 632 native searches actually performed per run. The test
   asserts the native search ran, so it cannot pass vacuously.
2. **Every pose bone.** `tests/diagnose_search_pose_difference.py` walks all 131
   pose bones at all 157 frames: `KEYS_IDENTICAL True`, `BONES_DIFFERING 0`.
3. **Ten rig configurations.** The residual matrix reports
   `max_pose_difference: 0.0` and zero frames fitting worse, on both versions.

## The bug this round found, and how

The first implementation scored candidates with a float32 dot product accumulated
forwards. `mathutils` does not do that. `Vector.length_squared` goes through
`len_squared_vn`, which squares each component in float32 and then accumulates in
**double**, iterating from the **last** component to the first:

```c
double len_squared_vn(const float *array, int size) {
  double d = 0.0f;
  const float *array_end = array + size;
  while (array != array_end) { d += (double)square_f(*(--array_end)); }
  return d;
}
```

Three differences: the accumulator type, the order, and where the widening
happens. On the plain rig, where the total residual is about 25.7, the rounding
never changed a decision and every single-rig test passed. Under the
`parent_scale` configuration, where the total residual is about 125,208, it
selected a different pole angle on **9 of 157 frames** and moved `KneeL` by
8.8e-04.

Two earlier choices caught it. Widening to ten configurations rather than
trusting one rig surfaced it at all. Comparing **per frame** rather than in
aggregate made it a failure: the native total was *lower* than Blender's
(125208.8786 against 125208.8922), so a sum-based check would have reported an
improvement.

## Benchmark harness limitation: pose fingerprints are process-local

While reviewing these results, `position_search0_*.json` and
`position_search1_*.json` showed identical `keys` fingerprints but different
`poses` fingerprints, which looked like an output regression.

It was not. Running the benchmark **twice with identical settings** in two
separate Blender processes reproduces it:

```
identical settings, two processes:
  keys  same: True
  poses same: False    f8958f985af5  vs  ff2623261522
```

The `poses` fingerprint in `tests/benchmark_position_ik_blender.py` is stable
**within** a Blender process and not **across** processes. `keys` is stable in
both.

This does not invalidate any earlier report. The factorial benchmark and the
paired production runs evaluate all of their variants inside a single process,
which is the comparison the fingerprint supports. It does mean:

- Never compare `poses` fingerprints between separate benchmark invocations.
- To compare two code paths for exactness, either add both as variants inside one
  benchmark process, or compare poses directly as the diagnostic above does.

## Scope

The native search runs only under `SUB_NATIVE_IK=experimental`. Verification mode
(`SUB_NATIVE_IK=1`) deliberately keeps the per-candidate path, because comparing
each candidate against Blender is its entire purpose. A native search that
declines -- any candidate failing to converge, or the geometry guard rejecting it
-- falls through to the unchanged Python loop. The native backend remains off by
default.

## Artifacts

- `.tests/benchmarks/position_search{0,1}_{4.5,5.2}.json` -- paired timings
- `.tests/benchmarks/native_ik/search_pose_diff_4.5.json` -- the all-bones diff
- `.tests/benchmarks/native_ik/residual_matrix_{4.5,5.2}.json` -- acceptance
