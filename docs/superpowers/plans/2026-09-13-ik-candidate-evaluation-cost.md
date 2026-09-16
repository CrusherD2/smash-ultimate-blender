# Cheaper IK Candidate Evaluations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each remaining IK pole-search candidate evaluation cheaper, and make the existing fast paths reachable for single-chain matches, without changing the solver, the candidate sequence, or the output.

**Architecture:** Add an opt-in diagnostics module that records stage timings and always-on fallback reason codes, so every later decision is measured rather than guessed. Then split the one monolithic `_can_batch_match` audit into a *self-containment* half (which isolation and mesh deferral actually need) and a *limb-disjointness* half (which only two-limbs-in-one-graph-update needs), so a single chain stops being disqualified by a check it does not need. Finally, measure three reductions to the isolated clone's dependency graph behind flags and adopt only those that are both faster and bit-exact.

**Tech Stack:** Python 3.11 / `bpy` (Blender 4.4–5.2), `mathutils`, `ctypes` FFI to the optional Rust backend (left disabled), single-script Blender tests driven by `tests/run_blender_test.py`.

**Spec:** `docs/superpowers/specs/2026-09-13-ik-candidate-evaluation-cost.md`

## Global Constraints

- Blender 4.4, 4.5, 5.0, 5.1 and 5.2 must all keep working. The fast paths stay restricted to `bpy.app.version[:2] in {(4, 5), (5, 2)}`.
- The numerical solver, candidate sequence, search order, summation order and `_POLE_REFINE_STEPS = 12` are untouched.
- No correctness guard is loosened. Tasks 3 and 4 only stop one guard standing in for another.
- Every rejection path still falls back to the ordinary scene evaluation.
- Exactness gate for any performance change: the keyframe coordinate/interpolation digest **and** the whole-rig per-frame pose digest from `tests/benchmark_shyguy_match_blender.py` must be byte-identical to the pre-change output.
- Diagnostics off must cost at most one boolean test per stage, never per graph update.
- No new third-party dependency.
- The Rust backend stays off: tests set `os.environ['SUB_NATIVE_IK'] = '0'`.
- Blender executable for every test command below: `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe` (4.5 and 4.4 where a step names them).

---

### Task 1: Diagnostics module and fallback reason codes

**Files:**
- Create: `source/extras/ik_match_diag.py`
- Modify: `source/extras/ik_match_fast.py` (`sample_fk` lines 64–150, `can_isolate` lines 153–166, `isolated` lines 169–246)
- Test: `tests/test_ik_diag_blender.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ik_match_diag.enabled() -> bool`
  - `ik_match_diag.reset() -> None`
  - `ik_match_diag.record() -> dict` with keys `reasons: dict[str, str]`, `stages: dict[str, float]`, `counts: dict[str, int]`
  - `ik_match_diag.reject(guard: str, code: str) -> None` — records and returns `None`
  - `ik_match_diag.accept(guard: str) -> None`
  - `ik_match_diag.add(name: str, seconds: float, count: int = 0) -> None`
  - `ik_match_diag.stage(name: str)` — context manager
  - Guard names used across the codebase: `'sample'`, `'isolate'`, `'batch'`, `'selfcontained'`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_diag_blender.py`:

```python
"""Fallback reason codes name the guard that actually rejected the rig."""
from pathlib import Path
import os, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
fast = importlib.import_module(MODULE+'.source.extras.ik_match_fast')
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')
compat = importlib.import_module(MODULE+'.source.anim.fcurve_compat')

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 15
    return obj

def sample(obj):
    scene = bpy.context.scene
    jobs = list(ik.chains(obj))
    cache = ik._chain_cache(obj, jobs)
    names = ik._sample_names(obj, jobs, cache)
    action = obj.animation_data.action if obj.animation_data else None
    curves = compat.get_all_action_fcurves(action, id_type='OBJECT') if action else ()
    return fast.sample_fk(obj, range(scene.frame_start, scene.frame_end+1), names, curves)

# Accepted rig records 'ok'.
obj = reload()
diag.reset()
assert sample(obj) is not None
assert diag.record()['reasons']['sample'] == 'ok', diag.record()

# A foreign frame-change handler is the documented rejection.
def custom_handler(*args):
    pass

obj = reload()
bpy.app.handlers.frame_change_post.append(custom_handler)
try:
    diag.reset()
    assert sample(obj) is None
    assert diag.record()['reasons']['sample'] == 'foreign_handler', diag.record()
finally:
    bpy.app.handlers.frame_change_post.remove(custom_handler)

# An unmuted constraint on a sampled bone is a different, distinguishable reason.
obj = reload()
jobs = list(ik.chains(obj))
source_bone = ik.limb_path(obj, jobs[0][1])[0]
con = obj.pose.bones[source_bone].constraints.new('COPY_LOCATION')
diag.reset()
assert sample(obj) is None
assert diag.record()['reasons']['sample'] == 'constrained_source', diag.record()
obj.pose.bones[source_bone].constraints.remove(con)

# can_isolate reports its own guard under its own name.
obj = reload()
obj.pose.use_auto_ik = True
diag.reset()
assert not fast.can_isolate(obj, list(ik.chains(obj)), ik)
assert diag.record()['reasons']['isolate'] == 'auto_ik', diag.record()
obj.pose.use_auto_ik = False

# reset() clears, and reasons are recorded with diagnostics disabled.
assert os.environ.get('SUB_IK_DIAG') != '1'
diag.reset()
assert diag.record() == {'reasons': {}, 'stages': {}, 'counts': {}}
print('IK_DIAG_REASONS_OK')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_diag_blender.py
```

Expected: FAIL with `ModuleNotFoundError` naming `ik_match_diag`.

- [ ] **Step 3: Create the diagnostics module**

Create `source/extras/ik_match_diag.py`:

```python
"""Opt-in stage timings and always-on fallback reason codes for IK matching.

Timings are opt-in because the thing being measured is the thing being
optimised: a `perf_counter` pair around each of the several thousand graph
updates a match performs is not free. Reason codes are always on -- a guard
rejects at most once per match, and the case where the reason matters is
exactly the slow user rig nobody can reproduce.
"""
from contextlib import contextmanager
import os
import time

_RECORD = {'reasons': {}, 'stages': {}, 'counts': {}}


def enabled():
    """True when SUB_IK_DIAG=1 asked for stage timings."""
    return os.environ.get('SUB_IK_DIAG') == '1'


def reset():
    _RECORD['reasons'] = {}
    _RECORD['stages'] = {}
    _RECORD['counts'] = {}


