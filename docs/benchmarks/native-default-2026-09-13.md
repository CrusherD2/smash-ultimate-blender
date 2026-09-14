# The native IK backend's default — 2026-09-13

Follow-up to `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md`, which
passed the outcome-based acceptance criterion on ten configurations of a single
animation and then declined to act on that evidence, asking explicitly for more
fixtures first: *"Widening this evidence — more fixtures, more rigs, longer clips
— is cheap now that the harness exists, and is the right thing to do before
flipping the default."* This is that widening, and the decision it supports.

## Verdict: adopt. The native backend is on by default where it is supported

**28 runs — three fixtures, fourteen configurations, both supported Blender
versions — every one produced the same solved pose as Blender's backend.
`max_pose_difference` is exactly 0.0 on all 28, `total_delta` 0, no frame fits
worse. No run was declined outright by the guards.**

That includes the fixture this was expected to fail on — but read what happened
there carefully, because it is not what it first looks like.
`native/ik_match/README.md` states plainly that *"near-straight test cases still
differ"*, and the corpus carries a generated straightening clip whose minimum
bend is 0.0098 rad for exactly that reason. The composed path matched Blender
anyway. **It matched because the guards declined the hard chain-frames and
Blender's own search finished them — not because the Rust solver reproduced
Eigen's arithmetic on near-collinear geometry.** The README's prediction was
routed around, not falsified. "What the near-straight rows actually show", below,
puts a number on it.

That distinction does not weaken the decision: "the composed path returns
Blender's answer" is precisely what the criterion asks, and the fallback is part
of the shipped product, not a caveat on it. It matters for what the next person
concludes about the Rust solver itself, which is a different claim and is not
supported here.

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

| source | scenario | limbs | frames | native solves | Py candidates | gate | frames worse | identical | total_delta | max pose diff | s Blender | s native |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | normal | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.280 | 0.649 |
| baseline | normal | ARMS | 157 | 314 | 0 | PASS | 0 | 157 | 0 | **0.0** | 0.968 | 0.396 |
| baseline | normal | LEGS | 157 | 314 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.029 | 0.459 |
| baseline | object_scale | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.422 | 0.750 |
| baseline | parent_scale | BOTH | 157 | 628 | 578 | PASS | 0 | 157 | 0 | **0.0** | 1.355 | 0.925 |
| baseline | inheritance | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.481 | 0.892 |
| baseline | stretch | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.291 | 0.678 |
| baseline | arm_pull | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.360 | 0.679 |
| baseline | animated_stretch | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.308 | 0.655 |
| baseline | foot_controls | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.315 | 0.672 |
| near_straight | normal | BOTH | 40 | 160 | 323 | PASS | 0 | 40 | 0 | **0.0** | 0.379 | 0.280 |
| near_straight | parent_scale | BOTH | 40 | 160 | 578 | PASS | 0 | 40 | 0 | **0.0** | 0.437 | 0.405 |
| near_straight | stretch | BOTH | 40 | 160 | 323 | PASS | 0 | 40 | 0 | **0.0** | 0.373 | 0.277 |
| shyguy_static | normal | LEGS | 5 | 10 | 0 | PASS | 0 | 5 | 0 | **0.0** | 0.121 | 0.065 |

`run_count: 14`, `native_engaged: 14`, `guards_declined: []`, `failing_rows: []`,
corpus wall time 14.120 s → 7.782 s (**1.81x**).

## Blender 4.5.7 LTS

