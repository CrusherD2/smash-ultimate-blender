# Adaptive IK Search and Native Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the cost of IK matching for every user by making the pole search stop when it has converged instead of always running 12 steps, and make the existing native solver shippable — both judged by one outcome-based acceptance gate rather than by bit-identity with Blender.

**Architecture:** Three pieces in order. First generalise the existing residual harness so it can judge any two match implementations against a widened corpus, with a tolerance derived from this project's own precedent. Then make the search's stopping rule adaptive behind a flag and measure it. Then re-run the same gate against the native backend and flip its default if it holds. Every piece is measurable alone, and each may legitimately conclude "no".

**Tech Stack:** Python 3.11 / `bpy` (Blender 4.4–5.2), `mathutils`, an existing Rust solver behind `ctypes` FFI, single-script Blender tests driven by `tests/run_blender_test.py`.

**Spec:** `docs/superpowers/specs/2026-09-13-adaptive-ik-search-design.md`

## Global Constraints

- Blender 4.4, 4.5, 5.0, 5.1 and 5.2 keep working. Fast paths stay gated to `bpy.app.version[:2] in {(4, 5), (5, 2)}`.
- No new third-party dependency, Python or Rust. No solver is written or rewritten.
- Every existing guard and fallback is preserved. This work loosens an *acceptance criterion*, never a safety check.
- **Acceptance gate (spec R1.2).** A change passes only when all hold against the baseline, per clip and configuration: no frame's residual exceeds baseline by more than `1e-5` *relative to that frame's baseline residual*; the median per-frame residual does not increase; the clip's total residual does not increase; and no bone moves more than `1e-4` world units. Frames better/worse/identical and the evaluation count are always reported.
- Default behaviour must not change until a task explicitly flips a default. Every new path is behind an environment flag that is off by default.
- Run every Blender test with `PYTHONIOENCODING=utf-8`; the launcher prints characters the Windows console codepage cannot encode.
- Blender executables: `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe` and `.../Blender 4.5/blender.exe`.
- `tests/test_ik_match_fast_blender.py` fails on Blender 4.4 for a pre-existing, unrelated reason. Out of scope; do not run 4.4, do not chase it.
- Work happens in the `ik-adaptive-search` worktree, branch `ik-adaptive-search`. Commit there freely; never touch `animation-workflow`.

---

### Task 1: Generalise the residual harness into a reusable gate

**Files:**
- Create: `tests/ik_match_gate.py`
- Modify: `tests/test_native_ik_residual_matrix_blender.py`
- Test: `tests/test_ik_match_gate_blender.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ik_match_gate.VARIANTS: dict[str, dict]` — each `{'env': {...}, 'engage': str | None}`. `env` is applied via `os.environ` before a run; `engage` names the `ik_match_diag` count key that must be non-zero for the run to be considered to have exercised the variant (`None` means no engagement requirement).
  - `ik_match_gate.run_variant(variant, source, scenario, limbs) -> dict` with keys `residuals: dict[int, float]`, `poses: dict[int, dict[str, Matrix]]`, `names: list[str]`, `counts: dict[str, int]`, `seconds: float`.
  - `ik_match_gate.compare(baseline, candidate, names, tolerance) -> dict` with keys `frames_worse: int`, `frames_better: int`, `frames_identical: int`, `worst_relative_delta: float`, `worst_relative_frame: int | None`, `median_delta: float`, `total_delta: float`, `max_pose_difference: float`, `max_pose_difference_at: str | None`, `passed: bool`.
  - `ik_match_gate.TOLERANCE` — `{'relative': 1e-5, 'pose': 1e-4}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_match_gate_blender.py`:

