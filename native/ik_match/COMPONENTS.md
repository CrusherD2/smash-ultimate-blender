# Component matching extension

`src/components.rs` and `src/component_graph.rs` add component APIs to the existing DLL.
The IK ABI (version 3), solver implementation, and IK Python adapter are unchanged.
Build and stage with the existing `build.py`.

The component adapter is `source/extras/component_native.py`. It provides:

- Batched projection for finger/transform sliders and material eye-look offsets.
- Minimum-norm least squares for directional bone eyes and nonlinear fitting steps.
- Batched best-expression/strength selection, including intermediate expression checkpoints.
- Relative transforms for isolated controls and component residual correction.

`source/extras/component_graph.py` captures a detached dependency model per
component, then combines supported components into one shared graph. Common
dependencies are evaluated once per candidate; unsupported groups retain a local
fallback. Rust evaluates its bone hierarchy, generated local TRANSFORM sliders,
COPY_TRANSFORMS helpers, DAMPED_TRACK targets, local location limits, and the
restricted arithmetic drivers used by bone eyes and mouth/eyelid expressions.
Candidate fitting and finger-circle correction read this model instead of
triggering Blender updates. Isolated controls and their heel/toe helpers use
the same model. Material eye-look matching already has a direct solution and
uses batched target conversion without a dependency-graph fitting loop.

Finger and expression targets are prepared in chunks of 128 frames. Numeric
batches over 32 frames run across Rayon workers. Workers receive only numeric
buffers. Bone-space conversion, control writes and keyframe insertion stay on
the main thread. The per-frame matching loop remains serial; the detached
graph removes candidate evaluation round trips, rather than threading Blender.

Blender verifies each completed native matching frame before keying it. On
failure, the matcher restores the editable bases and retries before stashing
keys. The rejected component and its dependents use the reference path for the
remainder of that run; independent components retain their native graphs.
`component_graph.LAST_DIAGNOSTICS` records per-component modes/reasons, native
evaluations/frames, reference evaluations and verification fallback.

Capture checks dependency topology before entering Rust. Unsupported constraints,
external dependencies and custom drivers use lazy Blender evaluation: querying a
native component does not trigger a scene update for an unrelated reference-only
component. Requested reference matrices are copied and cached per candidate.
Candidate consumers must read the snapshot before mutating controls. Final pose
verification and action rollback still apply to mixed evaluation.

`SUB_NATIVE_COMPONENTS=0` selects NumPy/Blender fallbacks independently of IK.
Missing/older DLLs automatically fall back. Singular relative transforms keep
Blender's `inverted_safe` policy. Nonconvergent native least squares also falls
back. Existing final pose verification and action rollback remain enabled.

Validation: `tests/test_component_native_blender.py` compares batched projection,
rank-deficient fitting, expression selection, and matrix corrections with the
reference math. Existing component, face, checkpoint, finger and import tests
exercise the integration; native IK synthetic tests check the existing solver.
`test_component_graph_blender.py` asserts that supported fixtures actually use
the detached graph without falling back (select with `SUB_GRAPH_FIXTURE`).
`test_component_graph_fallback_blender.py` injects a bad applied candidate and
checks both the Blender retry and rejection of an unsupported user constraint.

The synthetic eight-frame full-hand test on Blender 5.2 measured 152 explicit
Blender updates / 0.125 s on the reference path and 8 updates / 0.064 s with the
detached graph, with identical pose tolerances. These counts exclude
`scene.frame_set`; sampling and one final verification still use Blender.
This is a small synthetic benchmark, not a universal speedup claim.

## Blender source math

`component_math.rs` now ports the relevant Blender v4.5.0 routines, with
row-major indexing adapted for the Rust representation:

- `constraint.cc`: `transform_evaluate` (location-to-rotation, AFTER),
  `damptrack_do_transform` at full influence.
