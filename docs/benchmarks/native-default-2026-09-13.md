# The native IK backend's default — 2026-09-13

Follow-up to `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md`, which
passed the outcome-based acceptance criterion on ten configurations of a single
animation and then declined to act on that evidence, asking explicitly for more
fixtures first: *"Widening this evidence — more fixtures, more rigs, longer clips
— is cheap now that the harness exists, and is the right thing to do before
flipping the default."* This is that widening, and the decision it supports.

## Verdict: adopt. The native backend is on by default where it is supported

**28 runs — three fixtures, fourteen configurations, both supported Blender
versions — every one bit-identical to Blender's backend. `max_pose_difference`
is exactly 0.0 on all 28. No run was declined by the guards.**

That includes the fixture this was expected to fail on. `native/ik_match/README.md`
states plainly that *"near-straight test cases still differ"*, and the corpus
carries a generated straightening clip whose minimum bend is 0.0098 rad for
exactly that reason. It did not differ. All three of its configurations engaged
the native solver (160 solves each) and returned Blender's matrices bit for bit.

## Environment

- Blender 5.2.1 LTS and Blender 4.5.7 LTS, Windows x64, bundled
  `native/bin/sub_ik_match_native.dll` (ABI 3), one native thread.
- Driver: `tests/benchmark_native_corpus_blender.py`, comparing the `native`
  variant against the `blender` variant through `tests/ik_match_gate.py`
  (`TOLERANCE = {'relative': 1e-5, 'pose': 1e-4, 'absolute': 1e-9}`).
- Corpus: `tests/ik_match_corpus.py` — `baseline` (real clip, 131-bone rig, 157
  frames, ten configurations), `near_straight` (generated straightening clip,
  same rig, 40 frames, three configurations), `shyguy_static` (170-bone
  production rig, static pose, five frames, one configuration). Two distinct
  animations; `shyguy_static` contributes rig shape, not motion.
- Full data: `docs/benchmarks/native-default-2026-09-13.json`.

## Blender 5.2.1 LTS

| source | scenario | limbs | frames | native solves | gate | frames worse | identical | total_delta | max pose diff | s Blender | s native |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | normal | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.280 | 0.649 |
| baseline | normal | ARMS | 157 | 314 | PASS | 0 | 157 | 0 | **0.0** | 0.968 | 0.396 |
| baseline | normal | LEGS | 157 | 314 | PASS | 0 | 157 | 0 | **0.0** | 1.029 | 0.459 |
| baseline | object_scale | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.422 | 0.750 |
| baseline | parent_scale | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.355 | 0.925 |
| baseline | inheritance | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.481 | 0.892 |
| baseline | stretch | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.291 | 0.678 |
| baseline | arm_pull | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.360 | 0.679 |
| baseline | animated_stretch | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.308 | 0.655 |
| baseline | foot_controls | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.315 | 0.672 |
| near_straight | normal | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.379 | 0.280 |
| near_straight | parent_scale | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.437 | 0.405 |
| near_straight | stretch | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.373 | 0.277 |
| shyguy_static | normal | LEGS | 5 | 10 | PASS | 0 | 5 | 0 | **0.0** | 0.121 | 0.065 |

`run_count: 14`, `native_engaged: 14`, `guards_declined: []`, `failing_rows: []`,
corpus wall time 14.120 s → 7.782 s (**1.81x**).

## Blender 4.5.7 LTS

| source | scenario | limbs | frames | native solves | gate | frames worse | identical | total_delta | max pose diff | s Blender | s native |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | normal | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.085 | 0.658 |
| baseline | normal | ARMS | 157 | 314 | PASS | 0 | 157 | 0 | **0.0** | 0.760 | 0.397 |
| baseline | normal | LEGS | 157 | 314 | PASS | 0 | 157 | 0 | **0.0** | 0.831 | 0.442 |
| baseline | object_scale | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.281 | 0.864 |
| baseline | parent_scale | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.229 | 0.919 |
| baseline | inheritance | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.379 | 0.948 |
| baseline | stretch | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.124 | 0.680 |
| baseline | arm_pull | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.126 | 0.663 |
| baseline | animated_stretch | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.111 | 0.667 |
| baseline | foot_controls | BOTH | 157 | 628 | PASS | 0 | 157 | 0 | **0.0** | 1.112 | 0.671 |
| near_straight | normal | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.368 | 0.273 |
| near_straight | parent_scale | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.467 | 0.425 |
| near_straight | stretch | BOTH | 40 | 160 | PASS | 0 | 40 | 0 | **0.0** | 0.358 | 0.274 |
| shyguy_static | normal | LEGS | 5 | 10 | PASS | 0 | 5 | 0 | **0.0** | 0.128 | 0.069 |