```python
"""The gate must call a run identical to itself a pass, and a worse one a fail."""
from pathlib import Path
import importlib, os, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate')

BASELINE = ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'
if not BASELINE.exists():
    print(f'SKIP gate test, no baseline at {BASELINE}')
    raise SystemExit(0)

# Same variant twice must be identical: zero worse, zero better, zero pose delta.
a = gate.run_variant('blender', BASELINE, 'normal', 'BOTH')
b = gate.run_variant('blender', BASELINE, 'normal', 'BOTH')
same = gate.compare(a, b, a['names'], gate.TOLERANCE)
assert same['passed'], same
assert same['frames_worse'] == 0 and same['frames_better'] == 0, same
assert same['max_pose_difference'] == 0.0, same
assert same['frames_identical'] == len(a['residuals']), same

# A synthetic degradation must fail the gate, so a pass cannot be vacuous.
worse = dict(b)
worse['residuals'] = dict(b['residuals'])
victim = sorted(worse['residuals'])[len(worse['residuals']) // 2]
worse['residuals'][victim] = worse['residuals'][victim] * 1.5 + 1.0
verdict = gate.compare(a, worse, a['names'], gate.TOLERANCE)
assert not verdict['passed'], verdict
assert verdict['frames_worse'] == 1, verdict
assert verdict['worst_relative_frame'] == victim, verdict

# The engagement requirement must fail a run that never exercised its variant.
empty = dict(a)
empty['counts'] = {}
try:
    gate.require_engaged('native', empty)
except AssertionError:
    pass
else:
    raise AssertionError('require_engaged accepted a run with no engagement')

print('IK_MATCH_GATE_OK')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_gate_blender.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ik_match_gate'`.

- [ ] **Step 3: Write the gate module**

Create `tests/ik_match_gate.py`. Lift `active_armature`, `limb_bone_names`, `capture`, `residuals` and `configure` verbatim from `tests/test_native_ik_residual_matrix_blender.py` (lines 50–124) — they are correct and must not drift — then add the variant and comparison layers:

```python
"""Compare any two IK match implementations under the project's acceptance gate.

Generalised from tests/test_native_ik_residual_matrix_blender.py, which compared
exactly two hard-coded backends. The residual and pose comparisons are unchanged;
what is new is that the implementation under test is selected by name, and that
the verdict carries a tolerance instead of demanding no frame ever fit worse.
"""
import importlib, json, os, statistics, time
from pathlib import Path
import bpy

MODULE = __name__.rsplit('.', 1)[0] if '.' in __name__ else None

# Set by the importing test script, which has already resolved the add-on module.
def bind(module_name):
    global ik, ik_native, diag, MODULE
    MODULE = module_name
    ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
    ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')
    diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')


TOLERANCE = {'relative': 1e-5, 'pose': 1e-4}

# 'env' is applied before the run; every key absent from a variant's env is
# removed, so variants cannot leak into one another. 'engage' names the
# ik_match_diag count that proves the variant actually ran.
VARIANTS = {
    'blender':  {'env': {'SUB_NATIVE_IK': '0'},                              'engage': None},
    'native':   {'env': {'SUB_NATIVE_IK': 'experimental'},                   'engage': 'native_solves'},
    'adaptive': {'env': {'SUB_NATIVE_IK': '0', 'SUB_IK_ADAPTIVE': '1'},      'engage': 'adaptive_early'},
}
_MANAGED = ('SUB_NATIVE_IK', 'SUB_IK_ADAPTIVE')


def apply_env(variant):
    for key in _MANAGED:
        os.environ.pop(key, None)
    os.environ.update(VARIANTS[variant]['env'])
    os.environ['SUB_IK_DIAG'] = '1'


def require_engaged(variant, run):
    key = VARIANTS[variant]['engage']
    if key is None:
        return
    assert run['counts'].get(key, 0) > 0, (
        f'variant {variant!r} never engaged: {key} was {run["counts"].get(key, 0)}')


def run_variant(variant, source, scenario, limbs):
    apply_env(variant)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    obj = active_armature()
    if bpy.context.object.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    ik.create_controls(bpy.context, obj, 'BOTH')
    names = limb_bone_names(obj, limbs)
    configure(obj, scenario)
    fk = capture(obj, names)
    start = time.perf_counter()
    ik.match(bpy.context, obj, limbs=limbs, entire=True, key=True, _batch=True)
    seconds = time.perf_counter() - start
    solved = capture(obj, names)
    return dict(residuals=residuals(fk, solved, names), poses=solved, names=names,
                counts=dict(diag.record()['counts']), seconds=seconds)


def compare(baseline, candidate, names, tolerance):
    base_r, cand_r = baseline['residuals'], candidate['residuals']
    worse = better = identical = 0
    worst_rel, worst_frame = 0.0, None
    deltas = []
    for frame, a in base_r.items():
        b = cand_r[frame]
        delta = b - a
        deltas.append(delta)
        if delta > 0:
            worse += 1
            # Relative to this frame's own baseline, so a large-residual frame
            # is not held to the same absolute bar as a near-perfect one.
            rel = delta / a if a > 0 else float('inf')
            if rel > worst_rel:
                worst_rel, worst_frame = rel, frame
        elif delta < 0:
            better += 1
        else:
            identical += 1

    pose_delta, pose_where = 0.0, None
    for frame, before in baseline['poses'].items():
        after = candidate['poses'][frame]
        for name in names:
            a, b = before[name], after[name]
            for r in range(4):
                for c in range(4):
                    d = abs(a[r][c] - b[r][c])
                    if d > pose_delta:
                        pose_delta, pose_where = d, f'{name}@{frame}[{r}][{c}]'

    median_delta = statistics.median(deltas) if deltas else 0.0
    total_delta = sum(cand_r.values()) - sum(base_r.values())
    passed = (worst_rel <= tolerance['relative']
              and median_delta <= 0.0
              and total_delta <= 0.0
              and pose_delta <= tolerance['pose'])
    return dict(frames_worse=worse, frames_better=better, frames_identical=identical,
                worst_relative_delta=worst_rel, worst_relative_frame=worst_frame,
                median_delta=median_delta, total_delta=total_delta,
                max_pose_difference=pose_delta, max_pose_difference_at=pose_where,
                passed=passed)
```

