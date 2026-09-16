# Native Eigen IK Solver — Phases 0 and 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the add-on's own viewport handlers from the IK matching loop, then establish whether a real `Eigen::JacobiSVD` compiled into the native module produces results bit-identical to Blender's IK solver.

**Architecture:** The Rust accelerator currently approximates Eigen's JacobiSVD (`native/ik_match/src/math.rs:79`), which is why it cannot be enabled by default. This plan puts both SVD implementations behind one narrow seam so they are interchangeable at runtime, compiles Blender's vendored Eigen through a C++ shim, and builds a differential harness that compares them over every real SVD call captured from a full match. Phase 1 ends at a go/no-go gate, not at a shipped feature.

**Tech Stack:** Rust 1.89.0 (cdylib, `cc` crate for C++), Blender 4.5.7 LTS and 5.2.1 LTS Python API, MSVC, Eigen (vendored by Blender), `ctypes` FFI.

**Spec:** `docs/superpowers/specs/2026-09-12-ik-native-eigen-design.md`

## Global Constraints

- Windows x64 only; Blender 4.5 and 5.2 only. Other platforms and versions keep the existing Blender backend.
- The default SVD backend stays `Approximate` for the whole of this plan. Changing the default is a Phase 2 decision, made only after the Phase 1 gate reports.
- `ApproximateSvd` is retained and selectable. It is never deleted.
- The Eigen backend's acceptance is **zero mismatches against Blender**, component for component. Not a tolerance, not a smaller delta. Zero.
- Phases 0 and 1 do not change the search, so their acceptance test is **output fingerprint equality** with current code (key coordinates, interpolation, and every pose-bone matrix at every frame).
- All existing guards in `ik_native.supported()` and `ik_match_fast` remain untouched and in force.
- C++ compiles with `/fp:precise`, `/O2`, FMA contraction disabled, no fast-math.
- Rust builds stay `--locked --offline`; vendored sources carry their GPL-2.0-or-later / MPL-2.0 notices under `native/ik_match/LICENSES/`.
- Benchmarks follow the established `docs/benchmarks/` format: median of three paired runs, alternating order, on both Blender versions.

---

## File Structure

**Phase 0**
- Modify `source/extras/ik_match_fast.py` — add `suspend_viewport_handlers()` beside the existing `known_handlers()`.
- Modify `source/extras/ik_channels.py:1265-1290` — wrap the match body in it.
- Create `tests/test_ik_handler_suspension_blender.py` — proves handlers stop firing, are restored, and output is unchanged.

**Phase 1**
- Create `docs/benchmarks/eigen-source-parity-2026-09-12.md` — the 4.5 vs 5.2 Eigen/iksolver parity finding.
- Modify `native/ik_match/src/math.rs` — rename `svd` to `approximate_svd`, add `Backend` enum and the `svd(backend, columns)` dispatcher.
- Modify `native/ik_match/src/solver.rs` — `Job` carries `backend`; `sdls` takes it.
- Modify `native/ik_match/src/capture.rs` — `Input` carries an optional `backend`.
- Create `native/ik_match/eigen_shim/sub_ik_eigen_svd.cpp` — the C++ shim.
- Create `native/ik_match/build.rs` — compiles the shim with the required flags.
- Create `native/ik_match/vendor/` — Blender's `intern/iksolver` and `extern/eigen3`, with notices.
- Create `native/ik_match/src/eigen.rs` — Rust side of the shim FFI.
- Create `native/ik_match/src/bin/svd_diff.rs` — the differential harness.
- Create `tests/native_svd_capture_blender.py` — captures real `(J, beta)` pairs from a full match.
- Modify `source/extras/ik_native.py:120-125` — pass the backend through from `SUB_NATIVE_SVD`.

---

## Task 1: Suspend the add-on's viewport handlers during matching

The profile shows three add-on handlers firing 2,827 times each inside a single 157-frame match, costing about 0.12 s. They are viewport and UI synchronisation only; none feeds the solve.

**Files:**
- Modify: `source/extras/ik_match_fast.py`
- Modify: `source/extras/ik_channels.py:1265-1290`
- Test: `tests/test_ik_handler_suspension_blender.py`

**Interfaces:**
- Consumes: `ik_match_fast.known_handlers()` (existing, returns `True` only when every registered handler belongs to this add-on).
- Produces: `ik_match_fast.suspend_viewport_handlers()` — a context manager taking no arguments.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ik_handler_suspension_blender.py`. It reuses the fixture-loading preamble from `tests/test_ik_match_fast_blender.py` (copy its first block verbatim — the `exec(compile(...))` that sets `MODULE` and `ROOT`).

```python
import importlib
import bpy

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
fast = importlib.import_module(MODULE + '.source.extras.ik_match_fast')
retarget = importlib.import_module(MODULE + '.source.retargeting')