`run_count: 14`, `native_engaged: 14`, `guards_declined: []`, `failing_rows: []`,
corpus wall time 12.358 s → 7.951 s (**1.55x**).

## Why this is not a vacuous pass

A native run that the per-frame guards decline everywhere would fall back to
Blender on every candidate and therefore agree with Blender perfectly, while
proving nothing. Three things rule that out.

1. `gate.require_engaged('native', …)` decides each row's `engaged` flag from
   the `native_solves` counter, and the driver exits non-zero if any row is
   unengaged. All 28 rows engaged.
2. The solve counts scale with the work: 628 for two limbs over 157 frames, 314
   for one, 160 for the shorter clip, 10 for the five-frame static fixture.
3. The native runs are measurably faster than the Blender runs on every row. A
   run that fell back everywhere would be slower than Blender, not faster.

The honest caveat on that third point: `native_solves` counts solvers *created*,
one per chain per frame, not candidates *answered natively*. A solver that hits
the collinearity guard mid-frame sets `fallback` and Blender finishes that
chain's search silently. So these 28 rows show that the native path produces
Blender's answer end to end — which is what the criterion asks — rather than
that no individual candidate ever fell back. The per-frame fallback is part of
why bit-identity is reachable at all, and it stays.

## Independent confirmation on a production rig

`tests/benchmark_shyguy_match_blender.py` fingerprints every pose bone of the
170-bone Shy Guy rig on every frame, plus all F-Curve keys, after a real
`a00wait1` import and after a full leg re-match. Run under the Blender backend
and again under the new default, on Blender 5.2:

| | keys | poses |
|---|---|---|
| `SUB_NATIVE_IK=0` | `47fd45c9…` | `a2a2f03b…` |
| default (native on) | `47fd45c9…` | `a2a2f03b…` |

Identical. This is a different rig and a different code path from the corpus
(operator-driven import and transfer rather than `gate.run_variant`), and it
agrees.

## What it costs and what it buys

Same session, Blender 5.2, Shy Guy rig, median of three paired runs:

| phase | Blender backend | native default | speedup |
|---|---:|---:|---:|
| Import, fast paths on | 1.540 s | 0.637 s | **2.42x** |
| Match, fast paths on | 1.546 s | 0.615 s | **2.52x** |
| Import, fast paths off | 3.205 s | 0.977 s | 3.28x |
| Match, fast paths off | 3.196 s | 0.993 s | 3.22x |

Against the 3.9115 s import / 3.9671 s match fast-paths-off baseline recorded in
`docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`, the default path now
reaches 6.14x on import and 6.45x on match; the previous plan ended at 2.02x and
2.08x. The fast-paths-off rows above are ~18% quicker than that historical
baseline on the same fixture, so treat the same-session ratios as the real
figures and the 6x as an accumulated headline across both plans.

## The decision, and its limits

The default is flipped in `source/extras/ik_native.py`. An unset `SUB_NATIVE_IK`
now resolves to `'experimental'`; `'0'` forces the backend off everywhere; `'1'`
remains verification mode. **Only the default changed.** Every other guard is
untouched: Windows, x86-64, Blender 4.5 or 5.2, bundled DLL present, the
`supported()` constraint checks, and every per-frame fallback.

The mode is now resolved in one place — `ik_native.mode()` and
`ik_native.verifying()` — because three call sites previously read
`SUB_NATIVE_IK` from the environment independently (`get_factory`,
`evaluate_steps`'s verification switch, and `ik_channels`' native pole-search
gate), and an unset variable meaning something new would otherwise have meant
three chances to disagree about it.

**Results are no longer guaranteed bit-identical to Blender's backend on
degenerate geometry.** The criterion document recommends exactly this
disclosure, and it is not hypothetical: `tests/test_native_ik_singular_blender.py`
constructs synthetic poses — exactly straight rest bones, right-angle geometry,
bend angles from 0 to 0.1 rad — where the two backends do differ, in matrix
elements whose exact value is zero and whose largest divergence is 4.37e-08.
This corpus establishes that real content, including a clip built specifically
to be near-straight, does not land there. It does not prove no rig ever will.
`SUB_NATIVE_IK=1` and `SUB_NATIVE_IK=0` exist for anyone who needs certainty
rather than evidence.

Scope: two animations, three fixtures, two rigs, two Blender versions, one
machine. Wider than the evidence this replaces, and still not a proof.

## Reproduce

```powershell
$env:PYTHONIOENCODING='utf-8'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' tests/benchmark_native_corpus_blender.py
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/benchmark_native_corpus_blender.py
```

The driver merges each version's rows into
`docs/benchmarks/native-default-2026-09-13.json` under `versions`, so the two
runs accumulate rather than overwrite each other. The resolution rule itself is
pinned by `tests/test_native_default_blender.py`.