Note the module needs `bind(MODULE)` called by its importer, because the add-on's module name is the checkout directory name and differs between the main tree and this worktree. Add to the test from Step 1, immediately after the import:

```python
gate.bind(MODULE)
```

- [ ] **Step 4: Add the engagement counter the native variant needs**

`VARIANTS['native']['engage']` is `'native_solves'`, but nothing records it. In `source/extras/ik_native.py`, in `Factory.__call__`, after a solver is successfully created, add:

```python
        if solver is not None:
            diag.add('native_solves', 0.0, 1)
```

`diag.add` with `seconds=0.0` records a count without polluting the stage timings. `ik_native` already imports `ik_match_diag as diag`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_gate_blender.py
```

Expected: PASS, printing `IK_MATCH_GATE_OK`.

- [ ] **Step 6: Reproduce the published native numbers through the new gate**

Rewrite `tests/test_native_ik_residual_matrix_blender.py` to drive `ik_match_gate` instead of its own inlined logic, keeping its ten `CONFIGURATIONS` and its JSON report shape. Then:

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_ik_residual_matrix_blender.py
```

Expected: PASS with `NATIVE_RESIDUAL_MATRIX_OK`, ten configurations, `native_engaged: 10`, `guards_declined: []`, and **`max_pose_difference: 0.0` on every row** — the same result `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md` published. If the refactored harness does not reproduce those numbers, the refactor is wrong; fix it before continuing. Do not update the published doc to match a new number.

- [ ] **Step 7: Commit**

```bash
git add tests/ik_match_gate.py tests/test_ik_match_gate_blender.py tests/test_native_ik_residual_matrix_blender.py source/extras/ik_native.py
git commit -m "Generalise the residual comparison into a reusable acceptance gate"
```

---

### Task 2: Widen the corpus

**Files:**
- Create: `tests/ik_match_corpus.py`
- Create: `tests/build_near_straight_fixture_blender.py`
- Test: `tests/test_ik_match_corpus_blender.py`

**Interfaces:**
- Consumes: `ik_match_gate` from Task 1.
- Produces:
  - `ik_match_corpus.SOURCES: list[dict]` — each `{'name': str, 'blend': Path, 'configurations': [(scenario, limbs), ...]}`.
  - `ik_match_corpus.available() -> list[dict]` — the subset whose `blend` exists, so a missing local fixture skips rather than fails.
  - `ik_match_corpus.NEAR_STRAIGHT: Path` — the generated fixture's location.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_match_corpus_blender.py`:

