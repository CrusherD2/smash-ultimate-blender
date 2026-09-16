# Native Pole Search — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the per-frame pole-angle search out of Python and into the native module, so a chain costs one FFI call per frame instead of roughly 28 generator round-trips.

**Architecture:** `_match_chain_steps` currently yields a `Request` per candidate angle; each one crosses `ctypes`, rebuilds `mathutils.Matrix` objects, and resumes a Python generator. The search itself — three seed candidates, a tolerance check and a 12-step golden-section refinement — is pure arithmetic over a solver that can produce matrices for an angle. The native module already has that solver. This task moves the search beside it and returns only the winning angle and its matrices. Placement, key writing and every guard stay in Python.

**Tech Stack:** Rust 1.89.0 (cdylib), `ctypes`, Blender 4.5.7 / 5.2.1 Python API.

**Spec:** `docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md`

## Global Constraints

- Windows x64, Blender 4.5 and 5.2 only. Everything else keeps the current path.
- The native backend stays **off by default** for the whole of this plan. Flipping it is a separate decision.
- Acceptance is the criterion established in `docs/benchmarks/native-ik-residual-criterion-2026-09-12.md`: per frame, the native residual against the FK source is never worse than the Blender backend's, and the ten-configuration matrix still reports `max_pose_difference: 0.0`.
- The search's arithmetic and ordering must be preserved exactly: candidate order, the `errors` memo, `min` returning the first of equal scores, and `con.pole_angle` passing through float32 before reaching the solver.
- `SUB_NATIVE_IK=1` verification mode must keep working and must keep comparing against Blender.
- All existing guards in `ik_native.supported()` and `_can_batch_match` remain in force.
- Rust builds stay `--locked --offline`; the Eigen backend still builds only when `SUB_IK_EIGEN_DIR` is set.

---

## File Structure

- Modify `native/ik_match/src/solver.rs` — add the search over an existing solver handle.
- Modify `native/ik_match/src/ffi.rs` — add `sub_ik_search`, bump the ABI version.
- Modify `source/extras/ik_native.py` — `Solver.search()`, ABI check.
- Modify `source/extras/ik_channels.py:1150-1232` — call the native search instead of the candidate loop when native is active.
- Test `tests/test_native_ik_search_blender.py` — the native search returns the same angle as the Python search, chain by chain and frame by frame.

---

## Task 1: Port the search into Rust behind an existing solver handle

**Files:**
- Modify: `native/ik_match/src/solver.rs`
- Test: in-file `mod tests`

**Interfaces:**
- Consumes: the existing per-handle solve, `math::Backend`, `Job`.
- Produces: `solver::search(case: &mut Case, reference: &[[[f64; 3]; 4]], seeds: [f64; 3], tolerance: f64, refine_steps: usize) -> (f64, Vec<[[f32; 4]; 4]>)` returning the winning angle and its solved matrices.

The Python original, for reference while porting (`ik_channels.py:1151-1229`):

```python
errors = {}
def error(angle):
    if angle in errors:
        return errors[angle]
    con.pole_angle = math.atan2(math.sin(angle), math.cos(angle))
    evaluated = solve(con.pole_angle)
    score = sum(sum((matrix.col[i] - reference[i]).length_squared for i in range(4))
                for matrix, reference in zip(evaluated, reference_columns))
    errors[angle] = score
    return score

def best(candidates):
    scores = [(c, error(c)) for c in candidates]
    return min(scores, key=lambda pair: pair[1])[0]

angle = best([delta, -delta, entry['angle'] or 0.0])
if error(angle) > _POLE_TOLERANCE:
    lo, hi = angle - .2, angle + .2
    ratio = (math.sqrt(5.0) - 1.0) * .5
    a, b = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fa, fb = error(a), error(b)
    for _ in range(_POLE_REFINE_STEPS):
        if fa < fb:
            hi, b, fb = b, a, fa
            a = hi - ratio * (hi - lo)
            fa = error(a)
        else:
            lo, a, fa = a, b, fb
            b = lo + ratio * (hi - lo)
            fb = error(b)
    angle = best((angle, a, b))
```