| source | scenario | limbs | frames | native solves | Py candidates | gate | frames worse | identical | total_delta | max pose diff | s Blender | s native |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| baseline | normal | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.085 | 0.658 |
| baseline | normal | ARMS | 157 | 314 | 0 | PASS | 0 | 157 | 0 | **0.0** | 0.760 | 0.397 |
| baseline | normal | LEGS | 157 | 314 | 0 | PASS | 0 | 157 | 0 | **0.0** | 0.831 | 0.442 |
| baseline | object_scale | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.281 | 0.864 |
| baseline | parent_scale | BOTH | 157 | 628 | 578 | PASS | 0 | 157 | 0 | **0.0** | 1.229 | 0.919 |
| baseline | inheritance | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.379 | 0.948 |
| baseline | stretch | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.124 | 0.680 |
| baseline | arm_pull | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.126 | 0.663 |
| baseline | animated_stretch | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.111 | 0.667 |
| baseline | foot_controls | BOTH | 157 | 628 | 0 | PASS | 0 | 157 | 0 | **0.0** | 1.112 | 0.671 |
| near_straight | normal | BOTH | 40 | 160 | 323 | PASS | 0 | 40 | 0 | **0.0** | 0.368 | 0.273 |
| near_straight | parent_scale | BOTH | 40 | 160 | 578 | PASS | 0 | 40 | 0 | **0.0** | 0.467 | 0.425 |
| near_straight | stretch | BOTH | 40 | 160 | 323 | PASS | 0 | 40 | 0 | **0.0** | 0.358 | 0.274 |
| shyguy_static | normal | LEGS | 5 | 10 | 0 | PASS | 0 | 5 | 0 | **0.0** | 0.128 | 0.069 |

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

The honest caveat: `native_solves` counts solvers *created*, one per chain per
frame, not chain-frames *answered natively*. A chain-frame whose geometry the
native search declines is finished by Blender's own Python search, and the "Py
candidates" column above is exactly how much of that happened. So these 28 rows
show that the native path produces Blender's answer end to end — which is what
the criterion asks — not that the Rust solver answered every chain-frame. The
per-frame fallback is part of why that identity is reachable, and it stays.

## What the near-straight rows actually show

**The fallback rate is now measured directly.** `native_declined` is a dedicated
`diag` counter, incremented per chain-frame at the point `native.search(...)`
returns `None` and the Python search takes over (`ik_channels.py`). It sits
beside `native_solves`, so their ratio is the fallback rate — the single number
that explains why the accelerator would help one rig and not another, and the
figure to ask for when someone reports that the default did not speed theirs up.

| row | chain-frames | declined | rate |
|---|---:|---:|---:|
| baseline / parent_scale | 628 | **34** | 5.4% |
| near_straight / normal | 160 | **19** | 11.9% |
| near_straight / parent_scale | 160 | **34** | 21.3% |
| near_straight / stretch | 160 | **19** | 11.9% |
| every other row (24 of 28) | — | **0** | 0% |

The three `near_straight` figures are direct counter readings from
`docs/benchmarks/native-default-2026-09-13-near_straight.json`, a narrowed
re-run on Blender 5.2 (`SUB_IK_CORPUS=near_straight`). The `baseline` figure is
derived, below; the counter post-dates the 28-row corpus run and that run was
deliberately not repeated.

### Corroboration: the same numbers, derived independently

The direct counter agrees exactly with an inference available from the original
committed data, which is how the fallback picture was first worked out.

The "Py candidates" column is `diag`'s `candidates` counter, incremented in
`error()` inside `_match_chain_steps`. On the native path that whole block is
inside the `else:` of `if found is not None` (`ik_channels.py:1263`), so it is
reached **only** on a declined chain-frame. **It is a fallback counter, not a
work counter** — which is why it does not scale with frame count (578 on both a
157-frame and a 40-frame run, 323 on two 40-frame runs): declines depend on how
much degenerate geometry a clip contains, not how long it is.
`candidates_blender` scales exactly with frames because there every chain-frame
runs the Python search; `candidates_native` cannot.

