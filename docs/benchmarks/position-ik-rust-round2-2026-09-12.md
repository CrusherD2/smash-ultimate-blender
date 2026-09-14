# Rust IK integration and exactness — 2026-09-12

The addon now has a bundled **experimental** Windows x64 Rust accelerator for
independent generated two-bone IK chains on Blender 4.5 and 5.2. It is **disabled
by default**: additional near-straight tests disproved the proposed convergence
guard's exactness. Normal matching/import retain the previously optimized Blender
path. Verification mode is exact but evaluates Blender as well and adds overhead.

## End-to-end experimental benchmarks

Final-code reruns use the geometry guard and explicit experimental/verified mode
selection. Each cell is the median of three paired runs. All 18 pairs match exact
key/interpolation and whole-rig pose fingerprints on the real fixture.

| Version and mode | Operation | Previous optimized code | Native mode | Ratio |
|---|---|---:|---:|---:|
| 4.5.7, experimental | Both limbs, 157 frames | 2.8708 s | 1.3479 s | 2.13× faster |
| 4.5.7, experimental | Import, 372 frames | 7.8861 s | 4.5215 s | 1.74× faster |
| 5.2.1, experimental | Both limbs, 157 frames | 2.9229 s | 1.1799 s | 2.48× faster |
| 5.2.1, experimental | Import, 372 frames | 7.9839 s | 4.3148 s | 1.85× faster |
| 4.5.7, verified | Both limbs, 157 frames | 2.9312 s | 3.5843 s | 22% slower |
| 4.5.7, verified | Import, 372 frames | 7.9153 s | 9.5337 s | 20% slower |

The verified mode's overhead explains why it is not the default either. The
ordinary optimized Blender path remains active. Together with the earlier series,
the report contains 48 exact end-to-end pairs; the singular suite below demonstrates
why these successful fixture comparisons cannot justify enabling raw native results.

### Earlier integration series

The following recorded series predates the additional geometry guard and final
opt-in/verification policy. Its raw source and DLL hashes are retained in the
JSON. These are measured experimental speedups on this fixture, **not enabled
production speedups or a claim of universal exactness**.

These are complete operator/import timings, including capture, conversion,
search, FFI calls, fallback, key writing and restoration. Each value is the median
of three paired runs on the same machine, alternating before/after order.
The native library is loaded while preparing the rig before the timed operation;
library loading is therefore excluded. No other Blender tests or compiler jobs
ran concurrently with the final benchmark series.

| Blender 4.5.7 LTS operation | Previous optimized code | Rust, one thread | Speedup |
|---|---:|---:|---:|
| Both limbs, 157 frames | 2.5441 s | 1.2208 s | 2.08× |
| Animation import, 372 frames | 6.9681 s | 4.2083 s | 1.66× |

| Blender 5.2.1 LTS operation | Previous optimized code | Rust, one thread | Speedup |
|---|---:|---:|---:|
| Both limbs, 157 frames | 2.9998 s | 1.2126 s | 2.47× |
| Arms, 157 frames | 2.7576 s | 0.8915 s | 3.09× |
| Legs, 157 frames | 2.8711 s | 0.9541 s | 3.01× |
| Current frame, both limbs | 0.0568 s | 0.0479 s | 1.19× |
| Animation import, 372 frames | 7.8309 s | 4.2244 s | 1.85× |

Every before/after pair compares all output key coordinates/interpolation and
every pose-bone matrix at every frame using exact fingerprints. The native
implementation retains the existing pole-angle candidate order, previous-frame
candidate, score arithmetic and key writer. These speedups are relative to the
already optimized implementation, not the original slow implementation.

The earlier isolated-kernel timings are not estimates of end-to-end speedup.
They exclude the substantial sampling, key writing and dependency-graph work
that still has to happen outside candidate evaluation.

## Threading result

| Blender 4.5 native thread count | Matching median | Import median |
|---|---:|---:|
| 1 | 1.2208 s | 4.2083 s |
| 4 | 1.3362 s | 4.4700 s |

Four threads were about 9% slower for matching and 6% slower for import. Live
batches contain at most four very small solves; dispatch overhead outweighs
parallel compute savings. One thread is therefore the default. Four-thread
batching remains available through `SUB_NATIVE_THREADS=4` and gives identical
results. Larger detached benchmark batches do benefit from four threads.

## Numerical fixes and acceptance boundary

The initial prototype's zero exact matches did not establish that all the error
was in Rust's solver. The diagnostic boundary was also wrong:

