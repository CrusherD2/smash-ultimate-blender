# How far the pole refinement can be cut — 2026-09-15

Follow-up to merging upstream's `BL_SUB_IK_MATCH_` correction bones
(`6efe5d1`). Every earlier decision about the pole search — including
`_POLE_REFINE_STEPS = 12` itself, and the residual acceptance criterion the
native backend was validated against — rested on the residual between the
solved chain and the sampled FK pose *being the output*. Corrections changed
that. This measures what the search is still worth.

Harness: `tests/benchmark_pole_refine_sweep_blender.py`. Nine budgets (12 down
to 0) × three native modes × Blender 4.5.7 and 5.2.1, on the benchmark clip —
157 frames, four chains, twelve limb bones. Raw JSON in
`.tests/benchmarks/pole-refine-sweep-<mode>-<version>.json`.

## Verdict: 12 → 4. Exactness never depended on this number

**Worst-case FK drift is `7.63e-06` at every budget in all six runs —
including budget 0.** Not "close at 4 and degrading below"; bit-identical
across the whole sweep, on both Blender versions, in all three native modes.
Output exactness is not a function of the refinement budget at all.

Two structural facts explain it, and both are worth stating plainly because
they invalidate the reasoning the old value was chosen under:

1. The correction bones key the residual per frame, and the pull chain reads
   the correction rather than the solver, so the deform bones land on sampled
   FK whatever pole angle the search settles on. A worse angle does not make a
   worse pose; it makes a *larger correction*.
2. The pole **control** — `KneeIK` / `ArmIK`, the thing an animator actually
   selects — is placed by arithmetic in `_match_chain_steps` that the search
   never touches. `con.pole_angle` drives only the hidden `BL_SUB_IK_*` solver
   chain, which lives in the `IK Internal` collection.

So cutting the search cannot move the posed character and cannot move any
visible control. If exact output were genuinely the only requirement, the
answer would be 0.

## What the search still buys

The residual is frozen into a local offset at match time. It is correct at the
matched pose and only approximately correct once the animator drags the IK
target away from it, so a larger correction means a limb that misbehaves
sooner under editing. That is the axis the budget still trades on, and it
degrades in two clear steps:

| steps | drift worst | corr. translation worst / p99 / median | corr. rotation worst / median |
|------:|------------:|---------------------------------------:|------------------------------:|
| 12 | 7.63e-06 | 0.4726 / 0.3458 / 0.0349 | 7.09° / 0.55° |
| 10 | 7.63e-06 | 0.4726 / 0.3458 / 0.0350 | 7.09° / 0.55° |
| 8 | 7.63e-06 | 0.4728 / 0.3458 / 0.0347 | 7.09° / 0.54° |
| 6 | 7.63e-06 | 0.4731 / 0.3467 / 0.0354 | 7.07° / 0.54° |
| **4** | **7.63e-06** | **0.4724 / 0.3467 / 0.0376** | **7.12° / 0.61°** |
| 3 | 7.63e-06 | 0.4724 / 0.3467 / 0.0412 | 7.12° / 0.63° |
| 2 | 7.63e-06 | 0.4724 / 0.3422 / 0.0415 | 7.12° / 0.64° |
| 1 | 7.63e-06 | 0.4740 / 0.3566 / 0.0541 | 7.27° / 1.07° |
| 0 | 7.63e-06 | 0.9104 / 0.3789 / 0.0544 | 14.04° / 1.07° |

- **12 → 4 is free.** Worst and p99 move by nothing meaningful (0.4726 →
  0.4724; 0.3458 → 0.3467 — the worst figure is *lower* at 4 than at 12, which
  is the honest read that these differences are noise, not a trend). The median
  rises 8%, 0.0349 → 0.0376. Pole-angle curve roughness is flat: mean RMS
  second difference 0.07268 → 0.07268.
- **Below 4 it costs.** The median gives up 44% by budget 1 (0.0541) and
  rotation median nearly doubles, 0.61° → 1.07°. Curve roughness starts moving
  too (0.07268 → 0.07693).
- **0 is never acceptable.** The worst correction doubles outright — 0.4740 →
  0.9104, rotation 7.27° → 14.04°. The bracket's endpoints are all it has left.

4 is the last budget that is free on *every* measure, so that is the pick. 2 is
defensible if the median matters less than the evaluations; 0 is not.

## Where the saving lands — not in the default mode

`_POLE_REFINE_STEPS` is passed to `native.search`, which resolves the whole
search inside the DLL. In the shipped default mode the budget therefore costs
**no Blender evaluations at all**:

| mode (Blender 4.5) | evals @12 | evals @4 | evals @0 |
|---|---:|---:|---:|
| `native-search` (default, `SUB_NATIVE_IK` unset) | 314 | 314 | 314 |
| `native-verify` (`SUB_NATIVE_IK=1`) | 3140 | 1884 | 1256 |
| `blender` (`SUB_NATIVE_IK=0`) | 2983 | 1727 | 1099 |

314 is two barriers per frame — the native capture, and the correction write
upstream added. Flat at every budget, and wall time follows: 0.82 s at 12,
0.73 s at 4, 0.76 s at 0, which is noise.

The cut pays in every fallback: Blender-only drops 2983 → 1727 evaluations
(−42%) and 1.48 s → 0.95 s; verification 3140 → 1884. Those paths are reached
with the add-on preference off, on the chain-frames the native guard declines
(up to 21.3% of one corpus rig — `native-default-2026-09-13.md`), and whenever
a match cannot batch, since `native_factory` is only built for batched matches.

Both Blender versions agree throughout; 5.2 is uniformly slower but the shape
is identical (`native-search` flat at 314, `blender` 2983 → 1099).

## A correction to the record

An earlier reading of this sweep concluded the native search "declines on
Blender 5.2," from a 5.2 run showing 3140 evaluations and 10,676 candidates.
That was a mistake in the harness invocation, not a finding: `SUB_NATIVE_IK=1`
is *verification* mode — `ik_native.verifying()` is `mode() == '1'` — and the
native search gate requires `not verifying()`. The unset default resolves to
`'experimental'`, which is the accelerating mode. The 4.5 and 5.2 runs had not
been given the same mode. Re-run controlled, 5.2 is flat at 314 like 4.5. The
harness now labels runs by `ik_native.mode()` rather than by the raw variable
so the two cannot be confused again.

## What this does not settle

- One clip, one rig. The correction-magnitude knee at 4 is measured on the
  benchmark fixture only. The corpus harness
  (`tests/benchmark_native_corpus_blender.py`) covers three fixtures and would
  extend this cheaply; that was not done here.
- The editability claim is mechanical, not measured. That a larger frozen
  correction misbehaves sooner under editing follows from the correction being
  a fixed local offset, but no one has perturbed a target and measured the
  resulting error as a function of budget. If the budget is ever cut below 4,
  that measurement is the thing to do first.
- The remaining 314 evaluations are now the cost centre, not the search. Two
  barriers per frame, one of which exists only to read the solved pose back for
  the correction write. Folding that into the native path is the next available
  speedup and is not attempted here — the native solver models `solver[:-1]`,
  while the correction needs the endpoint bone with its endpoint constraints
  live.