def record():
    """Snapshot of the current match's diagnostics."""
    return {'reasons': dict(_RECORD['reasons']),
            'stages': dict(_RECORD['stages']),
            'counts': dict(_RECORD['counts'])}


def reject(guard, code):
    """Record why `guard` declined. Returns None so guards can `return` it."""
    _RECORD['reasons'][guard] = code
    return None


def accept(guard):
    _RECORD['reasons'][guard] = 'ok'


def add(name, seconds, count=0):
    _RECORD['stages'][name] = _RECORD['stages'].get(name, 0.0) + seconds
    if count:
        _RECORD['counts'][name] = _RECORD['counts'].get(name, 0) + count


@contextmanager
def stage(name):
    """Time a coarse stage. One boolean test when diagnostics are off."""
    if not enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        add(name, time.perf_counter() - start)
```

- [ ] **Step 4: Give every `sample_fk` rejection a code**

In `source/extras/ik_match_fast.py`, change the import line to `from . import pose_math, ik_match_diag as diag`, then split the opening guard of `sample_fk` (currently lines 72–77) into individually coded guards:

```python
    anim = obj.animation_data
    if not anim or not anim.action:
        return diag.reject('sample', 'no_action')
    if anim.action_blend_type != 'REPLACE' or anim.action_influence != 1.0:
        return diag.reject('sample', 'action_blend')
    if anim.use_nla and any(not t.mute for t in anim.nla_tracks):
        return diag.reject('sample', 'nla_track_active')
    if len(getattr(anim.action, 'slots', ())) > 1:
        return diag.reject('sample', 'multi_slot_action')
    if not known_handlers():
        return diag.reject('sample', 'foreign_handler')
```

Then, leaving the rest of the body unchanged, replace each remaining `return None` with its coded form:

```python
    if any(not pose_math.supports(pb) or pb.bone.use_connect
           or any(not con.mute for con in pb.constraints) for pb in originals):
        return diag.reject('sample', 'constrained_source')
```

```python
    if any(pb.constraints for pb in originals) and (
            tuple(tuple(r) for r in obj.matrix_basis) != identity_rows
            or tuple(tuple(r) for r in obj.matrix_world) != identity_rows):
        return diag.reject('sample', 'transformed_object')
```

```python
    if any(pb.constraints for pb in originals) and any(
            not fc.mute and fc.data_path in object_transforms for fc in curves):
        return diag.reject('sample', 'animated_object')
```

```python
            if fc.data_path not in paths or channel in seen:
                return diag.reject('sample', 'unsupported_channel')
```

```python
        if any(fc.data_path.startswith(prefixes) and fc.data_path not in muted
               for fc in anim.drivers):
            return diag.reject('sample', 'source_driver')
```

and immediately before `return result` inside the `try` block:

```python
        diag.accept('sample')
        return result
```

`diag.reject` returns `None`, so `sample_fk` still returns exactly `None` on every rejection. `tests/test_ik_direct_exact_blender.py` asserts `is None`, so this is load-bearing.

- [ ] **Step 5: Give every `can_isolate` and `isolated` rejection a code**

Replace `can_isolate` (currently lines 153–166) with:

```python
def can_isolate(obj, jobs, ik):
    """Called only after the existing full dependency guard passes.

    Returns a truthy value when isolation is allowed and ``None`` when it is
    not; the reason for a rejection is recorded under the ``isolate`` guard.
    """
    if not known_handlers():
        return diag.reject('isolate', 'foreign_handler')
    if obj.mode not in {'OBJECT', 'POSE'}:
        return diag.reject('isolate', 'object_mode')
    if obj.pose.ik_solver != 'LEGACY':
        return diag.reject('isolate', 'itasc_solver')
    if obj.pose.use_auto_ik:
        return diag.reject('isolate', 'auto_ik')
    for _, names, target, _ in jobs:
        path = ik.limb_path(obj, names)
        solver = obj.pose.bones[ik.PREFIX + path[-2]]
        endpoint = obj.pose.bones[ik.PREFIX + path[-1]]
        if solver.constraints['SUB IK Solve'].mute:
            return diag.reject('isolate', 'muted_solver')
        if any(c.mute for c in ik.end_constraints(endpoint)):
            return diag.reject('isolate', 'muted_endpoint')
        if obj.pose.bones[target].rotation_mode != 'QUATERNION':
            return diag.reject('isolate', 'target_rotation_mode')
    diag.accept('isolate')
    return True
```

In `isolated`, the rest-data verification failure is the last silent fallback. Immediately after the `valid = all(...)` assignment (currently line 232), add:

```python
            if not valid:
                diag.reject('isolate', 'rest_data_changed')
```

- [ ] **Step 6: Run the new test to verify it passes**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_diag_blender.py
```

Expected: PASS, printing `IK_DIAG_REASONS_OK`.

- [ ] **Step 7: Run the existing fast-path regressions unchanged**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS, printing `FAST_MATCH_EXACT_AND_CLEANUP_OK`.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_direct_exact_blender.py
```

Expected: PASS. This is the test that pins `sample_fk`'s `None` return.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_match_diag.py source/extras/ik_match_fast.py tests/test_ik_diag_blender.py docs/superpowers/specs/2026-09-13-ik-candidate-evaluation-cost.md docs/superpowers/plans/2026-09-13-ik-candidate-evaluation-cost.md
git commit -m "Name the guard that rejects each IK matching fast path"
```

---

### Task 2: Stage timings through the match pipeline

**Files:**
- Modify: `source/extras/ik_channels.py` (`_evaluate_match_steps` lines 939–946, `match` lines 1274–1345)
- Modify: `source/extras/ik_native.py` (`evaluate_steps` lines 164–184)
- Modify: `source/extras/ik_match_fast.py` (`isolated`)
- Test: `tests/test_ik_diag_blender.py` (append)

**Interfaces:**
- Consumes: `ik_match_diag.stage`, `.add`, `.enabled`, `.reset`, `.record` from Task 1.
- Produces: `record()['stages']` keys `'sample'`, `'isolate'`, `'place'`, `'search'`, `'write'` (seconds, floats) and `record()['counts']['search']` (graph-update count, int). `match()` calls `ik_match_diag.reset()` once at entry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ik_diag_blender.py`, before its final `print`:

```python
# Stage timings: opt-in, and the search is measurable.
os.environ['SUB_IK_DIAG'] = '1'
try:
    obj = reload()
    ik.match(bpy.context, obj, _batch=True)
    timed = diag.record()
finally:
    del os.environ['SUB_IK_DIAG']