Each declined chain-frame costs exactly 17 evaluations: 3 seeds through
`best(seeds)`, then `error(angle)` free from the memo, `error(a)` and `error(b)`,
12 `_POLE_REFINE_STEPS`, and a final `best((angle, a, b))` entirely memoised.
The Blender-variant rows confirm the constant independently — `candidates_blender
/ native_solves` is exactly 17.0 on every row of both versions (10676/628,
5338/314, 2720/160, 170/10), across 1,712 chain-frames, which also shows the
`_POLE_TOLERANCE` early exit never fires on this content, so the decomposition is
unique rather than merely consistent.

| row | Py candidates | ÷ 17 | counter says |
|---|---:|---:|---:|
| near_straight / normal | 323 | 19 | **19** |
| near_straight / parent_scale | 578 | 34 | **34** |
| near_straight / stretch | 323 | 19 | **19** |
| baseline / parent_scale | 578 | 34 | *not re-run* |

Three for three. That validates the arithmetic on the fourth row, where the
committed `candidates_native` of 578 gives 34 declines of 628 chain-frames.

### What `max_pose_difference == 0.0` does and does not prove

It does not say the Rust solver reproduced Eigen's matrices. The native search's
only durable output is the **selected pole angle** (`ik_channels.py:1263-1264`,
then `entry['angle'] = angle` and `con.pole_angle = …`); every matrix keyed
downstream is produced by Blender evaluating the rig at that angle. So the gate
compares *which angle each backend chose*, and a 0.0 pose difference means the
two backends agreed on the angle — not that the intermediate matrices the native
search scored internally were bit-compatible with Eigen's.

That is the right thing to gate on, because the angle is the only thing that
reaches the user's file. It is a weaker statement about the Rust arithmetic than
"bit-identical" suggests, and the earlier criterion document's wording should be
read with the same care.

So the near-straight fixture is the hard case the README predicted: it is the
only source where the plain `normal` configuration provokes declines at all, and
it declines at 2–4x the rate of the one real-motion configuration that does. The
solver did not handle near-collinear geometry; it refused it, and Blender picked
it up. The 0.0 pose difference is a property of the composed path.

## What this evidence licenses, and what it does not

**The 28/28 result is evidence about the composed path — native search plus
guards plus per-frame fallback plus Blender — and not about the Rust solver on
its own.** The guards declining is part of *why* the result is clean, not an
asterisk on it. Three consequences, stated plainly because the number is
otherwise easy to over-read:

1. **It is not licence to loosen or remove the collinearity guard.** The rows
   where the guard fired hardest are exactly the near-collinear rows the Rust
   README says the solver gets wrong. Removing the guard removes the thing that
   produced the 0.0, and this data says nothing whatever about what the solver
   would return in its place. A change there needs its own corpus run, measured
   the same way, and cannot cite this one.
2. **It is not a claim that the Rust arithmetic matches Eigen's.** See the
   section above: the gate compares the selected pole angle, which is the only
   thing that reaches a user's file.
3. **It does not bound the fallback rate on unseen rigs.** 0% on 24 rows and
   21.3% on the worst comes from two animations and two rigs. A rig that declines
   far more would still be *correct* — Blender finishes those chain-frames — but
   would get little of the speedup. `native_declined` exists so that case is
   diagnosable in one number instead of guessed at.

### The repeated counts are a shared cause, not a coincidence

Two pairs repeat across rows — 19/19 and 34/34 — and both now have an account.

**19/19 is direct:** `near_straight/normal` and `near_straight/stretch` drive the
same pole search on the same rig, so they decline on the same chain-frames.

**34/34 is supported by the counts themselves.** `near_straight.blend` *is*
`baseline.blend`: `tests/build_near_straight_fixture_blender.py` opens the
baseline, trims the range to 40 frames and overwrites **only** the bend bone's
`rotation_euler.x`, leaving every other channel — including the parent bone that
`parent_scale` scales — exactly as the baseline has it. Three measurements then
fit together and rule out the alternatives:

- `baseline/normal` declines **0**. On the baseline clip the bend geometry alone
  causes no declines at all, so every one of `baseline/parent_scale`'s 34 is
  caused by the scaled parent.
