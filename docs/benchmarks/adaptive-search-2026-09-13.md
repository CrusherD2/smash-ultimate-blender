# Adaptive pole-search stopping rule — 2026-09-13

Follow-up to `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md`. Task 3
implemented a convergence-based early stop for the golden-section pole search
(`SUB_IK_ADAPTIVE=1`) and measured it against the project's acceptance corpus. This
document records the verdict, why the gate rejects it on structural grounds rather
than merely on a headline number, and what was decided as a result: **the rule is
removed, not merely defaulted off.**

## Verdict: reject and remove

**2.53% fewer candidate evaluations (104,414 → 101,775), no wall-time win, and the
rejection rests on that 2.53% — not on the 13/14 gate failure rate**, which turns out
to measure something else entirely (see below). The corpus was not close: every
real-motion configuration in the corpus failed, so this is not a near-straight-only
edge case that a special-case branch could carve out.

## What was measured

Environment: Blender 5.2, `tests/benchmark_adaptive_corpus_blender.py`, 14 runs
(baseline rig × 10 scenarios/limb-subsets, near-straight rig × 3, static Shy Guy
fixture × 1) comparing the fixed 12-step search against the same search with the
adaptive stop enabled. Full data: `docs/benchmarks/adaptive-search-2026-09-13.json`.

| source | scenario | limbs | cand. before | cand. after | early stops | gate | frames worse | total_delta | max pose diff | s before | s after |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | normal | BOTH | 10676 | 10637 | 62 | **FAIL** | 3/157 | 0.01932 | 3.42e-3 | 1.485 | 1.565 |
| baseline | normal | ARMS | 5338 | 5308 | 52 | **FAIL** | 2/157 | 0.0188 | 3.42e-3 | 1.037 | 1.107 |
| baseline | normal | LEGS | 5338 | 5329 | 10 | **FAIL** | 1/157 | 5.272e-4 | 5.89e-4 | 1.147 | 1.165 |
| baseline | object_scale | BOTH | 10676 | 10633 | 63 | **FAIL** | 10/157 | -0.01056 | 3.42e-3 | 1.599 | 1.591 |
| baseline | parent_scale | BOTH | 10676 | 8972 | 599 | **FAIL** | 64/157 | -0.2654 | 9.06e-3 | 1.554 | 1.462 |
| baseline | inheritance | BOTH | 10676 | 10636 | 55 | **FAIL** | 7/157 | 0.01753 | 2.93e-3 | 1.754 | 1.744 |
| baseline | stretch | BOTH | 10676 | 10637 | 62 | **FAIL** | 3/157 | 0.05307 | 3.48e-3 | 1.453 | 1.462 |
| baseline | arm_pull | BOTH | 10676 | 10640 | 65 | **FAIL** | 2/157 | -4.021e-3 | 5.75e-4 | 1.440 | 1.498 |
| baseline | animated_stretch | BOTH | 10676 | 10637 | 62 | **FAIL** | 3/157 | -5.244e-3 | 3.42e-3 | 1.582 | 1.618 |
| baseline | foot_controls | BOTH | 10676 | 10637 | 62 | **FAIL** | 3/157 | 0.01932 | 3.42e-3 | 1.802 | 1.573 |
| near_straight | normal | BOTH | 2720 | 2630 | 44 | **FAIL** | 10/40 | 0.01477 | 2.32e-3 | 0.441 | 0.458 |
| near_straight | parent_scale | BOTH | 2720 | 2279 | 150 | **FAIL** | 19/40 | 0.292 | 3.01e-2 | 0.516 | 0.517 |
| near_straight | stretch | BOTH | 2720 | 2630 | 44 | **FAIL** | 11/40 | 0.01688 | 2.32e-3 | 0.479 | 0.426 |
| shyguy_static | normal | LEGS | 170 | 170 | 0 | PASS | 0/5 | 0 | 0 | 0.150 | 0.154 |

**Total candidates: 104,414 → 101,775. Reduction 2,639 (2.53%).** Wall time is inside
noise in both directions — several adaptive runs are slower than the fixed search
they replace, on the same hardware, same process.