assert set(timed['stages']) >= {'sample', 'place', 'search', 'write'}, timed
assert timed['counts']['search'] > 0, timed
assert timed['stages']['search'] > 0.0, timed
assert timed['stages']['sample'] >= 0.0, timed

# Off by default: no stage is recorded at all, but reasons still are.
obj = reload()
ik.match(bpy.context, obj, _batch=True)
untimed = diag.record()
assert untimed['stages'] == {} and untimed['counts'] == {}, untimed
assert untimed['reasons'].get('sample') == 'ok', untimed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_diag_blender.py
```

Expected: FAIL on `assert set(timed['stages']) >= {...}` because `stages` is empty.

- [ ] **Step 3: Time the graph updates in the batched scheduler**

In `source/extras/ik_native.py`, add `import time` (if absent) and `from . import ik_match_diag as diag` to the module imports, then replace the update in `evaluate_steps` (currently lines 183–184):

```python
        if evaluate_scene:
            if diag.enabled():
                start = time.perf_counter()
                context.view_layer.update()
                diag.add('search', time.perf_counter() - start, 1)
            else:
                context.view_layer.update()
```

- [ ] **Step 4: Time the sequential scheduler**

In `source/extras/ik_channels.py`, add `import time` if absent, then replace `_evaluate_match_steps` (lines 939–946) with:

```python
def _evaluate_match_steps(context, steps, batch):
    from . import ik_match_diag as diag
    if not batch:
        for step in steps:
            for _ in step:
                if diag.enabled():
                    start = time.perf_counter()
                    context.view_layer.update()
                    diag.add('search', time.perf_counter() - start, 1)
                else:
                    context.view_layer.update()
        return
    from .ik_native import evaluate_steps
    evaluate_steps(context, steps, batch)
```

- [ ] **Step 5: Wrap the coarse stages in `match`**

In `match`, immediately after `ensure(obj, context, limbs)`:

```python
    from . import ik_match_diag as diag
    diag.reset()
```

Wrap the sampling block (currently lines 1307–1318):

```python
                with diag.stage('sample'):
                    if fast:
                        from . import ik_match_fast
                        samples = ik_match_fast.sample_fk(obj, frames, sampled,
                            get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')
                            if obj.animation_data and obj.animation_data.action else ())
                    if not samples:
                        samples = {}
                        for frame in frames:
                            scene.frame_set(frame)
                            context.view_layer.update()
                            samples[frame] = {name: obj.pose.bones[name].matrix.copy() for name in sampled}
```

Wrap the per-frame step construction:

```python
                with solve_context as (work_context, work_obj, work_scene):
                    for frame, matrices in samples.items():
                        work_scene.frame_set(frame)
                        with diag.stage('place'):
                            steps = [
                                _match_chain_steps(work_obj, job, matrices, frame, key, writer,
                                                   cache[job[2]], previous_pole, native_factory)
                                for job in jobs
                            ]
                        _evaluate_match_steps(work_context, steps, batch)
```

`_match_chain_steps` is a generator function, so `place` measures only list construction; the body runs inside `_evaluate_match_steps`. That split is intended — `place` is cheap by construction and `search` is where the answer is.

Wrap the flush and interpolation pass:

```python
            with diag.stage('write'):
                if writer is not None:
                    writer.flush()
                if key and obj.animation_data and obj.animation_data.action:
                    owned = {PREFIX+n for _, _, target, _ in jobs for n in cache[target]['path']} | {n for _, _, target, pole in jobs for n in (target, pole)}
                    owned.update(name for entry in cache.values() if entry['foot'] for name in entry['foot'][:3])
                    owned.update(name for entry in cache.values() if entry['articulation'] for name in entry['articulation'][:2])
                    paths = tuple(obj.pose.bones[n].path_from_id() + '.' for n in owned if n in obj.pose.bones)
                    for fc in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'):
                        if fc.data_path.startswith(paths):
                            fcurve_bulk.set_interpolation(fc, 'LINEAR')
```

- [ ] **Step 6: Time the isolated scene construction**

`isolated` is a context manager, so time only its setup, not the solve. Restructure the body of `isolated` in `source/extras/ik_match_fast.py` so the timed region ends at the validity check and the `yield` sits outside it:

```python
    scene = clone = data = view = None
    valid = False
    try:
        with diag.stage('isolate'):
            scene = bpy.data.scenes.new('SUB temporary IK solve')
            ...                       # unchanged body through the edit-bone prune
            with context.temp_override(scene=scene, view_layer=view, object=clone, active_object=clone):
                bpy.ops.object.mode_set(mode='EDIT')
                for bone in list(data.edit_bones):
                    if bone.name not in needed:
                        data.edit_bones.remove(bone)
                bpy.ops.object.mode_set(mode='OBJECT')
                rows = lambda m: tuple(tuple(r) for r in m)
                valid = all(rows(b.matrix_local) == rows(obj.data.bones[b.name].matrix_local)
                            and rows(b.matrix) == rows(obj.data.bones[b.name].matrix)
                            and tuple(b.head) == tuple(obj.data.bones[b.name].head)
                            and b.length == obj.data.bones[b.name].length for b in data.bones)
            if not valid:
                diag.reject('isolate', 'rest_data_changed')
        if valid:
            with context.temp_override(scene=scene, view_layer=view, object=clone, active_object=clone):
                yield context, clone, scene
    finally:
        ...                           # unchanged cleanup
    if not valid:
        yield context, obj, context.scene
```

The override is entered twice instead of once. Read the resulting function top to bottom and confirm `view` and `clone` are bound before the second override, and that the solve still runs with the temporary scene and view layer active.

- [ ] **Step 7: Run the tests**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_diag_blender.py
```

Expected: PASS, printing `IK_DIAG_REASONS_OK`.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS, printing `FAST_MATCH_EXACT_AND_CLEANUP_OK`.

