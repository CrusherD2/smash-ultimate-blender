# Phase 3 decision: do not build cross-frame parallelism — 2026-09-13

Phase 3 of `docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md` proposed
making each frame a pure function of its own inputs and dispatching frames across
`rayon`. Profiling the current state first, as Phase 2's outcome argued for,
shows the premise does not hold: **the native search is 12% of a match, so
parallelising it cannot return more than about 1.12x.**

Recommendation: **do not build Phase 3.**

## Where a match spends its time now

cProfile of `match(_batch=True)` under `SUB_NATIVE_IK=experimental`,
`SUB_NATIVE_SEARCH=1`, Blender 4.5.7, 157 frames, both limbs. Total 0.955 s
(profiler overhead puts this ~10% above the 0.869 s measured without it).

| Component | Time | Share |
|---|---:|---:|
| `match()` own code, mostly the placement loop | 0.183 s | 19.2% |
| Native search including FFI | 0.119 s | 12.5% |
| `Solver.__init__`, dominated by JSON capture | 0.102 s | 10.7% |
| `fcurve_bulk` key writing | 0.102 s | 10.7% |
| `sample_fk` | 0.084 s | 8.8% |
| `_match_chain_steps` own | 0.057 s | 6.0% |
| `evaluate_steps` own | 0.057 s | 6.0% |
| accounted | 0.704 s | 73.7% |

**The depsgraph no longer appears in the top thirty entries at all.** Neither
`frame_set` nor `view_layer.update` is measurable here. The 68% depsgraph share
that started this work is gone, removed by FK sampling, the isolated solve rig
and the native search between them.

What remains is Python orchestration, spread thin. There is no dominant cost left
to attack.

## Why Phase 3 is not worth building

| Change | Resulting match | Speedup |
|---|---:|---:|
| Parallel search, perfect 8-core scaling | 0.851 s | 1.12x |
| Binary capture instead of JSON | 0.875 s | 1.09x |
| Both | 0.771 s | 1.24x |
| Both plus key writing halved | 0.720 s | 1.33x |

Phase 3 alone returns at most 1.12x, and that assumes perfect scaling with no
dispatch overhead. Against that it requires splitting `match()` into a serial
capture pass, a parallel solve pass and a serial key-writing pass, and replacing
the previous-frame pole seed with a deterministic per-frame candidate set — which
is the one change in this whole effort that would knowingly alter output, and
would need the equal-or-better-residual criterion to be re-verified across every
configuration.

That is a large restructure and a real correctness risk for about a tenth.

## What this means for the 10x target

It is not reachable on this architecture. Working backwards: 10x over the 2.63 s
Blender-backend baseline means 0.263 s. The floor here is `sample_fk` (0.084 s)
plus the native search (0.119 s) plus the per-frame capture evaluations — roughly
0.3 s before any Python orchestration at all. Even eliminating every Python cost
in the table lands near 8x, and nothing in the table is free to eliminate.

Realistically attainable from here:

- **~4x** by taking the cheap wins: binary capture instead of JSON, and cheaper
  key writing. Contained, low risk, no output change.
- **~6-8x** only by moving the entire match loop into native code — placement,
  capture, search and key generation — leaving Python a single call. That is a
  rewrite of `match()`, not an optimisation of it, and it would put every guard
  and fallback currently written in Python on the other side of the FFI boundary.

Delivered so far is about 3x on matching over the pre-optimisation baseline, plus
the earlier exact 2.0-2.3x that ships enabled by default.

## Recommended next step

Take the cheap wins, and stop there unless the remaining factor is worth a
rewrite:

1. Replace the per-solve JSON capture with a packed binary buffer. 628 solves per
   match each serialise a dict through `json.dumps` and parse it in Rust. The FFI
   already has `sub_ik_create_raw`; this is a format change behind it, worth
   about 8%, with no effect on results.
2. Reduce key-writing cost in `fcurve_bulk`, worth up to about 5%.

Both are measurable independently and neither changes output, so both can be
verified by the existing residual matrix and fast-path suites.