- `math_rotation_c.cc`: `eulO_to_mat3`, `axis_angle_normalized_to_mat3_ex`.
- `math_matrix_c.cc`: `mat3_to_rot_size`, rotation/scale reconstruction,
  scalar 3x3 products and the SSE2 4x4 addition order.
- `math_vector_inline.cc`: normalization thresholds and operation order.

Source: https://github.com/blender/blender/tree/v4.5.0/source/blender

Matrix arithmetic is float32; Euler trig retains Blender's double intermediates.
Drivers evaluate expressions in double, rounding stored channels to float.
Existing IK matrix multiplication and inverse ports are reused without editing
the IK implementation. Rest offsets use stored bone orientation/head/parent
length. Undriven input bases come straight from Blender, avoiding lossy
matrix-to-Euler-to-matrix conversion. The component graph ABI is now version 5;
the old numerical and IK entry points remain available.

The detached path also handles connected bones (ignore input translation and
restore head position after the constraint stack), all six Inherit Scale modes,
disabled Inherit Rotation/Local Location, partial constraint influence, animated
constraint settings, and transformed look-target armatures. Animated settings
refresh the capture only when their evaluated values change, including transitions
to/from zero influence. Driver-controlled constraint settings stay on the reference
path because they can depend on the candidate being fitted.

`component_blend.rs` ports polar matrix interpolation (including quaternion
interpolation), using the existing native SVD. `component_space.rs` ports
BoneParentTransform inheritance and pose/bone conversion. Graph evaluation no
longer calls Blender's Matrix.lerp or Bone.convert_local_to_pose callbacks.
LOCAL-space constraint targets and drivers use the evaluated pose-to-bone round
trip; raw basis channels are not interchangeable at float32 precision. This
matters for small sliders away from the origin and branching driver expressions.
World transforms are applied before tracking and constraint blending. Python
still orchestrates matching, converts sampled targets, writes keys and runs the
final Blender pose verification; this is not a complete standalone Blender.

Copy Transforms supports REPLACE, BEFORE_FULL and AFTER_FULL in POSE owner space,
with LOCAL or POSE target space and optional partial influence. Local location
limits now evaluate in stack order.

Additional native constraint ports now cover:

- Limit Rotation: LOCAL/POSE/WORLD, all Euler orders, legacy and cyclic clamping,
  stable shear removal, per-axis switches and partial influence.
- Limit Scale: LOCAL/POSE/WORLD, per-axis minimum/maximum and partial influence.
- Copy Location: LOCAL/POSE/WORLD, axis switches/inversion and offset (head target).
- Copy Rotation: LOCAL/POSE/WORLD, all Euler orders, axis switches/inversion,
  REPLACE/ADD/BEFORE/AFTER/OFFSET and compatible Euler handling.
- Copy Scale: LOCAL/POSE/WORLD, offset/additive/multiplicative modes, uniform
  scaling, power and axis switches.
- Child Of: WORLD owner/target, stored inverse, per-channel switches and influence.

The above constraint math is translated into Rust from Blender's constraint and
matrix/rotation routines. Independent external objects/FK armature bones can be
WORLD targets for these copy constraints, Child Of and Damped Track. They refresh
after frame changes; targets with constraints, drivers or parenting dependencies
on the matched armature conservatively use Blender.

Scripted driver expressions support arithmetic, powers, Python-style modulo/floor
division, comparisons, short-circuit boolean/conditional expressions, trigonometric
functions, sqrt/exp/log/log10, abs/floor/ceil/trunc, degrees/radians, min/max, pi/e/tau
and frame. SUM/AVERAGE/MIN/MAX drivers are also native. Inputs include same-armature
LOCAL/WORLD position, Euler rotation, scale/average scale, expression selectors and
independent scalar custom properties (including properties on other IDs).
Custom-property/frame values refresh as they change. Expressions are parsed as
restricted ASTs, never executed as Python by the native adapter. Invalid/blocked
drivers and replaced/custom namespace functions are not silently substituted.