- [ ] **Step 8: Cross-check against the existing external profiler**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/profile_shyguy_updates_blender.py
```

Expected: the printed `SHYGUY_GRAPH_TIME` rows still report about 4,292 `search_graph_updates`. The new in-process counter must agree with that figure for the same run. A disagreement means the instrumentation is missing an update site; resolve it before continuing, because every later task is judged against this counter.

- [ ] **Step 9: Commit**

```bash
git add source/extras/ik_channels.py source/extras/ik_native.py source/extras/ik_match_fast.py tests/test_ik_diag_blender.py
git commit -m "Record IK matching stage timings behind SUB_IK_DIAG"
```

---

### Task 3: Split the dependency audit from multi-limb batching

This task is a **pure refactor**. `_can_batch_match` must return exactly what it returns today for every rig.

**Files:**
- Modify: `source/extras/ik_channels.py` (`_can_batch_match` lines 825–937)
- Test: `tests/test_ik_dependency_audit_blender.py`

**Interfaces:**
- Consumes: `ik_match_diag.reject` / `.accept` from Task 1.
- Produces:
  - `ik_channels._dependency_audit(obj, jobs, separate) -> dict | None` — the owner map when the rig passes, `None` when it fails. With `separate=True` each job gets its own island index and any shared bone fails; with `separate=False` every job shares island index `0`, so cross-limb sharing is fine and only genuinely external dependencies fail.
  - `ik_channels._is_self_contained(obj, jobs) -> bool` — `_dependency_audit(obj, jobs, separate=False) is not None`, recorded under guard `'selfcontained'`.
  - `ik_channels._can_batch_match(obj, jobs) -> bool` — unchanged semantics: `len(jobs) >= 2 and _dependency_audit(obj, jobs, separate=True) is not None`, recorded under guard `'batch'`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_dependency_audit_blender.py`:

```python
"""The audit split keeps batching identical and admits single chains."""
from pathlib import Path
import os, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 15
    return obj

# A clean rig batches and is self-contained.
obj = reload()
jobs = list(ik.chains(obj))
assert len(jobs) >= 2, jobs
assert ik._can_batch_match(obj, jobs)
assert ik._is_self_contained(obj, jobs)

# One chain cannot batch, but is still self-contained. This is the whole point.
single = jobs[:1]
diag.reset()
assert not ik._can_batch_match(obj, single)
assert diag.record()['reasons']['batch'] == 'single_chain', diag.record()
assert ik._is_self_contained(obj, single)

# An external parent fails both.
obj = reload()
jobs = list(ik.chains(obj))
empty = bpy.data.objects.new('external', None)
bpy.context.scene.collection.objects.link(empty)
obj.parent = empty
assert not ik._can_batch_match(obj, jobs)
diag.reset()
assert not ik._is_self_contained(obj, jobs)
assert diag.record()['reasons']['selfcontained'] == 'object_parent', diag.record()
obj.parent = None

# A constraint pointing outside the armature fails both.
obj = reload()
jobs = list(ik.chains(obj))
source_bone = ik.limb_path(obj, jobs[0][1])[0]
con = obj.pose.bones[source_bone].constraints.new('COPY_LOCATION')
con.target = empty
assert not ik._is_self_contained(obj, jobs)
assert not ik._can_batch_match(obj, jobs)
obj.pose.bones[source_bone].constraints.remove(con)

# One island vs. one island per chain.
obj = reload()
jobs = list(ik.chains(obj))
owners = ik._dependency_audit(obj, jobs, separate=False)
assert owners is not None and set(owners.values()) == {0}, sorted(set(owners.values()))
split = ik._dependency_audit(obj, jobs, separate=True)
assert split is not None and len(set(split.values())) == len(jobs), sorted(set(split.values()))
print('IK_DEPENDENCY_AUDIT_OK')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_dependency_audit_blender.py
```

Expected: FAIL with `AttributeError: module ... has no attribute '_is_self_contained'`.

- [ ] **Step 3: Perform the refactor**

Replace `_can_batch_match` (lines 825–937) with the audit plus two thin wrappers. Every check below is moved verbatim from the current function; the only edits are (a) the island index comes from `separate`, (b) a shared name is only a failure when the two owners differ, (c) `len(jobs) < 2` moves out to the batch wrapper, and (d) each rejection records a code.