1. `mathutils` matrix multiplication accumulates float products in double;
   Blender's internal 3×3/4×4 operations use different float summation orders.
2. Python matrix inversion differs from the reciprocal-based BLI 3×3 inverse and
   Eigen packet 4×4 inverse used by the IK plugin.
3. Blender rescales only the X/Z axes when applying IK basis changes.
4. Blender's pole angle is a float, so its sine/cosine calls select float
   overloads before promotion into Eigen's double vectors.

Correcting those differences produced exact results for all 1,884 fixed-angle
evaluations and then all 11,304 real-search evaluations in the diagnostic
comparison on Blender 4.5 and 5.2. Input conversion and pose reconstruction were
then moved into Rust and verified through the complete matching/import path.

The unrestricted solver was also tested on synthetic poses with randomized
rotations, nonuniform scale, goals and poles. That exposed significant drift on
nonconverging trajectories, and tiny differences on some slowly converging ones.
Merely falling back when the maximum iteration count was reached was insufficient.
The first integration therefore accepted only solves that converge within
Blender's minimum twelve iterations. It did not use a visual tolerance or epsilon
comparison. Longer solves triggered a normal Blender
evaluation at the current angle, and the rest of that chain/frame stays on Blender.

For each of Blender 4.5.7 and 5.2.1, that integration's stress test evaluated 10,000
randomized poses at four angles:

| Result per Blender version | Count |
|---|---:|
| Native results accepted | 5,620 |
| Accepted results exactly equal to Blender | 5,620 |
| Longer solves routed back to Blender | 34,380 |
| Accepted mismatches | 0 |

This adversarial distribution is not representative of normal animation matching;
it intentionally includes arbitrary scales and targets. Passing these tests is
evidence of compatibility within the tested scope, not a universal mathematical
proof for every possible input. Eigen's full SVD arithmetic is not reproduced
bit for bit, and the unrestricted diagnostic solver remains unsuitable as a
general drop-in replacement.

### Counterexample and final selection policy

A further suite uses exactly straight rest bones, seven bend angles from zero
through 0.1 radians, seven goals and five pole angles (245 cases per version).
Perfectly straight cases already disproved the twelve-iteration rule. A new
geometry guard rejects nearly collinear starts and degenerate pole frames, but
32 of 40 remaining native candidates still differ from Blender on each version;
205 cases fall back. The largest difference in this suite is approximately
3.55e-15. Small is not exact, so increasing a threshold is not a valid solution.

The final policy is therefore:

- No override, or `SUB_NATIVE_IK=0`: use the optimized Blender backend.
- `SUB_NATIVE_IK=1`: compare every candidate with Blender component by component
  and use Blender's matrices. All 245 singular-suite cases per version pass exactly.
- `SUB_NATIVE_IK=experimental`: opt into the unverified native experiment; it can
  change results and must not be used when exact matching is required.

Shipping native speedups under the exact-output requirement needs a compatible
implementation of Eigen's complete SVD arithmetic, including degenerate paths.
Convergence and geometry heuristics cannot replace that work. Multithreading
does not fix numerical compatibility.

## Integration and failure handling

- The original dependency-safety checks run before enabling native matching.
- Per-frame checks reject custom solver constraints, IK locks/limits/stiffness,
  rotational targets, stretch, alternate spaces and unsupported chain lengths.
- Workers receive detached numeric data and make no Blender API calls.
- A failed native batch falls back to Blender at the same candidate angles.
- Missing/incompatible libraries preserve the Python/Blender implementation.
- Handles, output constraint states, current frame and deferred mesh visibility
  are restored during failure cleanup.

Rust numerical/FFI tests and a portable captured-matrix golden test pass. Blender
backend-selection and cleanup tests pass on 4.5 and 5.2. Existing batch matching
and mesh-deferral regression checks also pass after integration.

## Reproduction and artifacts

Build with `python native/ik_match/build.py`. The bundled DLL is built with
Rust 1.89.0 and locked dependencies; sources and license notices are included.
See `native/ik_match/README.md` for test and benchmark commands.

`position-ik-rust-round2-2026-09-12.json` contains the raw paired rows,
key/pose fingerprints, thread counts, source/DLL hashes and synthetic summaries.
The pre-native source snapshot used for these paired runs is the round-two
Python implementation whose normalized source SHA-256 starts `21e8213586ce`.
If that local snapshot is absent, the benchmark harness compares current code
with native matching disabled instead.

The experimental backend is opt-in. Other Blender versions and non-Windows
platforms also use the existing Blender backend.