calls = []
original = retarget.auto_detect_smash_armature


def counting(*args, **kwargs):
    calls.append(1)
    return original(*args, **kwargs)


index = bpy.app.handlers.depsgraph_update_post.index(original)
bpy.app.handlers.depsgraph_update_post[index] = counting
retarget.auto_detect_smash_armature = counting
try:
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    calls.clear()
    assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT', cleanup_mode='BOTH',
                                         entire_animation=True) == {'FINISHED'}
    during = len(calls)
    # The handler must be back in place, and functional, after matching.
    restored = counting in bpy.app.handlers.depsgraph_update_post
finally:
    index = bpy.app.handlers.depsgraph_update_post.index(counting)
    bpy.app.handlers.depsgraph_update_post[index] = original
    retarget.auto_detect_smash_armature = original

print('HANDLER_CALLS_DURING_MATCH', during, flush=True)
assert during == 0, during
assert restored, 'handler was not restored'
print('HANDLER_SUSPENSION_OK', flush=True)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_handler_suspension_blender.py
```

Expected: FAIL with `AssertionError` reporting a non-zero call count in the low thousands.

Note: set `PYTHONIOENCODING=utf-8` when redirecting output to a file; `run_blender_test.py` prints non-cp1252 characters and will otherwise raise `UnicodeEncodeError` on the print, masking the real result.

- [ ] **Step 3: Add the context manager**

In `source/extras/ik_match_fast.py`, after `known_handlers()`:

```python
# Viewport and UI synchronisation only. None of these feeds the solve, and
# each fires once per depsgraph update, which matching performs thousands of
# times. Suspending them is skipped entirely when a foreign handler is
# present, matching the guard the rest of this module already applies.
SUSPENDED_HANDLERS = (
    ('source.anim.motion_list_ui', 'motion_list_auto_sync_handler'),
    ('source.extras.stage_tools.light_nuanmb', '_stage_light_depsgraph_update'),
    ('source.retargeting', 'auto_detect_smash_armature'),
)


@contextmanager
def suspend_viewport_handlers():
    """Remove this add-on's own viewport handlers for the duration."""
    if not known_handlers():
        yield
        return
    package = __package__.rsplit('.source', 1)[0] + '.'
    wanted = {package + module + '.' + name for module, name in SUSPENDED_HANDLERS}
    removed = []
    try:
        for listname in ('frame_change_pre', 'frame_change_post',
                         'depsgraph_update_pre', 'depsgraph_update_post'):
            handlers = getattr(bpy.app.handlers, listname)
            for index in range(len(handlers) - 1, -1, -1):
                function = handlers[index]
                identity = getattr(function, '__module__', '') + '.' + getattr(function, '__name__', '')
                if identity in wanted:
                    removed.append((listname, index, function))
                    handlers.remove(function)
        yield
    finally:
        # Reinsert at the original index so handler order is preserved.
        for listname, index, function in reversed(removed):
            getattr(bpy.app.handlers, listname).insert(index, function)
```

- [ ] **Step 4: Wrap the match body**

In `source/extras/ik_channels.py`, the `with` chain at line 1270 currently reads:

```python
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context), anim_layers_compat.bind_driving_action_for_bake(obj, context):
```

Change it to:

```python
        from . import ik_match_fast
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context), anim_layers_compat.bind_driving_action_for_bake(obj, context), ik_match_fast.suspend_viewport_handlers():
```

The existing `from . import ik_match_fast` inside the `if fast:` branch further down becomes redundant but is harmless; leave it.

- [ ] **Step 5: Run the test to verify it passes**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_handler_suspension_blender.py
```

Expected: `HANDLER_CALLS_DURING_MATCH 0` then `HANDLER_SUSPENSION_OK`.

- [ ] **Step 6: Verify output is unchanged**