```python
def _dependency_audit(obj, jobs, separate):
    """Owner map for the rig's dependency islands, or None if it is not closed.

    ``separate=True`` gives each selected chain its own island, which is what
    scheduling two limbs into one graph update requires. ``separate=False``
    puts every chain in one island, which is what isolating the rig into a
    temporary scene -- and hiding downstream meshes -- requires. Cross-limb
    sharing fails the first and is fine for the second; an external parent, an
    outside constraint target or a pose-reading driver fails both.
    """
    from . import ik_match_diag as diag
    guard = 'batch' if separate else 'selfcontained'
    if obj.parent:
        return diag.reject(guard, 'object_parent')
    if obj.constraints:
        return diag.reject(guard, 'object_constraints')
    all_jobs = list(chains(obj, 'BOTH'))
    owners = {}
    muted_outputs = {con.as_pointer() for _, con, _ in
                     (*outputs(obj, 'BOTH'), *toe_outputs(obj, 'BOTH')) if con.mute}
    # Include unselected limbs: their solvers also evaluate, but do not make
    # otherwise independent selected chains unsafe to schedule together.
    for index, (_, names, target, pole) in enumerate(all_jobs):
        island = index if separate else 0
        path = limb_path(obj, names)
        # A mixed/legacy rig may have controls on an unselected limb without
        # the independent solver generation. Do not upgrade it just to batch.
        if any(PREFIX + name not in obj.pose.bones for name in path):
            return diag.reject(guard, 'legacy_controls')
        if solve_bone(obj, names).constraints.get('SUB IK Solve') is None:
            return diag.reject(guard, 'missing_solver')
        controls = foot_controls(names, obj)
        articulation = toe_articulation(obj, names)
        owned = [*path, *(PREFIX + n for n in path),
                 *(PULL_PREFIX + n for n in path), target, pole]
        if controls:
            owned.extend(controls)
        if articulation:
            owned.extend(articulation)
        for name in dict.fromkeys(owned):
            if name in owners and owners[name] != island:
                return diag.reject(guard, 'shared_bone')
            owners[name] = island
    # Descendants (fingers and toe tips, for example) belong to the same
    # dependency island. A separately owned descendant is checked below.
    for bone in obj.pose.bones:
        if bone.name in owners:
            continue
        parent = bone.parent
        while parent is not None and parent.name not in owners:
            parent = parent.parent
        if parent is not None:
            owners[bone.name] = owners[parent.name]
    props = {'sub_use_ik_arms', 'sub_use_ik_legs',
             'sub_ik_stretch_arms', 'sub_ik_stretch_legs',
             'sub_ik_stretch_chain_arms', 'sub_ik_stretch_chain_legs'}
    props.update(obj.data.bones[pole].path_from_id() + '.' + ARM_PULL_PROPERTY
                 for kind, _, _, pole in chains(obj, 'ARMS'))
    if obj.data.animation_data and obj.data.animation_data.drivers:
        return diag.reject(guard, 'armature_data_driver')
    if obj.animation_data and obj.animation_data.action:
        from ..anim.fcurve_compat import get_all_action_fcurves
        pole_paths = {solve_bone(obj, names).constraints['SUB IK Solve'].path_from_id() + '.pole_angle'
                      for _, names, _, _ in all_jobs}
        for curve in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'):
            # Animated constraint settings can change dependencies after the
            # initial check. Our own pole-angle keys only affect their own limb.
            if '.constraints[' in curve.data_path:
                if curve.data_path not in pole_paths:
                    return diag.reject(guard, 'animated_constraint')
    for curve in obj.animation_data.drivers if obj.animation_data else ():
        driver = curve.driver
        if not curve.data_path.endswith('.influence') or not driver.variables:
            return diag.reject(guard, 'pose_driver')
        # Only pure expressions emitted by our wiring helpers. All inputs are
        # armature properties, so none can read another chain's evaluated pose.
        expressions = {driver.variables[0].name, 'stretch * chain',
                       'stretch * (1-chain)', 'pull * stretch * chain', '0'}
        if driver.type != 'SCRIPTED' or driver.expression not in expressions:
            return diag.reject(guard, 'foreign_driver_expression')
        for var in driver.variables:
            if (var.type != 'SINGLE_PROP' or var.targets[0].id != obj.data
                    or var.targets[0].data_path not in props):
                return diag.reject(guard, 'foreign_driver_input')
    for bone in obj.pose.bones:
        owner = owners.get(bone.name)
        if bone.parent and bone.parent.name in owners:
            if owner != owners[bone.parent.name]:
                return diag.reject(guard, 'cross_island_parent')
        for con in bone.constraints:
            # Only the output blends stay muted throughout matching. Check all
            # other constraints, including ones animated from muted to active.
            if con.as_pointer() in muted_outputs:
                continue
            if con.type not in {'COPY_TRANSFORMS', 'COPY_LOCATION', 'COPY_ROTATION',
                                'COPY_SCALE', 'DAMPED_TRACK', 'IK', 'TRANSFORM'}:
                return diag.reject(guard, 'unsupported_constraint')
            if getattr(con, 'use_bbone_shape', False):
                return diag.reject(guard, 'bbone_shape_constraint')
            if con.type == 'IK' and (owner is None or con.chain_count < 1):
                return diag.reject(guard, 'unowned_ik')
            if con.type == 'IK':
                ancestor = bone
                for _ in range(con.chain_count):
                    if ancestor is None or owners.get(ancestor.name) != owner:
                        return diag.reject(guard, 'ik_chain_crosses_island')
                    ancestor = ancestor.parent
            targets = [(con.target, con.subtarget)]
            if getattr(con, 'space_object', None) is not None:
                targets.append((con.space_object, con.space_subtarget))
            if con.type == 'IK':
                targets.append((con.pole_target, con.pole_subtarget))
            for target, name in targets:
                if target is None:
                    continue
                if target != obj or not name:
                    return diag.reject(guard, 'external_constraint_target')
                if name in owners and owners[name] != owner:
                    return diag.reject(guard, 'cross_island_constraint_target')
    diag.accept(guard)
    return owners


def _can_batch_match(obj, jobs):
    """Only combine evaluations when each limb reads independent pose inputs."""
    from . import ik_match_diag as diag
    if len(jobs) < 2:
        return bool(diag.reject('batch', 'single_chain'))
    return _dependency_audit(obj, jobs, separate=True) is not None


def _is_self_contained(obj, jobs):
    """True when the rig is one closed dependency island.

    Isolating the rig into a temporary scene, and hiding downstream meshes,
    both need this, and neither needs the limbs to be independent of each other.
    """
    return _dependency_audit(obj, jobs, separate=False) is not None
```

One semantic subtlety to preserve deliberately: the original wrote `if name in owners: return False` before `owners[name] = index`. With `separate=True` and a distinct index per job, `owners[name] != island` is equivalent, because a repeat across `all_jobs` always carries a different index, and a repeat inside one job's own `owned` list is already removed by `dict.fromkeys`.

- [ ] **Step 4: Run the new test**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_dependency_audit_blender.py
```

Expected: PASS, printing `IK_DEPENDENCY_AUDIT_OK`.

- [ ] **Step 5: Prove batching behaviour did not change**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS, printing `FAST_MATCH_EXACT_AND_CLEANUP_OK`, with `results[0]['usage'][1] == dict(sampled=1, isolated=1)` still holding.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_batch_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_isolated_strategies_blender.py
```

Expected: PASS on both.

- [ ] **Step 6: Commit**

```bash
git add source/extras/ik_channels.py tests/test_ik_dependency_audit_blender.py
git commit -m "Split the IK dependency audit from multi-limb batching"
```

---

### Task 4: Reach the fast paths without batching

**Files:**
- Modify: `source/extras/ik_channels.py` (`match`, the `batch`, `_defer_match_meshes` and `fast` expressions at lines 1300–1311)
- Test: `tests/test_ik_single_chain_fast_blender.py`

**Interfaces:**
- Consumes: `_is_self_contained` and `_can_batch_match` from Task 3.
- Produces: no new public names. `match` gains a local `self_contained` bool; `fast` no longer depends on `batch`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_single_chain_fast_blender.py`. It forces a genuine one-job match by narrowing `ik.chains`, which is the single place `match` enumerates jobs:

```python
"""One selected chain reaches direct sampling and isolated solving, exactly."""
from pathlib import Path
from contextlib import contextmanager
import os, json, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
fast = importlib.import_module(MODULE+'.source.extras.ik_match_fast')
compat = importlib.import_module(MODULE+'.source.anim.fcurve_compat')

counts = dict(sampled=0, isolated=0)
sample_original, isolate_original = fast.sample_fk, fast.isolated

def sample(*args):
    result = sample_original(*args)
    counts['sampled'] += int(result is not None)
    return result

@contextmanager
def isolate(context, obj, *args):
    with isolate_original(context, obj, *args) as result:
        counts['isolated'] += int(result[1] != obj)
        yield result

fast.sample_fk, fast.isolated = sample, isolate

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 19
    return obj

def snapshot(obj):
    keys = sorted((f.data_path, f.array_index,
                   [(tuple(k.co), k.interpolation) for k in f.keyframe_points])
                  for f in compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    poses = []
    for frame in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end+1):
        bpy.context.scene.frame_set(frame)
        poses.append([[tuple(r) for r in b.matrix] for b in obj.pose.bones])
    return json.dumps([keys, poses])