```python
"""The corpus must contain more than one animation and reach the hard case."""
from pathlib import Path
import importlib, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
corpus = importlib.import_module('ik_match_corpus')

sources = corpus.available()
assert sources, 'corpus is empty; no fixtures resolved'
names = [s['name'] for s in sources]
assert len(set(names)) == len(names), names
# The whole point of widening: more than one animation, not one in ten costumes.
assert len(sources) >= 2, names
assert corpus.NEAR_STRAIGHT.exists(), f'near-straight fixture missing at {corpus.NEAR_STRAIGHT}'
assert any(s['blend'] == corpus.NEAR_STRAIGHT for s in sources), names
total = sum(len(s['configurations']) for s in sources)
print(f'IK_MATCH_CORPUS_OK sources={len(sources)} runs={total}')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_corpus_blender.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ik_match_corpus'`.

- [ ] **Step 3: Build the near-straight fixture**

Create `tests/build_near_straight_fixture_blender.py`. It opens the existing baseline, animates both limbs from a strongly bent pose to within a few thousandths of a radian of fully straight across the clip, and saves to `.tests/benchmarks/ik_corpus/near_straight.blend`. Near-collinear geometry is where the pole search has least signal and where the native guards decline, so this is the case most likely to expose an early-stopping regression.

```python
"""Generate a near-straight limb fixture: the pole search's worst case."""
from pathlib import Path
import math
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
import importlib
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')

BASELINE = ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'
OUT = ROOT / '.tests/benchmarks/ik_corpus/near_straight.blend'
assert BASELINE.exists(), BASELINE
bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
if bpy.context.object.mode != 'POSE':
    bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
scene.frame_end = scene.frame_start + 39
for _kind, chain, _t, _p in ik.chains(obj, 'BOTH'):
    path = ik.limb_path(obj, chain)
    middle = obj.pose.bones[ik.bend_name(obj, chain)]
    middle.rotation_mode = 'XYZ'
    for index, frame in enumerate(range(scene.frame_start, scene.frame_end + 1)):
        t = index / (scene.frame_end - scene.frame_start)
        # 0.9 rad of bend down to 0.002 rad: straight enough that the bend plane
        # is nearly undefined, without being exactly singular.
        middle.rotation_euler.x = 0.9 * (1.0 - t) + 0.002 * t
        middle.keyframe_insert('rotation_euler', index=0, frame=frame)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f'NEAR_STRAIGHT_FIXTURE_OK {OUT} frames={scene.frame_end - scene.frame_start + 1}')
```