**Not a near-straight-only failure.** All ten real-motion `baseline` configurations
fail, including plain `normal/BOTH`. The two `near_straight` failures are worse in
degree (`parent_scale` reaches the corpus's largest pose delta, 3.01e-2) but are not
a different *kind* of failure — same mechanism, more of it.

## The finding that outlives the code: the gate is an output-identity test here

The number that looks decisive is 13/14 failing rows. **It is not the reason to
reject the rule, and treating it as the reason would be wrong.** The gate's
`pose_delta <= 1e-4` check is a maximum over every element of every solved bone
matrix on every frame — not a fit-quality measure, a bit-closeness measure. On
Blender's IK solver, which warm-starts each pole-angle evaluation from the previous
one, **any search that visits a different sequence of candidate angles produces a
detectably different final pose, independent of whether that pose is a better or
worse fit to the FK source.**

The worked example is `baseline/arm_pull/BOTH`:

- Worst relative delta: **1.6e-6** — an order of magnitude *inside* the gate's own
  per-frame relative tolerance (1e-5).
- Median delta: **0.0** across all 157 frames.
- Total delta: **-4.02e-3** — negative, meaning the adaptive answer is on the whole
  a *better* fit to FK than the fixed search's answer.
- Yet `max_pose_difference` is **5.75e-4** against a `pose` tolerance of 1e-4 (5.75x
  over), at `KneeR@86[0][3]` — and that single element comparison alone fails the
  gate.

This run fails for being *different*, not for being *worse*. And the failure does
not track how much early stopping happened: `near_straight/normal/BOTH` stopped
early only 44 times and still landed a pose delta of 2.32e-3 (23x over); the largest
pose delta in the corpus (`near_straight/parent_scale`, 3.01e-2) came from the row
with the most stops (150), but `baseline/normal/LEGS` needed only 10 stops to reach
5.89e-4 — six times over the bar from the *smallest* number of early exits in the
corpus. There is no threshold of "a little bit of early stopping" that stays under
the gate; the mechanism that fails is present at the first stop.

**Consequence:** the gate, as specified, cannot distinguish "different and worse"
from "different and better." It cannot pass *any* stopping rule that changes even
one search path on this solver, no matter how small the change or how good the
result. So `13/14` is close to a foregone conclusion once a rule fires at all —
useful as a sanity check that the corpus is exercising the rule, but not as the
basis for the accept/reject decision. **The decision rests on the number that
*does* discriminate: 2.53%.** Under 2% end-to-end (this search is roughly two-thirds
of match runtime), against a real risk (pose drift on real animation, not merely
synthetic fixtures) and a permanent maintenance cost (a second code path through the
refinement loop, a flag to keep documenting and testing forever), the saving does
not clear the bar. This conclusion is the durable output of Task 3/4 — more durable
than the rule itself, which is deleted below.

## The `shyguy_static` pass is vacuous, not reassuring

It records 0 early stops: the static pose converges under `_POLE_TOLERANCE` before
the refinement block is ever entered, so the adaptive and fixed code paths are
identical there. It is evidence the flag is inert when it never fires, not evidence
that firing is safe.

## Decision

**Real motion fails. The rule is removed**, not merely left off by default.

The brief that scoped this task offered three outcomes (adopt, adopt with a
near-straight carve-out, or leave off behind a flag) and asked the corpus to choose.
The corpus chose "no" outright, and the review above adds a reason to go further
than "leave off": a flag whose only documented, reachable effect is *"produces
output that fails this project's own acceptance gate, for a 2% saving, on every
real-motion configuration tested"* is not a defensible piece of standing
configuration. Keeping `_adaptive_enabled()` and `_ADAPTIVE_RELATIVE` around under
an env var that anyone could set (or that a later refactor could flip the default
of) is a live foot-gun with no offsetting benefit. It is deleted from
`source/extras/ik_channels.py`.

Kept, deliberately:

- The `diag.add('candidates', 0.0, 1)` counter in `error()`, after the memo
  early-return. It is correct, cheap, always-on, and the only reason any of this
  was measurable in the first place — including the measurement in this document.
- `docs/benchmarks/adaptive-search-2026-09-13.json` and
  `tests/benchmark_adaptive_corpus_blender.py`, as the recorded evidence for this
  decision. Not re-run as part of routine testing; the rule they measure no longer
  exists in `source/`.
- `tests/test_ik_adaptive_search_blender.py`, converted from an assertion that the
  rule passes the gate (which was committed red and could not pass, by
  construction, once the gate's behaviour above was understood) to an assertion
  that the machinery does not silently come back — `ik._adaptive_enabled` and
  `ik._ADAPTIVE_RELATIVE` must not exist. A future reintroduction now has to edit a
  visible, named assertion instead of drifting back in unnoticed.

## Corrections to the record

Task 3's report (`.superpowers/sdd/2026-09-13-adaptive-ik-search/task-3-report.md`)
is kept as-is; these are amendments, not deletions, so the record shows how the
understanding changed.

**`adaptive_early` over-counted, and the "handful of steps" reading is wrong.** The
convergence check sat at the *end* of the loop body, so it also fired on what would
have been the loop's final (12th) iteration — recording a "stop" that broke a loop
about to exit on its own, saving nothing. On `baseline/normal/BOTH`, 62 recorded
early stops correspond to only 39 fewer candidates (10,676 → 10,637): **0.63 saved
candidates per recorded stop**, not "a handful of the 12 steps" as Task 3's report
characterized it in its "Reading the failures" section. The saving-per-firing is an
order of magnitude smaller than that phrasing implies; the corpus-wide 2.53%
already reflects the true (net) number, so the headline is unaffected — only the
per-stop intuition was wrong.

**The `best` shadowing bug's failure mode, as described in Task 3's report, is
wrong about *how* it fails, though the fix was correct.** The report says assigning
`best = fa if fa < fb else fb` (per the brief's Step 4 snippet) would raise
`UnboundLocalError` at `best(seeds)`. It would not: `best` is read for the first
time later in execution order than where the snippet's assignment appears
textually, but Python determines "local to this scope" from the *presence* of an
assignment anywhere in the function body, applied uniformly across the whole
function — so by the time `best(seeds)` executes, `best` is already bound (to the
nested generator function, since that def runs first at that point in the control
flow) and the call succeeds normally. The failure actually surfaces later: `best = fa if fa < fb else
fb`, placed mid-loop (in the adaptive branch, where this task's `converged`
temporary stood), rebinds the name from a function to a `float` the first time that
branch runs, and the final `angle = yield from best((angle, a, b))` — outside and
after the loop — then raises `TypeError: 'float' object is not callable`, not
`UnboundLocalError`. The rename to `converged` (now removed along with the rest of
the adaptive block) was still the right fix — it just fixed a `TypeError` raised
after the loop exits, not an `UnboundLocalError` at the start.

## Two untried directions, and why neither is worth doing next

**A bracket-width criterion (`hi - lo` instead of `abs(fa - fb)`).** The score gap
is path-dependent under warm-starting, as the corpus shows; the bracket width is
purely geometric and does not share that failure mode. This is the more principled
stopping signal and would likely reduce (not eliminate) the "different but not
worse" pattern seen above. It is still capped by the same ceiling: the search
already converges in 12 steps by design (see the note next to
`_POLE_REFINE_STEPS`), so a smarter stopping rule can only recover iterations
inside that already-small budget. Unless it recovers substantially more than
2.53% *and* passes the gate — which nothing here demonstrates — it is not worth
building and re-measuring against a ceiling this low.

**The native path.** `tests/test_ik_match_fast_blender.py` and this task's spec
both point at the native backend as the place a stopping rule could work, because
native solves are stateless (no warm-start, so a different search path should not
imply a different converged answer). But this is not a re-run of the existing
change under a flag: under `SUB_NATIVE_IK=experimental`, the `native.search(...)`
call in `_match_chain_steps` (`source/extras/ik_channels.py`) bypasses the Python
refinement loop — the `for _ in range(_POLE_REFINE_STEPS)` block this task
modified — entirely.
The equivalent stopping rule for the native path would have to be implemented in
Rust, inside `native/ik_match/src/`, with its own correctness work and its own
benchmark. It is a real candidate for a future task, but it is new work with its
own budget, not something Task 4 already did or can finish by flipping a flag.

## Environment hazard for anyone re-running this gate

Task 3 found that on Blender 4.4, the fast-path test's pose hash differs between
*separate processes running identical, unmodified code*
(`eaffac75…` then `fc80083d…` on two consecutive runs). This means **any gate
comparison run on 4.4 is unreliable by construction** — a "failure" could be process
nondeterminism rather than a real regression. This is recorded here, durably,
because it previously existed only inside a task report:
`.superpowers/sdd/2026-09-13-adaptive-ik-search/task-3-report.md`. It does not
affect this task's verdict, which was measured on 5.2, but it should stop anyone
from trying to validate a future IK change against 4.4's fast path expecting
reproducible results. 4.4 is already outside the `{(4,5),(5,2)}` fast-path gate for
unrelated reasons; this is an additional, independent reason not to trust a 4.4
comparison run even where the fast path is not in play.

## Scope and limits of this evidence

One source rig, ten scenario/limb configurations plus three near-straight variants
plus one static fixture, 14 runs, Blender 5.2 only (the corpus benchmark was not
re-run for this task, per the dispatch's instruction not to re-run it). The
structural argument about the gate — that it cannot separate "different" from
"worse" under warm-starting — is solver behavior, not corpus-specific, and should
generalize to any future stopping-rule attempt on this same Blender code path
regardless of fixture. The native-path and bracket-width directions above are
untried, not ruled out by data; the ceiling argument against them is a cost/benefit
judgment, not a measurement.