real_chains = ik.chains
results = []
try:
    # match() reads its jobs from chains(); one job is the case under test.
    ik.chains = lambda obj, limbs='BOTH': list(real_chains(obj, limbs))[:1]
    for enabled in (False, True):
        obj = reload()
        assert len(list(ik.chains(obj))) == 1
        counts.update(sampled=0, isolated=0)
        ik.match(bpy.context, obj, _batch=True, _fast=enabled)
        results.append((snapshot(obj), dict(counts)))
finally:
    ik.chains = real_chains

assert results[0][0] == results[1][0], 'single-chain fast path changed the output'
assert results[0][1] == dict(sampled=0, isolated=0), results[0][1]
assert results[1][1] == dict(sampled=1, isolated=1), results[1][1]
print('IK_SINGLE_CHAIN_FAST_OK')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_single_chain_fast_blender.py
```

Expected: FAIL on `assert results[1][1] == dict(sampled=1, isolated=1)`, reporting `dict(sampled=0, isolated=0)` — the fast paths never ran because `batch` was false.

- [ ] **Step 3: Gate the fast paths and mesh deferral on self-containment**

In `source/extras/ik_channels.py`, in `match`, replace

```python
            batch = _batch and _can_batch_match(obj, jobs)
```

with

```python
            self_contained = _is_self_contained(obj, jobs)
            batch = _batch and self_contained and _can_batch_match(obj, jobs)
```

replace

```python
            with _defer_match_meshes(context, obj, batch and len(frames) > 1):
```

with

```python
            with _defer_match_meshes(context, obj, self_contained and len(frames) > 1):
```

and replace

```python
                fast = (_fast and batch and key and entire and len(frames) >= 16
                        and bpy.app.version[:2] in {(4, 5), (5, 2)})
```

with

```python
                # Isolation and direct sampling need the rig to be one closed
                # dependency island. They do not need two limbs to be
                # independent of each other -- that is only what scheduling
                # them into a shared graph update requires.
                fast = (_fast and self_contained and key and entire and len(frames) >= 16
                        and bpy.app.version[:2] in {(4, 5), (5, 2)})
```

`_can_batch_match` still runs its own audit. Calling both is one extra traversal per match, not per frame, and keeps `_can_batch_match` independently correct for its other callers and tests.

- [ ] **Step 4: Run the new test**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_single_chain_fast_blender.py
```

Expected: PASS, printing `IK_SINGLE_CHAIN_FAST_OK`.

- [ ] **Step 5: Run the exactness suite across versions**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.4/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS on each. 4.4 must still take the slow path — `fast` stays version-gated — and must still produce identical output.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_animation_workflow_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_foot_contact_regressions_blender.py
```

Expected: PASS on both.

- [ ] **Step 6: Measure the control**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_shyguy_match_blender.py
```

Expected: PASS with `SHYGUY_EXACT_PAIRS 6` and fingerprints identical to `.tests/benchmarks/shyguy_ik_repro/paired.json` from before this task. The Shy Guy fixture has two leg chains and already batches, so this task should move its timings by roughly nothing. That is the point: if the Shy Guy numbers move, Task 4 changed something it should not have.

- [ ] **Step 7: Commit**

```bash
git add source/extras/ik_channels.py tests/test_ik_single_chain_fast_blender.py
git commit -m "Let a single IK chain reach the sampling and isolation fast paths"
```

---

### Task 5: Measure three reductions to the isolated clone's dependencies

This task **changes no production default**. It adds three reductions behind an environment flag, measures them, and writes the result down. Task 6 adopts the winners.

**Files:**
- Modify: `source/extras/ik_match_fast.py` (`isolated`, plus three new helpers)
- Modify: `source/extras/ik_channels.py` (`_sample_names`, and the `solve_context` unpacking in `match`)
- Create: `tests/benchmark_isolated_dependencies_blender.py`
- Create: `docs/benchmarks/isolated-dependencies-2026-09-13.md`
- Create: `docs/benchmarks/isolated-dependencies-2026-09-13.json`

**Interfaces:**
- Consumes: `ik_match_diag.record()` stage timings from Task 2; `isolated` as restructured in Task 2.
- Produces:
  - `ik_match_fast._reductions() -> frozenset[str]` — parsed from `SUB_IK_REDUCE`, a comma-separated subset of `action`, `pin`, `bbone`.
  - `ik_match_fast._prune_action(clone, needed) -> None`
  - `ik_match_fast._collapse_bbones(data, needed) -> None`
  - `ik_match_fast._pin_ancestors(context, clone, data, keep) -> list[str]`
  - `ik_match_fast.isolated` now yields a **4-tuple** `(context, obj, scene, pinned)`; both the success and the fallback yield are updated, and `match` unpacks four values.

- [ ] **Step 1: Add the flag parser and the three reductions**

In `source/extras/ik_match_fast.py`, add `import os` and:

```python
# Experimental reductions to the isolated clone's dependency graph, measured by
# tests/benchmark_isolated_dependencies_blender.py. Empty by default: each one
# must be shown both exact and faster before it becomes a default.
def _reductions():
    return frozenset(f for f in os.environ.get('SUB_IK_REDUCE', '').split(',') if f)


def _prune_action(clone, needed):
    """Give the clone its own action with only the retained bones' channels.

    obj.copy() shares the action datablock, so the original must never be
    edited. The copy is removed along with the clone by the caller's cleanup.
    """
    anim = clone.animation_data
    if not anim or not anim.action:
        return
    action = anim.action.copy()
    anim.action = action
    keep = tuple(clone.pose.bones[n].path_from_id() + '.' for n in needed
                 if n in clone.pose.bones)
    from ..anim.fcurve_compat import get_all_action_fcurves, remove_fcurve
    for fc in list(get_all_action_fcurves(action, id_type='OBJECT')):
        if fc.data_path.startswith('pose.bones[') and not fc.data_path.startswith(keep):
            remove_fcurve(action, fc, id_type='OBJECT')


def _collapse_bbones(data, needed):
    """Drop B-Bone subdivision on retained bones.

    Segment evaluation runs on every graph update. It should not be able to
    move pb.matrix, which is the only thing the search reads -- but that is a
    claim for the exactness gate to confirm, not an assumption to build on.
    """
    for bone in data.bones:
        if bone.name in needed and bone.bbone_segments > 1:
            bone.bbone_segments = 1


def _pin_ancestors(context, clone, data, keep):
    """Unparent the retained bones that exist only to carry an ancestor pose.

    Bones in `keep` are the ones the solve actually touches. Their ancestors
    are retained today only so the evaluated parent pose is right. Those poses
    are already sampled, so the topmost kept bone can be pinned from its sample
    and its own ancestors dropped -- turning a walk up the spine into one bone.

    Returns the names whose world matrices the caller must apply each frame.
    Rest data is untouched: matrix_local is armature space and does not depend
    on the parent, and the caller's existing rest verification re-checks it.
    """
    pinned = []
    with context.temp_override(object=clone, active_object=clone):
        bpy.ops.object.mode_set(mode='EDIT')
        for name in sorted(keep):
            bone = data.edit_bones.get(name)
            if bone is None or bone.parent is None or bone.parent.name in keep:
                continue
            bone.parent = None
            pinned.append(name)
        bpy.ops.object.mode_set(mode='OBJECT')
    return pinned
```