Run it:

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/build_near_straight_fixture_blender.py
```

Expected: `NEAR_STRAIGHT_FIXTURE_OK` and the file exists. If `ik.bend_name` needs different arguments than shown, read its signature in `source/extras/ik_channels.py` and adapt — do not guess.

- [ ] **Step 4: Write the corpus module**

Create `tests/ik_match_corpus.py`:

```python
"""The fixtures the acceptance gate is run against.

The prior evidence was ten rig configurations of a single animation, which
varies the rig and never the motion. This adds distinct motion and a distinct
rig, plus the generated near-straight worst case.

A fixture that is not present locally is skipped, not failed: the large .blend
files live under .tests/ and are not distributed.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / '.tests' / 'benchmarks'
NEAR_STRAIGHT = BENCH / 'ik_corpus' / 'near_straight.blend'

# The ten configurations the existing matrix uses. Kept as the default set so a
# widened corpus is a superset of the published evidence, never a replacement.
FULL = [('normal', 'BOTH'), ('normal', 'ARMS'), ('normal', 'LEGS'),
        ('object_scale', 'BOTH'), ('parent_scale', 'BOTH'), ('inheritance', 'BOTH'),
        ('stretch', 'BOTH'), ('arm_pull', 'BOTH'), ('animated_stretch', 'BOTH'),
        ('foot_controls', 'BOTH')]
# Secondary fixtures carry a reduced set: distinct motion is the variable being
# added, and repeating all ten on every clip multiplies runtime without
# multiplying evidence.
LIGHT = [('normal', 'BOTH'), ('parent_scale', 'BOTH'), ('stretch', 'BOTH')]

SOURCES = [
    {'name': 'baseline',      'blend': BENCH / 'ik_apply/out/baseline.blend',       'configurations': FULL},
    {'name': 'near_straight', 'blend': NEAR_STRAIGHT,                                'configurations': LIGHT},
    {'name': 'shyguy_wait',   'blend': BENCH / 'shyguy_ik_repro/matched_wait.blend', 'configurations': [('normal', 'LEGS')]},
]


def available():
    override = os.environ.get('SUB_IK_CORPUS')
    wanted = set(override.split(',')) if override else None
    return [s for s in SOURCES if s['blend'].exists()
            and (wanted is None or s['name'] in wanted)]
```

Note `shyguy_wait` carries only `('normal', 'LEGS')`: that fixture is a fully-built foot-IK rig on a different armature, and the `configure()` scenarios assume the baseline rig's structure. Its value is a different rig and different motion, not more configurations.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_corpus_blender.py
```

Expected: PASS, printing `IK_MATCH_CORPUS_OK` with `sources=3`.

- [ ] **Step 6: Record the baseline table**

Create and run a script that walks `corpus.available()`, runs the `blender` variant on each configuration, and writes per-run residual totals, frame counts and the `search` evaluation count to `docs/benchmarks/ik-corpus-baseline-2026-09-13.json`. This is the reference every later comparison is made against; without it Tasks 3 and 5 have nothing to compare to.

- [ ] **Step 7: Commit**

```bash
git add tests/ik_match_corpus.py tests/build_near_straight_fixture_blender.py tests/test_ik_match_corpus_blender.py docs/benchmarks/ik-corpus-baseline-2026-09-13.json
git commit -m "Widen the IK acceptance corpus beyond one animation"
```

---

### Task 3: Adaptive stopping rule, behind a flag

**Files:**
- Modify: `source/extras/ik_channels.py` (`_match_chain_steps`, the refinement block)
- Test: `tests/test_ik_adaptive_search_blender.py`

**Interfaces:**
- Consumes: `ik_match_diag` (`add`), `ik_match_gate`, `ik_match_corpus`.
- Produces:
  - `ik_channels._adaptive_enabled() -> bool` — `os.environ.get('SUB_IK_ADAPTIVE') == '1'`, off by default.
  - Diagnostic counts: `candidates` (total `error()` evaluations performed) and `adaptive_early` (searches that stopped before the step cap). Both recorded unconditionally via `diag.add(name, 0.0, 1)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_adaptive_search_blender.py`:

```python
"""Adaptive search must cost less, stay within the gate, and be off by default."""
from pathlib import Path
import importlib, os, sys, json

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate'); gate.bind(MODULE)
corpus = importlib.import_module('ik_match_corpus')

source = next((s for s in corpus.available() if s['name'] == 'baseline'), None)
if source is None:
    print('SKIP adaptive test, no baseline fixture')
    raise SystemExit(0)

base = gate.run_variant('blender', source['blend'], 'normal', 'BOTH')
adap = gate.run_variant('adaptive', source['blend'], 'normal', 'BOTH')
gate.require_engaged('adaptive', adap)
verdict = gate.compare(base, adap, base['names'], gate.TOLERANCE)
print('ADAPTIVE_VERDICT ' + json.dumps({**verdict,
      'candidates_baseline': base['counts'].get('candidates'),
      'candidates_adaptive': adap['counts'].get('candidates')}))

# The whole point: strictly less work. Never more than the fixed search.
assert adap['counts']['candidates'] < base['counts']['candidates'], (
    base['counts'], adap['counts'])
assert verdict['passed'], verdict

# Off by default: no flag means the fixed search and no early stops.
os.environ.pop('SUB_IK_ADAPTIVE', None)
plain = gate.run_variant('blender', source['blend'], 'normal', 'BOTH')
assert plain['counts'].get('adaptive_early', 0) == 0, plain['counts']
assert plain['counts']['candidates'] == base['counts']['candidates'], (
    plain['counts'], base['counts'])
print('IK_ADAPTIVE_SEARCH_OK')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_adaptive_search_blender.py
```

Expected: FAIL — `adaptive` never engages, so `require_engaged` raises `AssertionError: variant 'adaptive' never engaged`.

- [ ] **Step 3: Count candidate evaluations**

In `source/extras/ik_channels.py`, inside `_match_chain_steps`'s `error(angle)` closure, immediately after the memo check that returns a cached score, record one evaluation:

```python
    def error(angle):
        if angle in errors:
            return errors[angle]
        diag.add('candidates', 0.0, 1)
        con.pole_angle = math.atan2(math.sin(angle), math.cos(angle))
```

The counter goes *after* the memo check deliberately: a repeated candidate costs nothing and must not inflate the count.

- [ ] **Step 4: Make the stopping rule adaptive**

Still in `_match_chain_steps`, replace the fixed refinement loop. The current shape is a golden-section loop running exactly `_POLE_REFINE_STEPS` iterations. Change only when it stops:

```python
        if (yield from error(angle)) > _POLE_TOLERANCE:
            lo, hi = angle - .2, angle + .2
            ratio = (math.sqrt(5.0)-1.0)*.5
            a, b = hi-ratio*(hi-lo), lo+ratio*(hi-lo)
            fa = yield from error(a)
            fb = yield from error(b)
            adaptive = _adaptive_enabled()
            steps = 0
            for _ in range(_POLE_REFINE_STEPS):
                if fa < fb:
                    hi, b, fb = b, a, fa
                    a = hi-ratio*(hi-lo)
                    fa = yield from error(a)
                else:
                    lo, a, fa = a, b, fb
                    b = lo+ratio*(hi-lo)
                    fb = yield from error(b)
                steps += 1
                # Stop once the bracket can no longer move the score by more
                # than the acceptance tolerance allows. Relative to the current
                # best score, so a large-residual frame is not held to the same
                # absolute bar as a near-perfect one.
                if adaptive:
                    best = fa if fa < fb else fb
                    if abs(fa - fb) <= _ADAPTIVE_RELATIVE * max(best, 1e-12):
                        diag.add('adaptive_early', 0.0, 1)
                        break
            angle = yield from best((angle, a, b))
```

Add near `_POLE_REFINE_STEPS`:

```python
# Relative bracket width at which the adaptive search stops. Matches the
# acceptance gate's per-frame relative tolerance in
# docs/superpowers/specs/2026-09-13-adaptive-ik-search-design.md, so the search
# cannot stop at a point the gate would reject.
_ADAPTIVE_RELATIVE = 1e-5


def _adaptive_enabled():
    return os.environ.get('SUB_IK_ADAPTIVE') == '1'
```

The loop still runs at most `_POLE_REFINE_STEPS` times, so worst-case cost is exactly today's.

- [ ] **Step 5: Run the test**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_adaptive_search_blender.py
```

Expected: PASS with `IK_ADAPTIVE_SEARCH_OK`, and an `ADAPTIVE_VERDICT` line showing fewer candidates.

**If `verdict['passed']` is false, do not tune the tolerance to make it pass.** Record the numbers and report `DONE_WITH_CONCERNS`. The spec (R2.1) anticipates that Blender's warm-start path-dependence may make early stopping unsafe on this path; establishing that is a valid result and Task 4 acts on it.

- [ ] **Step 6: Run the whole corpus**

Create and run `tests/benchmark_adaptive_corpus_blender.py`, walking every `corpus.available()` source and configuration, comparing `adaptive` against `blender` through the gate, writing every row to `docs/benchmarks/adaptive-search-2026-09-13.json` and printing a per-row summary. Report the total candidate reduction and every failing row.

- [ ] **Step 7: Confirm the default path is untouched**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: PASS with `FAST_MATCH_EXACT_AND_CLEANUP_OK`. `SUB_IK_ADAPTIVE` is unset there, so output must be bit-identical to before this task.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_channels.py tests/test_ik_adaptive_search_blender.py tests/benchmark_adaptive_corpus_blender.py docs/benchmarks/adaptive-search-2026-09-13.json
git commit -m "Add an adaptive pole-search stopping rule behind SUB_IK_ADAPTIVE"
```

---

### Task 4: Decide the adaptive default

**Files:**
- Modify: `source/extras/ik_channels.py`
- Create: `docs/benchmarks/adaptive-search-2026-09-13.md`
- Modify: `tests/test_ik_adaptive_search_blender.py`

**Interfaces:**
- Consumes: Task 3's corpus results.
- Produces: `_adaptive_enabled()` returns the adopted default, overridable by `SUB_IK_ADAPTIVE` (`'0'` forces off, `'1'` forces on).

- [ ] **Step 1: Write the results document**

Create `docs/benchmarks/adaptive-search-2026-09-13.md` following the structure of `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md`: environment, corpus, a per-source table of candidate counts and gate verdicts, the total reduction, and an explicit adoption recommendation. State plainly any configuration that failed the gate, and whether the near-straight fixture behaved differently from real motion.

- [ ] **Step 2: Take the decision**

Three outcomes are permitted, and the corpus decides which:

- **Every configuration passes.** Flip `_adaptive_enabled()` to default on:
  ```python
  def _adaptive_enabled():
      return os.environ.get('SUB_IK_ADAPTIVE', '1') == '1'
  ```
- **Real motion passes but the near-straight fixture fails.** Keep adaptive on, and disable it for a chain whose bend plane is degenerate — that branch already exists in `_match_chain_steps`, where `bend.length` falls below the collinearity threshold and the previous pole is reused. Set a local flag there and skip early stopping for that chain and frame. Add a test asserting the near-straight fixture now passes the gate.
- **Real motion fails.** Leave the default off. Say so in the document, keep the flag for the native path (Task 5), and do not weaken the gate.

- [ ] **Step 3: Update the test to pin the decision**

Amend `tests/test_ik_adaptive_search_blender.py` so it asserts the adopted default explicitly, whichever it is, rather than assuming one:

```python
# Pin the adopted default so a later change cannot flip it silently.
os.environ.pop('SUB_IK_ADAPTIVE', None)
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
assert ik._adaptive_enabled() is <ADOPTED>, 'adaptive default changed without updating this test'
```

- [ ] **Step 4: Run the full suite on both supported versions**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_animation_workflow_blender.py
```

Expected: PASS on all three. **If adaptive was adopted as the default, `test_ik_match_fast_blender.py`'s exactness assertions now compare adaptive against adaptive**, which they should still satisfy — that test compares fast-path-on against fast-path-off, and both sides get the same search. If it fails, the adaptive change is not search-neutral in the way assumed; report it rather than adjusting the test.

- [ ] **Step 5: Measure the headline**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_shyguy_match_blender.py
```

Record `SHYGUY_EXACT_PAIRS`, the fast-path seconds, and the graph-update count. The update count is *expected* to fall now — that is the point of this task — so record the new figure and the reduction against 4,292.

- [ ] **Step 6: Commit**

```bash
git add source/extras/ik_channels.py tests/test_ik_adaptive_search_blender.py docs/benchmarks/adaptive-search-2026-09-13.md
git commit -m "Decide the adaptive search default from the corpus"
```

---

### Task 5: The native backend default

**Files:**
- Modify: `source/extras/ik_native.py` (`get_factory`)
- Modify: `CHANGELOG.md`
- Create: `docs/benchmarks/native-default-2026-09-13.md`
- Test: `tests/test_native_default_blender.py`

**Interfaces:**
- Consumes: `ik_match_gate`, `ik_match_corpus`.
- Produces: `SUB_NATIVE_IK` semantics — unset means the adopted default; `'0'` forces off; `'1'` verification mode; `'experimental'` forces on without verification.

- [ ] **Step 1: Run the widened corpus against the native backend**

Create and run `tests/benchmark_native_corpus_blender.py`, comparing `native` against `blender` through the gate across every corpus source and configuration, on **both** Blender 5.2 and 4.5, writing to `docs/benchmarks/native-default-2026-09-13.json`.

This is the evidence the criterion document named as the prerequisite for flipping the default. Record `native_engaged`, `guards_declined`, per-row `max_pose_difference`, and every gate verdict.

- [ ] **Step 2: Write the failing test**

Create `tests/test_native_default_blender.py`:

```python
"""The native backend's default must be explicit, overridable, and gated."""
from pathlib import Path
import importlib, os, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')