Four details decide whether results match:

1. `con.pole_angle` is a Blender float property, so the angle is rounded to **float32** before the solver sees it. `error` must do `let rounded = (angle.atan2_normalised()) as f32 as f64` — concretely `let p = (angle.sin()).atan2(angle.cos()) as f32;` and solve at `p`.
2. The memo is keyed on the **unrounded** `angle`, not the rounded one.
3. `min` in Python returns the **first** minimum on ties, so the Rust fold must use strict `<`.
4. The score sums bones outer, columns inner, in `path[:-1]` order.

- [ ] **Step 1: Write the failing test**

Append to `mod tests` in `native/ik_match/src/solver.rs`:

```rust
#[test]
fn search_prefers_the_lowest_scoring_seed() {
    // A reference built from the chain solved at a known angle must make that
    // angle win, and must be found without entering refinement.
    let mut case = crate::tests_support::reachable_case();
    let target = 0.35_f64;
    let reference = crate::tests_support::columns_at(&mut case, target);
    let (angle, _) = search(&mut case, &reference, [target, -target, 0.0], 1e-9, 12);
    assert!((angle - target).abs() < 1e-6, "{angle} vs {target}");
}

#[test]
fn search_ties_take_the_first_candidate() {
    let mut case = crate::tests_support::reachable_case();
    let reference = crate::tests_support::columns_at(&mut case, 0.0);
    // All three seeds identical: the first must be returned unchanged.
    let (angle, _) = search(&mut case, &reference, [0.25, 0.25, 0.25], f64::INFINITY, 12);
    assert_eq!(angle, 0.25);
}
```

Add `tests_support` helpers in `native/ik_match/src/lib.rs` behind `#[cfg(test)]`, building the `Case` the existing `reachable_target` test already constructs and returning its solved columns at a given angle. Reuse that test's `Job` literal verbatim rather than inventing new geometry.