- [ ] **Step 2: Wire the reductions into `isolated`**

Hoist the pre-closure bone set so `pin` can rebuild the closure. Replace

```python
        needed = set()
        for _,names,target,pole in jobs:
            needed.update(ik.PREFIX+n for n in ik.limb_path(obj,names))
            needed.update((target,pole))
            needed.update((ik.foot_controls(names,obj) or ())[:3])
            needed.update((ik.toe_articulation(obj,names) or ())[:2])
```

with

```python
        direct = set()
        for _,names,target,pole in jobs:
            direct.update(ik.PREFIX+n for n in ik.limb_path(obj,names))
            direct.update((target,pole))
            direct.update((ik.foot_controls(names,obj) or ())[:3])
            direct.update((ik.toe_articulation(obj,names) or ())[:2])
        needed = set(direct)
```

leaving the existing closure loop unchanged. After the closure loop and the constraint retargeting, and before the edit-bone prune, insert:

```python
        pinned = []
        reductions = _reductions()
        if 'pin' in reductions:
            pinned = _pin_ancestors(context, clone, data, direct)
            needed = set(direct)
            while True:
                old = set(needed)
                for name in old:
                    pb = clone.pose.bones.get(name)
                    if pb is None:
                        continue
                    if pb.parent and name not in pinned:
                        needed.add(pb.parent.name)
                    for con in pb.constraints:
                        for prop, sub in (('target','subtarget'),('pole_target','pole_subtarget')):
                            if getattr(con, prop, None) in (obj, clone):
                                needed.add(getattr(con, sub, ''))
                if needed == old:
                    break
        if 'action' in reductions:
            _prune_action(clone, needed)
        if 'bbone' in reductions:
            _collapse_bbones(data, needed)
```

Change the success yield to `yield context, clone, scene, pinned` and the trailing fallback yield to `yield context, obj, context.scene, []`.

- [ ] **Step 3: Place the pinned bones in `match`**

In `source/extras/ik_channels.py`, extend `_sample_names` so every solve-relevant bone's parent is also sampled. After the existing loop body, before the `return`:

```python
    for name in list(names):
        pose_bone = obj.pose.bones.get(name)
        parent = pose_bone.parent if pose_bone is not None else None
        if parent is not None and parent.name not in names:
            names.append(parent.name)
```

This is additive: extra sampled bones cost sampling time and change no output, and `pin` needs a world matrix for each unparented bone.

Then update the solve context and the per-frame loop:

```python
                solve_context = (ik_match_fast.isolated(context, obj, jobs, sys.modules[__name__])
                                 if fast and ik_match_fast.can_isolate(obj, jobs, sys.modules[__name__])
                                 else nullcontext((context, obj, scene, [])))
                with solve_context as (work_context, work_obj, work_scene, pinned):
                    for frame, matrices in samples.items():
                        work_scene.frame_set(frame)
                        for name in pinned:
                            pose_math.apply_world(work_obj.pose.bones[name], matrices[name], None)
                        with diag.stage('place'):
                            steps = [
                                _match_chain_steps(work_obj, job, matrices, frame, key, writer,
                                                   cache[job[2]], previous_pole, native_factory)
                                for job in jobs
                            ]
                        _evaluate_match_steps(work_context, steps, batch)
```

Indexing `matrices[name]` unguarded is deliberate: if a pinned bone has no sample, `pin` is unsound for that rig and must fail loudly during measurement rather than silently leaving the bone at rest.

- [ ] **Step 4: Write the measurement harness**

Create `tests/benchmark_isolated_dependencies_blender.py`:

```python
"""Time each isolated-clone dependency reduction against the exact baseline."""
from pathlib import Path
import os, importlib, json, time, hashlib, statistics

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
os.environ['SUB_IK_DIAG'] = '1'
ik = importlib.import_module(MODULE+'.source.extras.ik_channels')
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')
curves = importlib.import_module(MODULE+'.source.anim.fcurve_compat')
out = ROOT/'.tests/benchmarks/shyguy_ik_repro'
report = ROOT/'docs/benchmarks/isolated-dependencies-2026-09-13.json'

def fingerprint(obj):
    keys = sorted((f.data_path, f.array_index,
                   [(tuple(k.co), k.interpolation) for k in f.keyframe_points])
                  for f in curves.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    digest = hashlib.sha256()
    for f in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end+1):
        bpy.context.scene.frame_set(f)
        digest.update(json.dumps([[tuple(r) for r in b.matrix] for b in obj.pose.bones]).encode())
    return dict(keys=hashlib.sha256(json.dumps(keys).encode()).hexdigest(), poses=digest.hexdigest())

def run(flags):
    os.environ['SUB_IK_REDUCE'] = flags
    bpy.ops.wm.open_mainfile(filepath=str(out/'matched_wait.blend'))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    start = time.perf_counter()
    assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT', cleanup_mode='LEGS',
                                         entire_animation=True) == {'FINISHED'}
    elapsed = time.perf_counter() - start
    snap = diag.record()
    return dict(flags=flags or 'baseline', seconds=elapsed, stages=snap['stages'],
                counts=snap['counts'], reasons=snap['reasons'], **fingerprint(obj))

variants = ('', 'action', 'pin', 'bbone', 'action,pin,bbone')
rows = []
for repeat in range(3):
    for flags in variants:
        row = run(flags)
        row['repeat'] = repeat
        rows.append(row)
        print('ISOLATED_REDUCTION', row, flush=True)
        report.write_text(json.dumps(rows, indent=2))

base = next(r for r in rows if r['flags'] == 'baseline')
for flags in variants:
    group = [r for r in rows if r['flags'] == (flags or 'baseline')]
    exact = all(r['keys'] == base['keys'] and r['poses'] == base['poses'] for r in group)
    median = statistics.median(r['seconds'] for r in group)
    search = statistics.median(r['stages'].get('search', 0.0) for r in group)
    updates = statistics.median(r['counts'].get('search', 0) for r in group)
    print('ISOLATED_SUMMARY', dict(flags=flags or 'baseline', exact=exact, median=median,
                                   search=search, updates=updates), flush=True)
report.write_text(json.dumps(rows, indent=2))
print('ISOLATED_REDUCTIONS_DONE', len(rows), flush=True)
```