for key in ('SUB_NATIVE_IK',):
    os.environ.pop(key, None)

supported = (sys.platform == 'win32' and bpy.app.version[:2] in {(4, 5), (5, 2)}
             and (ROOT / 'native/bin/sub_ik_match_native.dll').is_file())

factory = ik_native.get_factory()
if supported:
    assert factory is not None, 'native backend did not engage by default on a supported platform'
    factory.close()
else:
    assert factory is None, 'native backend engaged on an unsupported platform'

# An explicit off must always win, on every platform.
os.environ['SUB_NATIVE_IK'] = '0'
assert ik_native.get_factory() is None, 'SUB_NATIVE_IK=0 did not force the native backend off'
os.environ.pop('SUB_NATIVE_IK', None)
print('NATIVE_DEFAULT_OK')
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_default_blender.py
```

Expected: FAIL — with `SUB_NATIVE_IK` unset, `get_factory()` currently returns `None`.

- [ ] **Step 4: Flip the default, only if Step 1 held**

In `source/extras/ik_native.py`, `get_factory()` currently requires `os.environ.get('SUB_NATIVE_IK') in {'1', 'experimental'}`. Change the mode resolution so an unset variable means on, and `'0'` means off, leaving every other guard exactly as it is:

```python
    # Unset means the native backend is on where it is supported. '0' forces it
    # off everywhere; '1' is verification mode; 'experimental' skips verification.
    # Adopted on the evidence in docs/benchmarks/native-default-2026-09-13.md.
    mode = os.environ.get('SUB_NATIVE_IK', 'experimental')
    if (mode not in {'1', 'experimental'} or sys.platform != 'win32'
            or platform.machine().lower() not in {'amd64','x86_64'}
            or bpy.app.version[:2] not in {(4,5),(5,2)}
            or not (Path(__file__).resolve().parents[2] / 'native/bin/sub_ik_match_native.dll').is_file()):
        return None
    return Factory()
