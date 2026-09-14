# Cheaper IK candidate evaluations — design spec

**Status:** accepted, 2026-09-13
**Diagnosis this builds on:** `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`

## Problem

On the fresh Shy Guy foot-IK reproduction (170 bones, 2 leg chains, 240 frames)
matching costs ~1.85 s with the current fast paths on. Explicit timing shows
**64–66% of that is inside `view_layer.update()` calls made by the pole search**:
4,292 graph updates per match, 1.14–1.25 s in total.

The pole search issues roughly nine candidate evaluations per chain per frame.
Previous work removed evaluations (arithmetic placement, batching, native
backend). This spec does **not** remove any more. It makes each remaining
evaluation cheaper, and makes the fast paths available in more situations.

## Non-goals

- No change to the numerical solver, the candidate sequence, the search order,
  the summation order, or `_POLE_REFINE_STEPS`.
- No wholesale arithmetic rewrite of the pole search. A closed-form replacement
  needs a separately validated solver, not a faster sampling vehicle; the
  measured attempt regressed worst-case limb error (0.415 -> 0.622).
- No enabling of the unverified Rust backend by default.

## Requirements

### R1 — Diagnostics: stage timings

Matching must be able to report where its time went, split by stage, without
that reporting costing measurable time when it is off.

- Stages: `sample`, `isolate`, `place`, `search`, `write`.
- `search` additionally reports the graph-update **count**.
- Enabled by `SUB_IK_DIAG=1`. Off by default, and off means one boolean test
  per stage — not per graph update.
- Results readable programmatically by tests, and reported to the operator log
  when enabled.

### R2 — Diagnostics: explicit fallback reasons

Today `sample_fk` returns bare `None` and `can_isolate` returns bare `False`.
When a real user rig is slow there is no way to learn which guard rejected it.

- Every rejection records a stable machine-readable reason code.
- Codes are recorded whether or not diagnostics are enabled (a rejection happens
  once per match, so the cost is irrelevant).
- The isolated-scene rest-data verification failure gets its own code.

### R3 — Isolation eligibility separated from multi-limb batching

`fast = _fast and batch and ...` and `batch` requires `len(jobs) >= 2`. So
matching a single chain disables direct FK sampling, isolated solving, and
mesh deferral, even when the rig is perfectly eligible for all three.

- The dependency audit in `_can_batch_match` must be split into:
  - **self-containment** — the rig is one closed island: no object parent or
    object constraints, no armature-data drivers, only whitelisted constraint
    types, every constraint target inside the same object, only the generated
    influence-driver expressions. Isolation and mesh deferral need this.
  - **limb disjointness** — no two selected chains share a bone or a
    dependency. Only scheduling two limbs into one graph update needs this.
- `batch` = `len(jobs) >= 2` and self-containment and disjointness. Its
  behaviour must not change for any rig that batches today.
- The fast paths become available when self-containment holds, regardless of
  chain count.
- `_defer_match_meshes` is gated on self-containment, not on batching.

### R4 — Measured reductions to the isolated solver's dependencies

Candidate reductions, each measured before adoption:

- **A. Prune the clone's action** to channels of retained bones only (requires
  copying the action; the clone currently shares the original datablock).
- **B. Pin retained ancestors.** Bones retained only because they are ancestors
  are pinned each frame from their sampled world matrices, and their own
  ancestors dropped. Reduces the clone toward the chain bones alone.
- **C. Collapse B-Bone segments** on retained bones.

Adoption gate for each: measured on the Shy Guy fixture, and **exact** — the
existing keyframe-coordinate/interpolation digest and the whole-rig per-frame
pose digest must be byte-identical to the current output. A reduction that is
exact but not faster is not adopted.

## Global constraints

- Blender 4.4, 4.5, 5.0, 5.1 and 5.2 must keep working. The fast paths remain
  restricted to `bpy.app.version[:2] in {(4, 5), (5, 2)}`.
- Existing guards stay. Nothing here loosens a correctness guard; R3 only
  stops one guard standing in for another.
- Every rejection path must still fall back to the ordinary scene evaluation.
- No new third-party dependency.