This harness deliberately does **not** assert exactness. A reduction that changes output is a result to record, not a test failure; exactness becomes a gate in Task 6.

- [ ] **Step 5: Confirm the baseline is untouched**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_shyguy_match_blender.py
```

Expected: PASS with `SHYGUY_EXACT_PAIRS 6`. `SUB_IK_REDUCE` is unset there, so every reduction is off and this must be unchanged from Task 4. This also proves the 4-tuple yield and the `_sample_names` extension changed nothing on their own.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS, printing `FAST_MATCH_EXACT_AND_CLEANUP_OK`. Note this test wraps `fast.isolated` and forwards `result`, so it is agnostic to the tuple width; confirm that is still true after the change.

- [ ] **Step 6: Run the measurement**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_isolated_dependencies_blender.py
```

Expected: `ISOLATED_REDUCTIONS_DONE 15` with five `ISOLATED_SUMMARY` lines.

- [ ] **Step 7: Write the results up**

Create `docs/benchmarks/isolated-dependencies-2026-09-13.md` following the structure of `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`: environment and fixture, a table of median seconds plus `search` seconds and update count per flag with the speedup against baseline, the exactness verdict per flag, and an explicit adoption recommendation per reduction. State plainly which reductions failed exactness and which were exact but not faster. End with the reproduce command.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_match_fast.py source/extras/ik_channels.py tests/benchmark_isolated_dependencies_blender.py docs/benchmarks/isolated-dependencies-2026-09-13.md docs/benchmarks/isolated-dependencies-2026-09-13.json
git commit -m "Measure three reductions to the isolated IK clone's dependencies"
```

---

### Task 6: Adopt the reductions that are exact and faster

**Files:**
- Modify: `source/extras/ik_match_fast.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/benchmarks/isolated-dependencies-2026-09-13.md`
- Test: `tests/test_ik_match_fast_blender.py` (append)

**Interfaces:**
- Consumes: the measured verdicts from Task 5.
- Produces:

```python
_DEFAULT_REDUCTIONS = frozenset()  # replaced by the adopted set in Step 3


def _reductions():
    override = os.environ.get('SUB_IK_REDUCE')
    if override is None:
        return _DEFAULT_REDUCTIONS
    return frozenset(f for f in override.split(',') if f)
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ik_match_fast_blender.py`, before its final `print`:

```python
# Adopted reductions are on by default and still exact. The scenario matrix
# above already ran with them, so this only pins the default itself.
assert 'SUB_IK_REDUCE' not in os.environ
assert fast._reductions() == fast._DEFAULT_REDUCTIONS, fast._reductions()
assert fast._reductions(), 'no reduction adopted; delete this line and say why in the changelog'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: FAIL on the empty `_DEFAULT_REDUCTIONS`.

- [ ] **Step 3: Set the default from the measurement**

Replace `_reductions` with the two-part form in the Interfaces block above and set `_DEFAULT_REDUCTIONS` to exactly the flags Task 5 measured as both exact and faster.

**If a reduction was not exact it is not adopted, however fast it was** — delete its helper and its branch rather than leaving a trap behind a flag. If no reduction qualified, delete the last assertion from Step 1, keep `_DEFAULT_REDUCTIONS = frozenset()`, remove the helpers that failed, and record the negative result in the changelog. A measured "no" is a valid outcome of this task.

- [ ] **Step 4: Run the exactness suite on both fast-path versions**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS on both, printing `FAST_MATCH_EXACT_AND_CLEANUP_OK`. Every scenario in that matrix — `object_scale`, `object_animation`, `parent_scale`, `inheritance`, `stretch`, `arm_pull`, `foot_controls`, `animated_stretch`, `rematch` — must stay exact with the reductions on. `parent_scale` and `inheritance` are the ones `pin` is most likely to break, because they are exactly the cases where an ancestor's evaluated transform matters.

- [ ] **Step 5: Confirm the headline number and the control**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_shyguy_match_blender.py
```

Expected: PASS with `SHYGUY_EXACT_PAIRS 6` and fingerprints identical to the pre-Task-5 baseline. Record the new fast-path seconds and the speedup against the 3.9115 s import / 3.9671 s match fast-paths-off figures in `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/profile_shyguy_updates_blender.py
```

Expected: the `search` share of total time has fallen. The graph-update **count** must be unchanged at about 4,292 — this plan makes updates cheaper, never fewer. A changed count means the candidate sequence moved; revert and diagnose.

- [ ] **Step 6: Update the write-up and the changelog**

Append an "Adopted" section to `docs/benchmarks/isolated-dependencies-2026-09-13.md` with the Step 5 numbers. Add to `CHANGELOG.md` under the unreleased heading: the fast paths now apply to single-chain matches; matching reports stage timings under `SUB_IK_DIAG=1`; fast-path rejections now name their reason; and whichever dependency reductions were adopted, with the measured speedup and the statement that the output is byte-identical.

- [ ] **Step 7: Run the whole affected set once more**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_diag_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_dependency_audit_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_single_chain_fast_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_direct_exact_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_animation_workflow_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_foot_contact_regressions_blender.py
```

Expected: PASS on all six.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_match_fast.py tests/test_ik_match_fast_blender.py docs/benchmarks/isolated-dependencies-2026-09-13.md CHANGELOG.md
git commit -m "Adopt the measured isolated-clone dependency reductions"
```

---

## Notes for the executor

- **The control that matters:** the graph-update count stays at ~4,292 on the Shy Guy fixture through every task. This plan makes each update cheaper and makes the fast paths reachable more often. If the count changes, the candidate sequence changed and the work has left its scope.
- **`pin` is the risky reduction.** It replaces "evaluate the ancestor chain" with "trust the sampled world matrix". It is exact only where `pose_math.apply_world` can place the bone exactly, which is why Task 5 measures it separately and Task 6 Step 4 names `parent_scale` and `inheritance`.
- **A negative result is a result.** Task 6 explicitly permits adopting nothing. Do not weaken the exactness gate to make a reduction adoptable.
- **Not in scope:** a closed-form pole angle. The measured attempt scored lower on the residual while drifting the end effector further from the FK pose (worst-case limb error 0.415 → 0.622); replacing the search needs a separately validated solver, not a faster sampling vehicle.
