# Isolated-clone dependency reductions

Three reductions to the dependency graph the isolated IK clone evaluates,
measured against the exact baseline. Each is behind `SUB_IK_REDUCE`; none is a
default. This document records what they cost and what they bought, so the
adoption decision has numbers behind it.

## Environment

- Blender 5.2.1 LTS (hash `9e2066aef7ef`, built 2026-08-25), Windows 11.
- `SUB_NATIVE_IK=0` (pure-Python solve path), `SUB_IK_DIAG=1` (stage timings).
- Fixture: `.tests/benchmarks/shyguy_ik_repro/matched_wait.blend` — Shy Guy,
  170 bones, **240 frames** (`frames: 240` in the fixture's
  `diagnostic.json`), both legs (`cleanup_mode='LEGS'`, entire animation),
  480 limb poses matched (2 chains x 240 frames), 4,292 graph updates in the
  pole search.
- 3 repeats per flag, 15 matches total. Medians reported.
- **Ordering caveat.** The harness runs the five variants in a fixed order
  within each repeat (baseline, `action`, `pin`, `bbone`, all three), unlike
  the alternating A/B design used in
  `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`. A drift over the run
  would therefore land on the variants unevenly. Nothing in the data suggests
  drift, but the design does not rule it out.
- **Precision.** Run-to-run spread within a flag is about 4% (e.g. the
  `action` group spans 1.626-1.695 s). Medians below are printed to three
  decimals for traceability against the JSON, not because the third decimal is
  meaningful. Treat differences under roughly 5% as unresolved by this run.

## Results

| `SUB_IK_REDUCE` | median s | speedup | `search` s | updates | exact | isolation |
| --- | --- | --- | --- | --- | --- | --- |
| *(baseline)* | 1.671 | 1.00x | 1.104 | 4292 | — | ok |
| `action` | 1.652 | 1.01x | 1.100 | 4292 | yes | ok |
| `pin` | 3.392 | **0.49x** | 2.614 | 4292 | yes | `rest_data_changed` |
| `bbone` | 1.671 | 1.00x | 1.105 | 4292 | yes | ok |
| `action,pin,bbone` | 3.476 | **0.48x** | 2.668 | 4292 | yes | `rest_data_changed` |

The update count is 4,292 in every row. No reduction moved the candidate
sequence; these change what each evaluation costs, not how many there are.

Every flag was **exact**: identical F-Curve keys and identical per-frame pose
matrices for all 170 bones against the baseline. For `pin` that verdict is
hollow — see below.

Raw rows: `docs/benchmarks/isolated-dependencies-2026-09-13.json`.

## `action` — exact, no measurable win

Gives the clone its own copy of the action (the original is never touched) and
removes the F-Curves of bones the clone does not retain. The majority of the
rig's bone channels go — a figure near 60% was seen in an ad-hoc probe that was
not kept, so treat it as indicative and not as a measurement of record.

**The `search` stage did not move: 1.100 s against a 1.104 s baseline.** That
is the argument, and it does not depend on the sample size. `search` is where
this match spends its time, and it is the stage the reduction would have to
move to be worth anything. It is unchanged because the clone's animation is
evaluated once per `frame_set`, i.e. 240 times, while the pole search performs
4,292 graph updates that re-evaluate constraints and the IK solver but *not*
the animation. Removing most of the curves therefore cuts 240 cheap
evaluations and leaves the 4,292 expensive ones untouched.

The median total, 1.652 s against 1.671 s, corroborates this but proves less:
at n=3 the `action` group spans 1.626-1.695 s and overlaps the baseline group
entirely, so this run rules out a win larger than roughly 5% — not a win of any
size. The unchanged `search` stage is what makes a smaller win implausible too.

**Recommendation: do not adopt.** Exact but not faster. It adds an action
datablock copy, a slot rebind and a cleanup path to the isolation for no
measured benefit.

## `pin` — inapplicable on this rig, and 2x slower when enabled

Built to the rule that a retained bone may be unparented only when its own
world matrix is in the sampled set, so the caller can re-place it from that
sample each frame. On this fixture it fires:

- Sampled: `FootL FootR Hip KneeL KneeR LegC LegL LegR ToeL ToeR`.
- Both chains' solver root parent is `LegC`; `LegC`'s own ancestor is `Hip`.
- **Unparented 2 bones: `Hip` and `LegC`.**
- The clone's retained set would fall from **20 bones to 17** (of 170) —
  `Hip`, `Rot` and `Trans` drop out once `LegC` is pinned.

It then fails. Unparenting an edit bone makes Blender recompute that bone's
armature-space rest matrix directly from head/tail/roll instead of composing it
down the hierarchy, and the two do not agree to the last bit. The "0 of 170"
and "134 of 170" figures below come from an ad-hoc probe that was not kept as
a script, so treat them as indicative, not as a measurement of record — the
same qualifier this section already applies to the `action` curve-count
figure above:

- A bare edit-mode round trip with nothing unparented changes **0 of 170**
  bones' `matrix_local` / `matrix` / `head` / `length`. The round trip itself
  is lossless here.
- The same round trip with `Hip` and `LegC` unparented changes **134 of 170**
  bones — the two pinned bones and, by cascade, every descendant. The retained
  solver bones are among them: `BL_SUB_IK_LegL.matrix[1][1]` moves from
  `1.0` to `0.9999999403953552`, one ULP.