- [ ] **Step 2: Run to verify it fails**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline search_
```

Expected: FAIL, `cannot find function search`.

- [ ] **Step 3: Implement the search**

In `native/ik_match/src/solver.rs`:

```rust
/// The pole search from ik_channels._match_chain_steps, moved beside the
/// solver. Candidate order, the memo, tie-breaking and the float32 rounding of
/// the pole angle all have to match the Python original exactly, because the
/// chosen angle is the output.
pub fn search(
    case: &mut Case,
    reference: &[[[f64; 3]; 4]],
    seeds: [f64; 3],
    tolerance: f64,
    refine_steps: usize,
) -> (f64, Vec<[[f32; 4]; 4]>) {
    let mut memo: Vec<(f64, f64)> = Vec::new();
    let mut score_at = |case: &mut Case, angle: f64| -> f64 {
        // The memo is keyed on the unrounded angle, as in Python.
        if let Some(&(_, score)) = memo.iter().find(|(a, _)| *a == angle) {
            return score;
        }
        // Blender stores pole_angle as a float property, so the solver sees a
        // float32 value however precisely the search computed it.
        let rounded = angle.sin().atan2(angle.cos()) as f32;
        let solved = solve_at(case, rounded);
        let mut score = 0.0;
        for (matrix, columns) in solved.iter().zip(reference.iter()) {
            for i in 0..4 {
                let mut sum = 0.0;
                for r in 0..3 {
                    let d = matrix[r][i] as f64 - columns[i][r];
                    sum += d * d;
                }
                score += sum;
            }
        }
        memo.push((angle, score));
        score
    };
    // min() in Python returns the first of equal scores, so compare strictly.
    let mut pick = |case: &mut Case, candidates: &[f64]| -> f64 {
        let mut best = candidates[0];
        let mut best_score = score_at(case, candidates[0]);
        for &candidate in &candidates[1..] {
            let score = score_at(case, candidate);
            if score < best_score {
                best = candidate;
                best_score = score;
            }
        }
        best
    };
    let mut angle = pick(case, &seeds);
    if score_at(case, angle) > tolerance {
        let (mut lo, mut hi) = (angle - 0.2, angle + 0.2);
        let ratio = (5.0_f64.sqrt() - 1.0) * 0.5;
        let (mut a, mut b) = (hi - ratio * (hi - lo), lo + ratio * (hi - lo));
        let (mut fa, mut fb) = (score_at(case, a), score_at(case, b));
        for _ in 0..refine_steps {
            if fa < fb {
                hi = b;
                b = a;
                fb = fa;
                a = hi - ratio * (hi - lo);
                fa = score_at(case, a);
            } else {
                lo = a;
                a = b;
                fa = fb;
                b = lo + ratio * (hi - lo);
                fb = score_at(case, b);
            }
        }
        angle = pick(case, &[angle, a, b]);
    }
    let rounded = angle.sin().atan2(angle.cos()) as f32;
    let matrices = solve_at(case, rounded);
    (angle, matrices)
}
```

`solve_at(case, angle)` is the existing per-handle solve already reached through `sub_ik_solve`; factor it out of that FFI entry point so both callers share it rather than duplicating it.

- [ ] **Step 4: Run to verify it passes**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: PASS, including every pre-existing test.

- [ ] **Step 5: Commit**

```bash
git add native/ik_match/src/solver.rs native/ik_match/src/lib.rs
git commit -m "Port the IK pole search into the native solver"
```

---

## Task 2: Expose the search over FFI

**Files:**
- Modify: `native/ik_match/src/ffi.rs`
- Modify: `source/extras/ik_native.py`

**Interfaces:**
- Produces: `sub_ik_search(handle, reference, reference_len, seeds, tolerance, refine_steps, out_angle, out_matrices, out_len) -> c_int`, and `sub_ik_abi_version()` returning **3**.
- Python: `Solver.search(reference_columns, seeds, tolerance, refine_steps) -> (angle, [Matrix, ...]) | None`.

- [ ] **Step 1: Write the failing test**

Append to `mod tests` in `native/ik_match/src/ffi.rs`:

```rust
#[test]
fn abi_version_advertises_the_search() {
    assert_eq!(sub_ik_abi_version(), 3);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline abi_version
```

Expected: FAIL, `assertion left == right failed: 2 vs 3`.

- [ ] **Step 3: Add the entry point and bump the ABI**

In `native/ik_match/src/ffi.rs`, change `sub_ik_abi_version` to return `3`, and add:

```rust
/// `reference` is 3 * 4 * bones doubles, bone-major then column-major,
/// matching the order ik_channels builds reference_columns in.
/// Returns 1 on success, 0 on a rejected problem, 2 when the caller should
/// fall back to Blender.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_search(
    handle: *mut pose::Case,
    reference: *const f64,
    reference_len: usize,
    seeds: *const f64,
    tolerance: f64,
    refine_steps: usize,
    out_angle: *mut f64,
    out_matrices: *mut f32,
    out_len: usize,
) -> std::os::raw::c_int {
    if handle.is_null() || reference.is_null() || seeds.is_null() {
        return 0;
    }
    let case = &mut *handle;
    let bones = reference_len / 12;
    if bones == 0 || reference_len % 12 != 0 || out_len < bones * 16 {
        return 0;
    }
    let flat = std::slice::from_raw_parts(reference, reference_len);
    let columns: Vec<[[f64; 3]; 4]> = (0..bones)
        .map(|b| std::array::from_fn(|c| std::array::from_fn(|r| flat[b * 12 + c * 3 + r])))
        .collect();
    let seeds = std::slice::from_raw_parts(seeds, 3);
    let (angle, matrices) = solver::search(
        case,
        &columns,
        [seeds[0], seeds[1], seeds[2]],
        tolerance,
        refine_steps,
    );
    *out_angle = angle;
    let out = std::slice::from_raw_parts_mut(out_matrices, out_len);
    for (index, matrix) in matrices.iter().enumerate() {
        for r in 0..4 {
            for c in 0..4 {
                out[index * 16 + r * 4 + c] = matrix[r][c];
            }
        }
    }
    1
}
```

- [ ] **Step 4: Add the Python binding**

In `source/extras/ik_native.py`, change the ABI check from `!= 2` to `!= 3`, register the signature next to the others:

```python
            library.sub_ik_search.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
            library.sub_ik_search.restype = ctypes.c_int