The whole point is that suspension is invisible in the output.

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_ik_match_fast_blender.py
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_ik_match_fast_blender.py
```

Expected: 12 scenarios reporting `'exact': True` on each version, then `FAST_MATCH_EXACT_AND_CLEANUP_OK`. Any `'exact': False` means a suspended handler was load-bearing — remove that handler from `SUSPENDED_HANDLERS` and re-run.

- [ ] **Step 7: Measure the gain**

```bash
SUB_MATCH_LABEL=handlers_45 SUB_MATCH_PHASES=BOTH,IMPORT SUB_MATCH_COMPARE_SOURCE=.tests/benchmarks/match_pre_strategies.py python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/benchmark_position_ik_blender.py
```

Expected: a few percent, consistent with the 0.12 s in the profile. Record the medians; a regression means the insert-by-index restore is wrong.

- [ ] **Step 8: Commit**

```bash
git add source/extras/ik_match_fast.py source/extras/ik_channels.py tests/test_ik_handler_suspension_blender.py
git commit -m "Suspend add-on viewport handlers during IK matching"
```

---

## Task 2: Establish Eigen and iksolver parity between Blender 4.5 and 5.2

This decides whether the build produces one binary or two, so it comes before any build work.

**Files:**
- Create: `docs/benchmarks/eigen-source-parity-2026-09-12.md`

**Interfaces:**
- Produces: a recorded decision, `SINGLE_BINARY` or `PER_VERSION_BINARY`, that Tasks 4 and 5 read.

- [ ] **Step 1: Obtain both source trees**

Download the source tarballs for Blender 4.5.7 LTS and 5.2.1 LTS from `https://download.blender.org/source/`. Extract to a scratch directory outside the repo.

- [ ] **Step 2: Compare the Eigen version**

```bash
grep -h "EIGEN_WORLD_VERSION\|EIGEN_MAJOR_VERSION\|EIGEN_MINOR_VERSION" <tree>/extern/eigen3/Eigen/src/Core/util/Macros.h
```

Run for both trees and record both triples.

- [ ] **Step 3: Compare the files that decide the solve**

```bash
sha256sum <tree>/intern/iksolver/intern/IK_QJacobian.cpp \
          <tree>/intern/iksolver/intern/IK_QJacobianSolver.cpp \
          <tree>/intern/iksolver/intern/IK_QSegment.cpp \
          <tree>/intern/iksolver/intern/IK_QTask.cpp \
          <tree>/extern/eigen3/Eigen/src/SVD/JacobiSVD.h
```

Run for both trees. Record every hash.

- [ ] **Step 4: Write the finding**

Create `docs/benchmarks/eigen-source-parity-2026-09-12.md` with both version triples, both hash sets, and a one-line verdict: `SINGLE_BINARY` if every hash matches, `PER_VERSION_BINARY` otherwise, naming which files differ.

- [ ] **Step 5: Commit**

```bash
git add docs/benchmarks/eigen-source-parity-2026-09-12.md
git commit -m "Record Eigen and iksolver source parity between Blender 4.5 and 5.2"
```

---

## Task 3: Introduce the SVD backend seam, behaviour unchanged

Pure refactor. The approximate implementation keeps producing identical numbers; only its name and call path change.

**Files:**
- Modify: `native/ik_match/src/math.rs:79-142`
- Modify: `native/ik_match/src/solver.rs:88-90`
- Modify: `native/ik_match/src/capture.rs:12-23`

**Interfaces:**
- Produces: `math::Backend` (enum, `Approximate` | `Eigen`, `Deserialize`, defaults to `Approximate`), `math::svd(backend: Backend, columns: &[V]) -> (M, V, Vec<V>)`, `math::approximate_svd(columns: &[V]) -> (M, V, Vec<V>)`.
- Consumed by: Tasks 5, 6, 7.

- [ ] **Step 1: Write the failing test**

Append to the `mod tests` block in `native/ik_match/src/math.rs`:

```rust
#[test]
fn backend_dispatch_matches_approximate() {
    let a = vec![[0.3, -1.2, 0.7], [2.0, 0.1, -0.4], [-0.6, 0.9, 1.5], [0.05, 0.02, -0.01]];
    let direct = approximate_svd(&a);
    let dispatched = svd(Backend::Approximate, &a);
    assert_eq!(direct.0, dispatched.0);
    assert_eq!(direct.1, dispatched.1);
    assert_eq!(direct.2, dispatched.2);
}

#[test]
fn backend_defaults_to_approximate() {
    assert_eq!(Backend::default(), Backend::Approximate);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: FAIL, `cannot find function approximate_svd` / `cannot find type Backend`.

- [ ] **Step 3: Add the enum and dispatcher**

In `native/ik_match/src/math.rs`, rename the existing `pub fn svd` to `pub fn approximate_svd` (body unchanged), then add above it:

```rust
/// Which SVD implementation decides each damped-least-squares step.
///
/// `Approximate` is the one-sided Jacobi implementation in this file. It is
/// NOT bit-compatible with Blender and stays the default.
/// `Eigen` calls Blender's own vendored Eigen::JacobiSVD through the C++ shim.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Backend {
    #[default]
    Approximate,
    Eigen,
}