Remaining reference-only cases include arbitrary Python functions, driver-computed
custom properties, driver F-Curve remapping/nonidentity modifiers, custom spaces,
quaternion/swing-twist driver variables, mesh/path/simulation constraints, other
unimplemented constraint modes, and coupled external dependencies. Identity driver
curves/default replacement generators are checked explicitly. This is expanded
coverage, not a complete independent implementation of Blender. Cycles and singular transforms are
detected and sent to the reference path; this cannot make an invalid or ambiguous
rig uniquely solvable. Matching must still pass the final pose check or roll back.

`test_component_blender_math.py` compares detached output directly with Blender
before residual correction, covering Euler orders, negative/nonuniform scales,
tracking edge cases, partial influence, animated settings, transformed armatures,
connected bones and every inheritance mode. `test_component_hybrid_blender.py`
checks external/custom constraints, custom drivers, cycles, dependent fallbacks
and the absence of unrelated scene updates during native probes.
`test_component_hybrid_matching_blender.py` covers mixed matching, export,
rematching and baking. These are tolerance comparisons, not a claim of
bit-identical output on every Blender platform/version.

`test_component_driver_constraints_blender.py` adds direct comparisons for the new
constraints and driver functions, including negative scale/shear, all spaces,
frame/custom-property updates, conditional short-circuiting, external targets and
rejection of candidate-dependent targets/custom namespace functions. Run this
isolated factory-startup fixture with `--enable-autoexec` because it deliberately
tests trusted Python driver expressions in addition to Blender's simple evaluator.

The Python adapter also avoids rereading unchanged external samples and unused
driver channels. Matching reuses evaluated results when no controls changed and
reads each RNA matrix once during error checking. A 64-frame full-hand benchmark
with these changes measured 0.450 s / 620 explicit updates on the reference path
and 0.225 s / 64 updates with native components. Both validated the same poses.
Run `tests/benchmark_component_match_blender.py` with `SUB_NATIVE_COMPONENTS=0`
and `1` in separate background Blender runs; `SUB_BENCH_PROFILE=1` enables a
profile. This measured approximately 2x, not 3x. After the hybrid extension the
same serial benchmark measured 0.476 s / 620 updates versus 0.234 s / 64 updates.

## Machamp reproduction and combined matching

On the supplied `machamp.blend` (55 frames, 60 matched finger joints), profiled
finger matching fell from 61–62 seconds to approximately 1.15 seconds. The old
2e-6 per-joint fitting gate retried float32 noise thousands of times. It now uses
1e-4, below the unchanged final 2e-4 pose acceptance check. AFTER-rotation circle
correction preserves the source TRS scale rather than rotating nonuniform scale
through a full matrix inverse.

The corrected Rust LOCAL-space conversion kept all 55 frames native: 110 graph
evaluations and zero reference candidate evaluations. Reloading the saved keys
in the same background test gave a worst finger matrix difference of 3.44e-5.
Full rig creation measured 7–9 seconds versus about 68 seconds; timings include
cProfile and vary with system load. The existing IK implementation was not changed.

Rig creation with a custom preset and fingers now uses one combined sampling,
matching and key-writing pass. The three-component facial fixture uses six
graph evaluations over three frames rather than eighteen. Tests cover combined
preset/finger creation, translated short sliders, mixed native/reference groups,
verification rollback, rematching, importing, exporting and baking.

`tests/profile_animation_rig_blender.py` opens `SUB_RIG_PROFILE_BLEND` read-only
in a background factory-startup Blender process. Set `SUB_RIG_PROFILE_RUN=1`
for creation timings and optionally `SUB_RIG_PROFILE_VERIFY=1` to check saved
finger keys. It never saves the blend. `SUB_RIG_PROFILE_GRAPH=1` enables a
diagnostic comparison that adds scene updates and should not be used for timing.