```

and add to `Solver`:

```python
    def search(self, reference_columns, seeds, tolerance, refine_steps):
        """Run the whole pole search natively; None means fall back to Blender."""
        flat = [value
                for columns in reference_columns
                for column in columns
                for value in (column[0], column[1], column[2])]
        reference = (ctypes.c_double * len(flat))(*flat)
        seed_buffer = (ctypes.c_double * 3)(*seeds)
        angle = ctypes.c_double()
        status = _dll.sub_ik_search(
            self.handle, reference, len(flat), seed_buffer, tolerance, refine_steps,
            ctypes.byref(angle), self.buffer, len(self.buffer))
        if status != 1:
            return None
        matrices = [Matrix([self.buffer[offset + r * 4:offset + r * 4 + 4] for r in range(4)])
                    for offset in range(0, len(self.buffer), 16)]
        return angle.value, matrices
```

- [ ] **Step 5: Run to verify it passes**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
python native/ik_match/build.py
```

Expected: tests pass, DLL stages. An add-on running against an older DLL now refuses it on the ABI check rather than calling a missing symbol.

- [ ] **Step 6: Commit**

```bash
git add native/ik_match/src/ffi.rs source/extras/ik_native.py
git commit -m "Expose the native pole search over FFI and bump the ABI to 3"
```

---

## Task 3: Call the native search from the match loop

**Files:**
- Modify: `source/extras/ik_channels.py:1150-1232`
- Test: `tests/test_native_ik_search_blender.py`

**Interfaces:**
- Consumes: `Solver.search` from Task 2.
- Produces: no new Python interface; `_match_chain_steps` gains one branch.

- [ ] **Step 1: Write the failing test**

Create `tests/test_native_ik_search_blender.py`, reusing the preamble from `tests/test_native_ik_residual_blender.py`. It matches the fixture three ways — Blender backend, native per-candidate (`SUB_NATIVE_SEARCH=0`) and native whole-search — and asserts all three produce identical pole-angle keys:

```python
def pole_angles(obj):
    from ..anim.fcurve_compat import get_all_action_fcurves
    return sorted((fc.data_path, [tuple(k.co) for k in fc.keyframe_points])
                  for fc in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')
                  if fc.data_path.endswith('.pole_angle'))

results = {}
for label, native, search in (('blender', '0', '0'),
                              ('per_candidate', 'experimental', '0'),
                              ('native_search', 'experimental', '1')):
    os.environ['SUB_NATIVE_IK'] = native
    os.environ['SUB_NATIVE_SEARCH'] = search
    obj = reload()
    ik.match(bpy.context, obj, _batch=True)
    results[label] = pole_angles(obj)

print('SEARCH_ANGLES_MATCH', {k: results[k] == results['blender'] for k in results}, flush=True)
assert results['native_search'] == results['blender'], 'native search chose different angles'
print('NATIVE_SEARCH_OK', flush=True)
```

- [ ] **Step 2: Run to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_ik_search_blender.py
```

Expected: FAIL — `SUB_NATIVE_SEARCH` is not read yet, so `native_search` is merely a second `per_candidate` run and the assertion is vacuous. Confirm the test is meaningful by temporarily returning a constant angle from the Rust search and watching this test fail; revert that before continuing.

- [ ] **Step 3: Take the native branch**

In `source/extras/ik_channels.py`, after `reference_columns` is built and `native` is non-`None`, replace the candidate loop with a single call. Keep the existing loop for the non-native path and for `SUB_NATIVE_SEARCH=0`:

```python
    if native is not None and os.environ.get('SUB_NATIVE_SEARCH', '1') == '1':
        seeds = (delta, -delta, entry['angle'] or 0.0)
        found = native.search(reference_columns, seeds, _POLE_TOLERANCE, _POLE_REFINE_STEPS)
        if found is not None:
            angle = found[0]
        else:
            angle = yield from _python_search(...)