pub fn svd(backend: Backend, columns: &[V]) -> (M, V, Vec<V>) {
    match backend {
        Backend::Approximate => approximate_svd(columns),
        Backend::Eigen => crate::eigen::eigen_svd(columns),
    }
}
```

Because `crate::eigen` does not exist yet, add a placeholder module so this task compiles standalone. Create `native/ik_match/src/eigen.rs`:

```rust
// SPDX-License-Identifier: GPL-2.0-or-later
use crate::math::{M, V};

/// Replaced by the real shim call in Task 5.
pub fn eigen_svd(_columns: &[V]) -> (M, V, Vec<V>) {
    unimplemented!("Eigen backend arrives in Task 5")
}
```

Add `mod eigen;` to `native/ik_match/src/lib.rs`.

- [ ] **Step 4: Thread the backend through the solver**

In `native/ik_match/src/solver.rs`, add the field to `Job`:

```rust
#[derive(Clone, Deserialize)]
pub struct Job {
    pub id: String,
    pub segments: Vec<Segment>,
    pub goal: V,
    pub pole: V,
    pub angle: f64,
    pub iterations: usize,
    #[serde(default)]
    pub backend: crate::math::Backend,
}
```

Change `sdls` at line 88 to take the backend:

```rust
fn sdls(backend: Backend, j: &[V], beta: V) -> Vec<f64> {
    let (u, w, v) = svd(backend, j);
```

Update its call site in the same file to pass the job's backend through.

- [ ] **Step 5: Thread it through capture**

In `native/ik_match/src/capture.rs`, add to `Input`:

```rust
    #[serde(default)]
    pub backend: crate::math::Backend,
```

and pass `input.backend` into the `Job` it constructs. `#[serde(default)]` keeps existing captured JSON parsing unchanged.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: PASS, including the pre-existing `reconstruct_svd` test, which proves the rename changed nothing.

- [ ] **Step 7: Verify end-to-end behaviour is untouched**

```bash
python native/ik_match/build.py
SUB_NATIVE_IK=1 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_ik_backend_blender.py
```

Expected: `NATIVE_BACKEND_GUARDS_AND_CLEANUP_OK`.

- [ ] **Step 8: Commit**

```bash
git add native/ik_match/src/math.rs native/ik_match/src/solver.rs native/ik_match/src/capture.rs native/ik_match/src/eigen.rs native/ik_match/src/lib.rs
git commit -m "Add selectable SVD backend seam to native IK solver"
```

---

## Task 4: Vendor Blender's iksolver and Eigen, and compile them

**Files:**
- Create: `native/ik_match/vendor/` (Blender sources)
- Create: `native/ik_match/build.rs`
- Modify: `native/ik_match/Cargo.toml`
- Modify: `native/ik_match/build.py`

**Interfaces:**
- Consumes: Task 2's `SINGLE_BINARY` / `PER_VERSION_BINARY` verdict.
- Produces: a compiled static object containing Eigen's headers, linkable from Rust.

- [ ] **Step 1: Vendor the sources**

Copy from the 4.5.7 tree (or, if Task 2 said `PER_VERSION_BINARY`, from each tree into `vendor/4.5/` and `vendor/5.2/`):

- `intern/iksolver/intern/*.cpp` and `*.h` → `native/ik_match/vendor/iksolver/`
- `extern/eigen3/Eigen/` → `native/ik_match/vendor/eigen3/Eigen/`

Copy Blender's `intern/iksolver` license header text to `native/ik_match/LICENSES/` alongside the existing `GPL-2.0.txt` and `MPL-2.0.txt`, which already cover these.

- [ ] **Step 2: Add the `cc` build dependency**

In `native/ik_match/Cargo.toml`:

```toml
[build-dependencies]
cc = "1.0"
```

Run `cargo build --manifest-path native/ik_match/Cargo.toml --release` once **online** to update `Cargo.lock`, then restore `--locked --offline` for all later builds.

- [ ] **Step 3: Write `build.rs`**

Create `native/ik_match/build.rs`:

```rust
// SPDX-License-Identifier: GPL-2.0-or-later
fn main() {
    let mut build = cc::Build::new();
    build
        .cpp(true)
        .file("eigen_shim/sub_ik_eigen_svd.cpp")
        .include("vendor/eigen3")
        .include("vendor/iksolver")
        .opt_level(2);
    if build.get_compiler().is_like_msvc() {
        // Identical source is not identical arithmetic unless the flags agree.
        // /fp:precise forbids reassociation; /fp:contract=off forbids the
        // compiler fusing a*b+c into an FMA with a different rounding profile.
        build.flag("/fp:precise").flag("/fp:contract=off").flag("/EHsc");
    } else {
        build.flag("-ffp-contract=off").flag("-fno-fast-math");
    }
    build.compile("sub_ik_eigen_svd");
    println!("cargo:rerun-if-changed=eigen_shim/sub_ik_eigen_svd.cpp");
}
```

- [ ] **Step 4: Verify it compiles**

```bash
cargo build --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: the shim compiles. It has no callers yet, so only compilation is proven here.

- [ ] **Step 5: Stage vendored notices**

In `native/ik_match/build.py`, after the existing dependency-licence loop, add:

```python
for name in ('iksolver', 'eigen3'):
    source = crate/'vendor'/name
    for file in source.rglob('*'):
        if file.is_file() and file.name.upper().startswith(('LICENSE', 'COPYING', 'COPYRIGHT')):
            destination = crate/'LICENSES/vendor'/name/file.relative_to(source).parent
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination/file.name)
```

- [ ] **Step 6: Commit**

```bash
git add native/ik_match/vendor native/ik_match/build.rs native/ik_match/Cargo.toml native/ik_match/Cargo.lock native/ik_match/build.py native/ik_match/LICENSES
git commit -m "Vendor Blender iksolver and Eigen sources with a C++ build step"
```

---

## Task 5: Implement the Eigen SVD shim in Blender's Jacobian orientation

This is the task the whole plan exists for, and the orientation is where it can silently go wrong.

Blender's `IK_QJacobian` stores the Jacobian as `(3 * ntasks) x ndof` — for one position task, `3 x ndof` — and runs `JacobiSVD` on **that**. The Rust port works on the transpose (`columns: &[V]` is `ndof x 3`), which swaps U and V. Handing Eigen the transposed matrix yields a mathematically equivalent decomposition with different rounding, which is exactly the class of error this plan is trying to eliminate.

**Files:**
- Create: `native/ik_match/eigen_shim/sub_ik_eigen_svd.cpp`
- Modify: `native/ik_match/src/eigen.rs`

**Interfaces:**
- Consumes: `math::Backend`, `math::{M, V}` from Task 3.
- Produces: `eigen::eigen_svd(columns: &[V]) -> (M, V, Vec<V>)`, same contract as `approximate_svd`: U is 3x3, W is 3 singular values descending, V is `columns.len()` rows of 3.

- [ ] **Step 1: Write the failing test**

Append to `mod tests` in `native/ik_match/src/math.rs`:

```rust
#[test]
fn eigen_reconstructs_the_input() {
    let a = vec![[0.3, -1.2, 0.7], [2.0, 0.1, -0.4], [-0.6, 0.9, 1.5], [0.05, 0.02, -0.01]];
    let (u, w, v) = svd(Backend::Eigen, &a);
    // A^T == U * diag(w) * V^T, so each input row is recoverable.
    for (row, vrow) in a.iter().zip(v.iter()) {
        for i in 0..3 {
            let rebuilt: f64 = (0..3).map(|k| u[i][k] * w[k] * vrow[k]).sum();
            assert!((rebuilt - row[i]).abs() < 1e-12, "{} vs {}", rebuilt, row[i]);
        }
    }
}