- `near_straight/normal` declines **19**, caused by the straightened bend.
- `near_straight/parent_scale` declines **34** — not 53. If the two mechanisms
  were independent and additive, the bend's 19 and the parent's 34 would give
  roughly 53. They do not add; the parent-scale declines subsume the bend ones.
- And 34 is *the same* count on a 157-frame clip and a 40-frame one. A
  frame-proportional cause would have given the 40-frame run about a quarter as
  many, ~9, not 34.

The reading consistent with all four: under `parent_scale` the scaled parent
determines which chain-frames decline, that set is the same in both fixtures
because the fixtures share those channels, and it already covers whatever the
bend would have caused on its own.

**What is still not measured:** that these are literally the same chain-frames.
Confirming that needs a per-frame decline trace on `baseline`, which would mean
re-running the full baseline source, and the 28-row corpus was deliberately not
re-run in this round. The mechanism is supported by four independent counts, not
proven by frame-level identity.

## Independent confirmation on a production rig

`tests/benchmark_shyguy_match_blender.py` fingerprints every pose bone of the
170-bone Shy Guy rig on every frame, plus all F-Curve keys, after a real
`a00wait1` import and after a full leg re-match. Run under the Blender backend
and again under the new default, on Blender 5.2:

| | keys | poses |
|---|---|---|
| `SUB_NATIVE_IK=0` | `47fd45c9…` | `a2a2f03b…` |
| `SUB_NATIVE_IK=experimental` (the shipped default) | `47fd45c9…` | `a2a2f03b…` |

Identical. This is a different rig and a different code path from the corpus
(operator-driven import and transfer rather than `gate.run_variant`), and it
agrees.

Both rows are reproducible from the tree: the benchmark now honours a pre-set
`SUB_NATIVE_IK` and falls back to `'0'` only when the variable is unset, so the
historical Blender-backend figures it was written for are unchanged while the
default can be measured with the same script.

```powershell
$env:PYTHONIOENCODING='utf-8'
Remove-Item Env:SUB_NATIVE_IK -ErrorAction Ignore   # Blender backend row
python tests/run_blender_test.py --blender '...\Blender 5.2\blender.exe' tests/benchmark_shyguy_match_blender.py
$env:SUB_NATIVE_IK='experimental'                   # shipped-default row
python tests/run_blender_test.py --blender '...\Blender 5.2\blender.exe' tests/benchmark_shyguy_match_blender.py
```

Each run prints six `SHYGUY_PAIR` lines carrying `keys`, `poses` and `seconds`,
and rewrites `.tests/benchmarks/shyguy_ik_repro/paired.json`; compare the
fingerprints across the two invocations. The figures recorded here predate that
one-line change and were produced by an equivalent scratch copy, so re-running
is the way to confirm them rather than to have produced them.

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
to be near-straight, does not land there *in the shipped composed path* — partly
because the guards steer away from it, as the fallback counts above show. It
does not prove no rig ever will.
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

Setting `SUB_IK_CORPUS` narrows the corpus and redirects the output to
`native-default-2026-09-13-<selection>.json`, flagged `partial`, so a narrowed
run cannot replace a complete version entry in the file the default flip rests
on. The decline figures above came from:

```powershell
$env:SUB_IK_CORPUS='near_straight'
python tests/run_blender_test.py --blender '...\Blender 5.2\blender.exe' tests/benchmark_native_corpus_blender.py
```

The production-rig fingerprints and timings come from
`tests/benchmark_shyguy_match_blender.py`, run twice — once with `SUB_NATIVE_IK`
unset (it defaults to `'0'`) and once with `SUB_NATIVE_IK=experimental`. See
"Independent confirmation on a production rig" above for the exact invocations.
That fixture needs the local `.tests/benchmarks/shyguy_ik_repro/` blends and the
Shy Guy moveset `a00wait1.nuanmb`, neither of which is distributed.