```

`delta` needs the zero-angle solve that currently happens inline; keep that exactly where it is, since it also feeds the near-straight fallback. Extract the existing candidate loop verbatim into `_python_search` so the two paths cannot drift, and so a `None` from `search` lands on the identical code that runs today.

- [ ] **Step 4: Run to verify it passes**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_ik_search_blender.py
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_ik_search_blender.py
```

Expected: `NATIVE_SEARCH_OK` on both.

- [ ] **Step 5: Re-run the acceptance suites**

```bash
python tests/run_blender_test.py --blender <4.5> tests/test_native_ik_residual_matrix_blender.py
python tests/run_blender_test.py --blender <5.2> tests/test_native_ik_residual_matrix_blender.py
python tests/run_blender_test.py --blender <4.5> tests/test_ik_match_fast_blender.py
python tests/run_blender_test.py --blender <5.2> tests/test_ik_match_fast_blender.py
```

Expected: `NATIVE_RESIDUAL_MATRIX_OK` with all ten configurations still at `max_pose_difference: 0.0`, and 13 exact scenarios per version. A configuration that regresses to a non-zero pose difference means the search port diverged; the `SEARCH_ANGLES_MATCH` line in Task 3's test names which path.

- [ ] **Step 6: Commit**

```bash
git add source/extras/ik_channels.py tests/test_native_ik_search_blender.py
git commit -m "Run the pole search natively in one call per chain and frame"
```

---

## Task 4: Measure

**Files:**
- Create: `docs/benchmarks/native-search-2026-09-12.md`

- [ ] **Step 1: Benchmark both versions**

```bash
SUB_NATIVE_IK=experimental SUB_NATIVE_SEARCH=0 SUB_MATCH_LABEL=search_off_45 SUB_MATCH_PHASES=BOTH,IMPORT python tests/run_blender_test.py --blender <4.5> tests/benchmark_position_ik_blender.py
SUB_NATIVE_IK=experimental SUB_NATIVE_SEARCH=1 SUB_MATCH_LABEL=search_on_45 SUB_MATCH_PHASES=BOTH,IMPORT python tests/run_blender_test.py --blender <4.5> tests/benchmark_position_ik_blender.py
```

Repeat for 5.2 with the matching `SUB_BASELINE_BLEND`.

- [ ] **Step 2: Write the report**

Record medians per version and phase, the ratio against both the per-candidate native path and the 2.63 s / 7.26 s Blender-backend baseline from the factorial, and state plainly how far short of 10x the result lands. The profile predicts this removes most of the 14% Python search share plus the per-candidate marshalling; if the measured gain is much smaller, the remaining cost is in placement or key writing, which is Phase 4's subject and should be said rather than glossed.

- [ ] **Step 3: Commit**

```bash
git add docs/benchmarks/native-search-2026-09-12.md
git commit -m "Record the native pole search benchmark"
```

---

## Self-Review

**Spec coverage.** This plan covers the spec's Phase 2 only. Phase 3 (deterministic per-frame candidates and `rayon` across frames) and Phase 4 (sampling and key-writing) are deliberately out of scope and are planned after Task 4 reports, because Phase 3's value depends on how much of the remaining cost Phase 2 actually removes.

**Type consistency.** `solver::search` is defined in Task 1 with the signature Task 2's `sub_ik_search` calls; `Solver.search` in Task 2 returns the `(angle, matrices)` tuple Task 3 consumes; `SUB_NATIVE_SEARCH` takes the same two values in Tasks 3 and 4.

**Known risk, stated rather than hidden.** Task 1's four numeric details — float32 rounding of the pole angle, memo keyed on the unrounded angle, strict `<` tie-breaking, and summation order — are the whole correctness surface. Task 3 Step 2 deliberately includes a mutation check, because a test that passes whether or not the native path is taken would hide exactly these.