```

Check every other read of `SUB_NATIVE_IK` in the codebase and make it consistent with this resolution — `evaluate_steps` reads it to decide verification mode, and tests set it to `'0'` expecting off.

**If Step 1's corpus did not hold, do not make this change.** Record the failing configurations in the results document, leave the default off, and finish the task there. That is a valid outcome.

- [ ] **Step 5: Run the test and the full suite**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_default_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_match_fast_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_ik_residual_matrix_blender.py
```

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_foot_contact_regressions_blender.py
```

Expected: PASS on all five. Tests that assumed the native backend was off by default may now need `SUB_NATIVE_IK=0` set explicitly — that is a legitimate fix, but say so in the report rather than making it silently.

- [ ] **Step 6: Write the results document and changelog**

Create `docs/benchmarks/native-default-2026-09-13.md` with the corpus evidence, both Blender versions, and the decision. Add to `CHANGELOG.md`, matching its existing voice: the native accelerator is on by default on Windows x64 for Blender 4.5 and 5.2, `SUB_NATIVE_IK=0` turns it off, verification mode remains, and results are no longer guaranteed bit-identical to Blender's backend on degenerate geometry.

- [ ] **Step 7: Measure and record the final headline**

```bash
cd "C:/Users/notja/Documents/Coding/SSBU Modding/CrusherD2/ik-adaptive-search" && PYTHONIOENCODING=utf-8 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/benchmark_shyguy_match_blender.py
```

Record the end-to-end figure against the 3.9115 s import / 3.9671 s match fast-paths-off baseline in `docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md`, and against the 2.02x/2.08x recorded at the end of the previous plan.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_native.py tests/test_native_default_blender.py tests/benchmark_native_corpus_blender.py docs/benchmarks/native-default-2026-09-13.md docs/benchmarks/native-default-2026-09-13.json CHANGELOG.md
git commit -m "Enable the native IK backend by default under the residual gate"
```

---

## Notes for the executor

- **Three tasks can legitimately conclude "no".** Task 3 may find early stopping unsafe, Task 4 may keep the default off, Task 5 may not flip. The gate decides, not the plan. Never weaken the gate to reach a yes.
- **The graph-update count is no longer a control.** In the previous plan it had to stay at 4,292; here Task 3 exists to reduce it. Report it every run so the reduction is attributable.
- **The near-straight fixture is expected to be the hard case.** If it is the only failure, Task 4 Step 2's middle branch is the intended response, not a workaround.
- **Path-dependence is the live risk** (spec R2.1). Blender's solver warm-starts, so a shorter search may return a different answer rather than a coarser one. That is precisely what the corpus measures.