What the kept run *does* corroborate: every baseline row in the table above
performs the same edit-mode round trip — enter edit mode, delete the ~150
edit bones outside the solver's dependency closure, leave edit mode — and
still records `isolate: ok`, i.e. the round trip itself does not shift rest
data on this rig. `pin`'s row is the only one that additionally unparents two
bones and is the only one that records `isolate: rest_data_changed`.
Unparenting is therefore the only variable the kept data ties to the failure,
even without the standalone probe.

The existing rest-data check in `isolated` catches this, records
`isolate: rest_data_changed`, and falls back to solving in the user's own
scene. That is the correct outcome — a silently shifted rest matrix would
corrupt every pose the solve produces — but it means the whole fast isolation
is lost, and the match runs at **0.49x**, 1.7 s slower. The `exact: yes` in the
table is the fallback path being exact, not `pin` being exact.

The upside was never large in any case: the closure already prunes this
170-bone rig to 20 bones, so the best `pin` could have done is 20 → 17.

**Recommendation: do not adopt, and do not pursue.** The reduction cannot
preserve rest data on a bone that has a parent, which is the only case it
applies to. Enabling it is strictly worse than baseline because it converts
every match into a fallback.

## `bbone` — fired on nothing

The fixture has **0 bones with `bbone_segments > 1`**, so `_collapse_bbones`
made no change and the 1.00x row measures the baseline twice. The reduction is
untested rather than shown neutral.

**Recommendation: do not adopt on this evidence.** There is no measurement
here to adopt from. A Smash Ultimate import has no B-Bone subdivision, so this
would need a different fixture to say anything at all — and given that `action`
(a much larger graph reduction) bought nothing, there is little reason to build
that fixture.

## Summary

- Failed exactness: **none**.
- Exact but not faster: **`action`** (1.01x), and **`bbone`** vacuously (it
  fired on nothing).
- Actively harmful: **`pin`** (0.49x) — it trips the rest-data guard and forces
  a full fallback.

Nothing here is worth adopting. The pole search's cost on this rig is not the
size of the clone's dependency graph; the clone is already down to 20 of 170
bones before any of these reductions run.

## Reproduce

Task 6 removed the reductions this benchmark measures (see Adopted, below):
`_reductions`, `_prune_action`, `_collapse_bbones`, `_pin_ancestors`, the
`isolated()` branches that called them, and the `_sample_names` extension
`pin` depended on are no longer in `source/extras/ik_match_fast.py` /
`ik_channels.py`. `tests/benchmark_isolated_dependencies_blender.py` is kept
in the tree for the record, but running it as-is no longer exercises any
reduction — `SUB_IK_REDUCE` has nothing left to read, so every variant now
runs the same code and the five `ISOLATED_SUMMARY` rows will read as
identical modulo run-to-run noise, not as five different measurements.

To reproduce the original measurement, first re-apply
`docs/benchmarks/isolated-dependencies-2026-09-13-reductions.patch` (an
annotated listing of the removed code and exactly where each block went),
then run:

```
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_isolated_dependencies_blender.py
```

Expect `ISOLATED_REDUCTIONS_DONE 15` and five `ISOLATED_SUMMARY` lines.

## Adopted

**Nothing.** All three candidate reductions were measured and rejected —
`action` exact but with no measurable win (1.01x, and it left the dominant
`search` stage completely unmoved), `pin` exact only via a total fallback and
twice as slow when it fires (0.49x), and `bbone` untested on this fixture
(zero eligible bones). See the per-reduction sections above for the full
reasoning. Task 6 removed the `SUB_IK_REDUCE` machinery — `_reductions`,
`_prune_action`, `_collapse_bbones`, `_pin_ancestors`, the reductions branch
in `isolated()`, `ik_match_diag.note()`, and the `_sample_names` sampling
extension that existed solely to feed `pin` — rather than leave it behind a
flag nothing sets. The removed code is preserved at
`docs/benchmarks/isolated-dependencies-2026-09-13-reductions.patch` for
reproducibility. `_closure()`, the behaviour-preserving extraction of the
pre-existing dependency-closure loop, was kept — it changes nothing and reads
better than the inline version it replaced.

This is a negative result over one axis, not a regression: the fast paths
(direct FK sampling plus isolated-clone solving) that Task 6 acts on remain
in place and unaffected by this removal, because the reductions were behind
a flag nothing set by default. On the Shy Guy fixture
(`docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`), those fast paths
measure:

| Operation | Fast paths off | Fast paths on | Speedup |
|---|---:|---:|---:|
| Automatic IK matching during animation import | 3.9115 s | 1.8537 s | 2.11x |
| Position IK Controls, legs, whole animation | 3.9671 s | 1.8361 s | 2.16x |

Re-running `tests/benchmark_shyguy_match_blender.py` after Task 6's removal
(3 repeats, Blender 5.2.1 LTS, same fixture) reproduces the same shape:

| Operation | Fast paths off (median) | Fast paths on (median) | Speedup |
|---|---:|---:|---:|
| Automatic IK matching during animation import | 3.6046 s | 1.7862 s | 2.02x |
| Position IK Controls, legs, whole animation | 3.5296 s | 1.6935 s | 2.08x |

`SHYGUY_EXACT_PAIRS 6` — all six fast/exact pairs share the identical
F-Curve-key hash and per-frame pose-matrix hash, matching the pre-Task-5
baseline. `tests/profile_shyguy_updates_blender.py` reports
`search_graph_updates: 4292` for both import and match, unchanged. Removing
the dependency-reduction machinery changes none of this, because it was
never on the path those numbers measure — it was reachable only behind
`SUB_IK_REDUCE`, a flag nothing set by default. Full command transcripts are
in the task report
(`.superpowers/sdd/2026-09-13-ik-candidate-evaluation-cost/task-6-report.md`).