#[test]
fn eigen_orders_singular_values_descending() {
    let a = vec![[0.3, -1.2, 0.7], [2.0, 0.1, -0.4], [-0.6, 0.9, 1.5]];
    let (_, w, _) = svd(Backend::Eigen, &a);
    assert!(w[0] >= w[1] && w[1] >= w[2], "{:?}", w);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: FAIL, panicking on `unimplemented!("Eigen backend arrives in Task 5")`.

- [ ] **Step 3: Write the C++ shim**

Create `native/ik_match/eigen_shim/sub_ik_eigen_svd.cpp`:

```cpp
// SPDX-License-Identifier: GPL-2.0-or-later
// Calls the same Eigen::JacobiSVD, in the same orientation and with the same
// options, that Blender's IK_QJacobian::Invert uses.
#include <Eigen/Core>
#include <Eigen/SVD>
#include <cstddef>

extern "C" void sub_ik_eigen_svd(const double *jacobian_row_major,
                                 std::size_t ndof,
                                 double *u_out,   // 3 * 3, row major
                                 double *w_out,   // 3
                                 double *v_out)   // ndof * 3, row major
{
  // Blender's m_jacobian is (3 * ntasks) x ndof with one position task, so
  // 3 x ndof. The caller hands us exactly that, already in Blender's layout.
  Eigen::MatrixXd jacobian(3, ndof);
  for (std::size_t r = 0; r < 3; ++r) {
    for (std::size_t c = 0; c < ndof; ++c) {
      jacobian(r, c) = jacobian_row_major[r * ndof + c];
    }
  }
  Eigen::JacobiSVD<Eigen::MatrixXd> svd(
      jacobian, Eigen::ComputeThinU | Eigen::ComputeThinV);
  const Eigen::MatrixXd &u = svd.matrixU();       // 3 x 3
  const Eigen::VectorXd &w = svd.singularValues();  // 3, descending
  const Eigen::MatrixXd &v = svd.matrixV();       // ndof x 3
  for (std::size_t r = 0; r < 3; ++r) {
    for (std::size_t c = 0; c < 3; ++c) {
      u_out[r * 3 + c] = u(r, c);
    }
    w_out[r] = w(r);
  }
  for (std::size_t r = 0; r < ndof; ++r) {
    for (std::size_t c = 0; c < 3; ++c) {
      v_out[r * 3 + c] = v(r, c);
    }
  }
}
```

- [ ] **Step 4: Write the Rust side**

Replace `native/ik_match/src/eigen.rs` entirely:

```rust
// SPDX-License-Identifier: GPL-2.0-or-later
use crate::math::{M, V};

extern "C" {
    fn sub_ik_eigen_svd(jacobian: *const f64, ndof: usize, u: *mut f64, w: *mut f64, v: *mut f64);
}

/// `columns` is ndof rows of 3, i.e. the TRANSPOSE of Blender's Jacobian.
/// Blender runs JacobiSVD on the 3 x ndof orientation, so transpose back
/// before handing it over. Feeding Eigen this crate's orientation would swap
/// U and V and change the rounding.
pub fn eigen_svd(columns: &[V]) -> (M, V, Vec<V>) {
    let ndof = columns.len();
    let mut jacobian = vec![0.0f64; 3 * ndof];
    for (c, row) in columns.iter().enumerate() {
        for r in 0..3 {
            jacobian[r * ndof + c] = row[r];
        }
    }
    let mut u = [0.0f64; 9];
    let mut w = [0.0f64; 3];
    let mut v = vec![0.0f64; ndof * 3];
    unsafe {
        sub_ik_eigen_svd(jacobian.as_ptr(), ndof, u.as_mut_ptr(), w.as_mut_ptr(), v.as_mut_ptr());
    }
    let u: M = std::array::from_fn(|r| std::array::from_fn(|c| u[r * 3 + c]));
    let v: Vec<V> = (0..ndof).map(|r| std::array::from_fn(|c| v[r * 3 + c])).collect();
    (u, w, v)
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cargo test --manifest-path native/ik_match/Cargo.toml --release --locked --offline
```

Expected: PASS on both new tests plus every pre-existing test.

- [ ] **Step 6: Commit**

```bash
git add native/ik_match/eigen_shim native/ik_match/src/eigen.rs native/ik_match/src/math.rs
git commit -m "Add Eigen JacobiSVD backend in Blender's Jacobian orientation"
```

---

## Task 6: Select the backend from Python

**Files:**
- Modify: `source/extras/ik_native.py:38-47`
- Test: `tests/test_native_svd_backend_blender.py`

**Interfaces:**
- Consumes: the `backend` field added to `Input` in Task 3.
- Produces: `SUB_NATIVE_SVD` environment variable, values `approximate` (default) or `eigen`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_native_svd_backend_blender.py`, reusing the preamble from `tests/test_native_ik_backend_blender.py`:

```python
import os
import importlib

native = importlib.import_module(MODULE + '.source.extras.ik_native')

os.environ['SUB_NATIVE_IK'] = '1'
for backend in ('approximate', 'eigen'):
    os.environ['SUB_NATIVE_SVD'] = backend
    factory = native.get_factory()
    assert factory is not None, backend
    print('SVD_BACKEND_FACTORY', backend, flush=True)
    factory.close()
print('SVD_BACKEND_SELECTION_OK', flush=True)
```

- [ ] **Step 2: Run to verify it fails**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_svd_backend_blender.py
```

Expected: FAIL. Without the change the DLL silently ignores `SUB_NATIVE_SVD`, so add the assertion below first and watch it fail on the value round-trip.

- [ ] **Step 3: Pass the backend in the capture struct**

In `source/extras/ik_native.py`, inside `Solver.__init__`, extend the `case` dict:

```python
        case = dict(parent=rows(bones[0].parent.matrix) if bones[0].parent else rows(Matrix.Identity(4)),
                    poses=[rows(b.matrix) for b in bones], rests=[rows(b.bone.matrix) for b in bones],
                    heads=[list(b.head) for b in bones], tails=[list(b.tail) for b in bones],
                    lengths=[b.bone.length for b in bones], object=rows(obj.matrix_world),
                    target=rows(obj.pose.bones[con.subtarget].matrix),
                    pole=rows(obj.pose.bones[con.pole_subtarget].matrix), iterations=con.iterations,
                    # Unrecognised values fall back to the approximate backend
                    # in Rust via #[serde(default)], so a typo cannot silently
                    # enable an unverified solver.
                    backend=os.environ.get('SUB_NATIVE_SVD', 'approximate'))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_svd_backend_blender.py
```

Expected: `SVD_BACKEND_FACTORY approximate`, `SVD_BACKEND_FACTORY eigen`, `SVD_BACKEND_SELECTION_OK`.

- [ ] **Step 5: Commit**

```bash
git add source/extras/ik_native.py tests/test_native_svd_backend_blender.py
git commit -m "Select the native SVD backend from SUB_NATIVE_SVD"
```

---

## Task 7: Differential harness over every real SVD call

**Files:**
- Create: `tests/native_svd_capture_blender.py`
- Create: `native/ik_match/src/bin/svd_diff.rs`

**Interfaces:**
- Consumes: `math::{Backend, svd}` from Tasks 3 and 5.
- Produces: `.tests/benchmarks/svd_capture_<version>.jsonl` (one `{"j": [[f64;3], ...], "beta": [f64;3]}` per line) and a printed delta report.

- [ ] **Step 1: Capture the real inputs**

Create `tests/native_svd_capture_blender.py`, reusing the fixture preamble from `tests/benchmark_position_ik_blender.py`. Set `SUB_IK_SVD_CAPTURE` to a path; the Rust side appends each `(J, beta)` it sees.

Add the capture hook in `native/ik_match/src/solver.rs`, at the top of `sdls`:

```rust
    if let Ok(path) = std::env::var("SUB_IK_SVD_CAPTURE") {
        use std::io::Write;
        if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(file, "{}", serde_json::json!({"j": j, "beta": beta}));
        }
    }
```

Then run a full match and import with capture enabled:

```bash
SUB_NATIVE_IK=experimental SUB_IK_SVD_CAPTURE=.tests/benchmarks/svd_capture_4.5.jsonl SUB_MATCH_PHASES=BOTH,IMPORT SUB_MATCH_RUNS=1 python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/benchmark_position_ik_blender.py
```

Expected: a file of roughly 150,000-250,000 lines. Confirm with `wc -l`.

- [ ] **Step 2: Write the differential binary**

Create `native/ik_match/src/bin/svd_diff.rs`:

```rust
// SPDX-License-Identifier: GPL-2.0-or-later
// Runs both SVD backends over captured real inputs and reports the spread.
use sub_ik_match_native::math::{svd, Backend, V};

#[derive(serde::Deserialize)]
struct Case {
    j: Vec<V>,
    beta: V,
}

fn main() {
    let path = std::env::args().nth(1).expect("usage: svd_diff <capture.jsonl>");
    let text = std::fs::read_to_string(&path).expect("capture unreadable");
    let mut count = 0usize;
    let mut max_u = 0f64;
    let mut max_w = 0f64;
    let mut max_v = 0f64;
    let mut exact = 0usize;
    for line in text.lines().filter(|l| !l.trim().is_empty()) {
        let case: Case = serde_json::from_str(line).expect("malformed capture line");
        let (ua, wa, va) = svd(Backend::Approximate, &case.j);
        let (ue, we, ve) = svd(Backend::Eigen, &case.j);
        let mut worst = 0f64;
        for r in 0..3 {
            for c in 0..3 {
                max_u = max_u.max((ua[r][c] - ue[r][c]).abs());
                worst = worst.max((ua[r][c] - ue[r][c]).abs());
            }
            max_w = max_w.max((wa[r] - we[r]).abs());
            worst = worst.max((wa[r] - we[r]).abs());
        }
        for (ra, re) in va.iter().zip(ve.iter()) {
            for c in 0..3 {
                max_v = max_v.max((ra[c] - re[c]).abs());
                worst = worst.max((ra[c] - re[c]).abs());
            }
        }
        if worst == 0.0 {
            exact += 1;
        }
        count += 1;
        let _ = case.beta;
    }
    println!("SVD_DIFF cases={count} bit_identical={exact} max_u={max_u:e} max_w={max_w:e} max_v={max_v:e}");
}
```

`svd_diff` needs the crate as a library, which `Cargo.toml` already provides via `crate-type = ["rlib", "cdylib"]`.

- [ ] **Step 3: Run it**

```bash
cargo run --release --locked --offline --manifest-path native/ik_match/Cargo.toml --bin svd_diff -- .tests/benchmarks/svd_capture_4.5.jsonl
```

Expected: a single `SVD_DIFF` line. A `bit_identical` count well below `cases` is the expected and informative result — it quantifies how far the approximation drifts on real inputs, which is the number this plan exists to replace.

- [ ] **Step 4: Commit**

```bash
git add tests/native_svd_capture_blender.py native/ik_match/src/bin/svd_diff.rs native/ik_match/src/solver.rs
git commit -m "Add differential harness comparing SVD backends on captured inputs"
```

---

## Task 8: Run the accuracy layers and report the gate

No new code. This task produces the decision.

**Files:**
- Create: `docs/benchmarks/eigen-svd-gate-2026-09-12.md`

- [ ] **Step 1: Layer 3 — the singular suite, both backends, both versions**

```bash
SUB_NATIVE_IK=1 SUB_NATIVE_SVD=eigen python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_ik_singular_blender.py
SUB_NATIVE_IK=1 SUB_NATIVE_SVD=eigen python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_ik_singular_blender.py
```

Expected under the gate: every one of the 245 cases per version accepted with zero mismatches. The previous run's `32 of 40 native candidates differ` is the number being replaced.

- [ ] **Step 2: Layer 3 — the randomized stress suite**

```bash
SUB_NATIVE_IK=1 SUB_NATIVE_SVD=eigen python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_native_ik_synthetic_blender.py
SUB_NATIVE_IK=1 SUB_NATIVE_SVD=eigen python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_native_ik_synthetic_blender.py
```

Expected: 10,000 poses per version, zero accepted mismatches, and — unlike the previous run — acceptance no longer restricted by the twelve-iteration convergence rule.

- [ ] **Step 3: Layer 3 — the fixture factorial**

```bash
SUB_NATIVE_SVD=eigen SUB_MATCH_LABEL=eigen_factorial_45 SUB_MATCH_PHASES=BOTH,IMPORT python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/benchmark_ik_fast_factorial_blender.py
```

Repeat for 5.2 with `SUB_BASELINE_BLEND` pointing at `.tests/benchmarks/ik_apply/out/5.2/baseline.blend` and `SUB_MATCH_LABEL=eigen_factorial_52`.

Expected: `FACTORIAL_EXACT_FIXTURE 48` on each version.

- [ ] **Step 4: Write the gate report**

Create `docs/benchmarks/eigen-svd-gate-2026-09-12.md` recording, for each Blender version: the `SVD_DIFF` line from Task 7, singular-suite mismatch counts under both backends, stress-suite accepted/mismatch counts under both backends, factorial exactness, and the compiler and Eigen versions used.

State the verdict explicitly: **PASS** (zero mismatches everywhere — Phase 2 proceeds and the default backend can change) or **FAIL** (naming the first suite that mismatched and the largest observed difference).

- [ ] **Step 5: Commit and stop**

```bash
git add docs/benchmarks/eigen-svd-gate-2026-09-12.md
git commit -m "Record the Eigen SVD exactness gate result"
```

**Stop here and report to the user.** Phases 2-4 are planned only after this verdict. A FAIL means the design's premise needs reassessment, not that the next phase should start anyway.

---

## Self-Review

**Spec coverage.** Phase 0 → Task 1. Version parity → Task 2. Backend seam → Task 3. Build → Task 4. Jacobian orientation and the Eigen backend → Task 5. Python selection → Task 6. Accuracy layer 1 (differential) → Task 7. Layers 2-4 and the gate → Task 8. The spec's Phases 2-4 are deliberately out of scope, as its Phases section states.

**Type consistency.** `Backend` is defined in Task 3 and used by the same path in Tasks 5, 6 and 7. `eigen_svd(columns: &[V]) -> (M, V, Vec<V>)` is declared in Task 3's placeholder and implemented with that exact signature in Task 5. `SUB_NATIVE_SVD` takes the same two values in Tasks 6, 7 and 8.

**Known gap, deliberately left open.** Task 4 Step 2 requires one online `cargo build` to refresh `Cargo.lock` for the `cc` build dependency, which breaks the `--offline` rule exactly once. It is called out in place rather than hidden.
