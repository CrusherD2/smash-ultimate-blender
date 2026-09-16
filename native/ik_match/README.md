# Experimental Rust IK matching accelerator

This library can evaluate pole-search candidates without repeated
Blender dependency-graph updates. Python captures the pre-IK pose once per frame,
Rust converts the detached numeric inputs and solves them, and Python retains
the original search order, scoring and key writer. No Rust worker accesses
Blender data. The standalone CLI is also retained for numerical diagnostics.

The Windows x64 library is bundled at `native/bin/sub_ik_match_native.dll`.
It is enabled by default where it is supported, on the corpus evidence in
`docs/benchmarks/native-default-2026-09-13.md`. Selection covers Blender 4.5 and 5.2,
independent generated two-bone chains with spherical joints, one position goal and a
pole target.
Existing dependency checks must pass before selecting it. Custom solver
constraints, IK limits/locks/stiffness, rotational goals, native IK stretch,
other platforms/versions and missing binaries retain the Blender path.

## Exactness and fallback

The experimental accelerator checks convergence within Blender's minimum twelve
iterations and rejects nearly collinear starting geometry. Neither check proves
bit-exact compatibility: near-straight test cases still differ from Blender.
The library returns a fallback status for rejected solves. The scheduler evaluates Blender at the
same candidate angle and uses Blender for the rest of that chain's search in
that frame. Native errors also fall back; cleanup releases all handles and
restores the frame and constraint state if the operation raises.

`SUB_NATIVE_IK=1` enables **verification mode**: every candidate is evaluated by
Blender too, compared component by component, and Blender's matrices are used.
This preserves exactness but adds overhead; it is for development, not acceleration.
`SUB_NATIVE_IK=experimental` skips that verification and can change results.
Do not rely on either when bit-exact matching is required rather than measured.
With no environment override, ordinary matching and import now take the native path
where the guards above admit it, and the previously optimized Blender path everywhere
else. Add-on Preferences has a **Use Native IK Accelerator** toggle for modders who
don't set environment variables; unticking it is equivalent to `SUB_NATIVE_IK=0`.
An explicitly set `SUB_NATIVE_IK` (including `=1` or `=experimental`) always wins
over that preference.

The acceptance heuristics do not establish a numerical compatibility boundary.
The diagnostic kernel's unrestricted iterations produced divergent results on
difficult synthetic poses, so it is not used as a general replacement. Its
one-sided Jacobi SVD is mathematically equivalent to the required decomposition
but is not bit-compatible with every arithmetic path in Eigen. Tests compare
accepted matrices and final keys exactly, with no rounding or epsilon allowance.
Passing the tested cases is evidence of compatibility, not a proof over all
possible rigs or floating-point inputs.

Important compatibility details include Blender's f32 pole-angle trigonometry,
f32 input conversion, reciprocal-based 3×3 inversion, Eigen's packet arithmetic
for 4×4 inversion, paired SSE matrix sums, and rescaling only the X/Z output axes.
Python `mathutils` matrix multiplication/inversion use different rounding paths
and cannot substitute for these internal Blender operations.

## Build and stage

From the repository root on Windows x64, with Rust/MSVC installed:

```powershell
python native/ik_match/build.py
```

This runs release tests, builds with the locked offline dependencies, copies the
DLL into `native/bin`, and stages dependency license notices. Offline builds
require the dependencies to have been cached. The recorded build used Rust
1.89.0. Numerical golden tests must pass when updating compilers or dependencies.
Restart Blender after replacing a DLL that it has loaded.

To build without staging:

```powershell
cargo test --offline --locked --manifest-path native/ik_match/Cargo.toml --release
cargo build --offline --locked --manifest-path native/ik_match/Cargo.toml --release
```

## Reproduce validation and benchmarks

```powershell
$env:PYTHONIOENCODING='utf-8'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/test_native_ik_backend_blender.py
$env:SUB_NATIVE_CASES='10000'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/test_native_ik_synthetic_blender.py
$env:SUB_MATCH_RUNS='3'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/benchmark_native_ik_match_blender.py
```

The synthetic suite creates its own rig. The real-rig tests need the local
Sceptile fixtures under `.tests/benchmarks/ik_apply/out/`; the benchmark accepts
`SUB_BASELINE_BLEND`. Paired runs compare the saved pre-native source when
available, otherwise the current source with the accelerator disabled. They
record whole-rig pose and key fingerprints, compiler-input/DLL hashes and timing.

`SUB_NATIVE_IK=0` explicitly disables the native backend everywhere, and the
**Use Native IK Accelerator** add-on preference offers the same off switch without
an environment variable (the environment variable wins whenever it is set).
`SUB_NATIVE_THREADS`
selects one or four native threads. Frames and previous-angle candidates remain
ordered; only independent limbs are eligible for native batch execution.
One thread is the default: measured whole-operation times were faster than with
four threads because each live batch contains at most four very small solves.
The larger detached CLI batches still benefit from four threads.

The benchmark explicitly selects experimental mode and checks final results
against Blender on the fixture. Set `SUB_NATIVE_BENCH_MODE=1` to measure verification
overhead, or `SUB_NATIVE_BENCH_MODE=0` to compare the unchanged default path.
The singular regression suite records native mismatches and asserts that the
verified scheduler returns exact Blender matrices:

```powershell
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/test_native_ik_singular_blender.py
```

The unrestricted kernel diagnostic is separate:

```powershell
$env:SUB_NATIVE_FULL_SEARCH='1'
python tests/run_blender_test.py --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' tests/test_native_ik_probe_blender.py
```

It exports all candidate problems and records kernel timings under
`.tests/benchmarks/native_ik/`. The CLI accepts
`input.json output.json [threads] [runs]`, warming its pool before timed batches.
Its timings exclude process startup, parsing, export and serialization; they
must not be presented as complete matching or import times. `SUB_NATIVE_STRICT=0`
is available only for diagnostic runs that record mismatches without failing.

## Provenance and licenses

Solver logic follows Blender `v4.5.0`, copyright NaN Holding BV / Blender Authors:

- https://github.com/blender/blender/tree/v4.5.0/intern/iksolver/intern
- https://github.com/blender/blender/blob/v4.5.0/source/blender/ikplugin/intern/iksolver_plugin.cc
- https://github.com/blender/blender/blob/v4.5.0/source/blender/blenlib/intern/math_matrix_c.cc

`inverse4.rs` adapts the vendored Eigen packet inverse under MPL-2.0, with the
original Intel, Gael Guennebaud and Benoit Jacob notices retained. Other crate
source files are GPL-2.0-or-later. Full texts and dependency notices accompany
the source in `LICENSES/`. The Python diagnostic inverse reference carries the
same upstream attribution. The compact golden fixture contains captured
numeric matrices from Blender 5.2.1; it requires no model assets at test time.

See `docs/benchmarks/position-ik-rust-round2-2026-09-12.md` for measured results.
