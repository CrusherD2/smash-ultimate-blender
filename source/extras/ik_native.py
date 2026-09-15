"""Optional Rust accelerator for independent, two-bone IK matching.

On by default where it is supported (Windows x64, Blender 4.5/5.2, bundled DLL),
adopted on the corpus evidence in docs/benchmarks/native-default-2026-09-13.md.
SUB_NATIVE_IK=0 forces it off everywhere, SUB_NATIVE_IK=1 verifies every
candidate against Blender, SUB_NATIVE_IK=experimental is the explicit spelling
of the default. The native SVD is not proven bit-compatible on every input, so
the per-frame guards and fallbacks here remain the reason that is survivable.
"""
import ctypes
import json
import os
import time
from pathlib import Path
from mathutils import Matrix

from . import ik_match_diag as diag

_dll = None

# Unset means the native backend is on where it is supported. '0' forces it off
# everywhere; '1' is verification mode; 'experimental' is the same acceleration
# as the default, named explicitly. Adopted on the evidence in
# docs/benchmarks/native-default-2026-09-13.md: 28 corpus runs across three
# fixtures and both supported Blender versions, every solved pose identical to
# Blender's backend, with the guards declining no run outright and Blender
# finishing the chain-frames they did decline.
_DEFAULT_MODE = 'experimental'
# Anything outside this set -- including an explicit '0' -- leaves Blender's
# path in place. Read through mode() and never directly, so get_factory,
# evaluate_steps and ik_channels' native pole search cannot drift apart.
_ENABLED_MODES = {'1', 'experimental'}


def _native_ik_preference_enabled():
    """Whether the add-on's own off switch allows the native backend.

    Defensive by design: bpy.context.preferences.addons[...] can be absent or
    raise during registration, in background/headless runs, or if this add-on
    is loaded under an unexpected module name. Any failure here resolves to
    True (the default) and never raises, so headless test runs -- which are
    how this whole project is verified -- can't be broken by this lookup.
    """
    try:
        from ..addon_preferences import get_addon_preferences
        prefs = get_addon_preferences()
        if prefs is None:
            return True
        return bool(prefs.use_native_ik_accelerator)
    except Exception:
        return True


def mode():
    """The resolved SUB_NATIVE_IK mode, with the default and preference applied.

    An explicit SUB_NATIVE_IK always wins, including '0': it is the documented
    escape hatch and the developer's verification tool, and every existing
    test sets it, so a saved preference must never override it. Only when the
    variable is unset does the add-on preference get a say, and an unticked
    preference then behaves exactly like an explicit '0'.
    """
    value = os.environ.get('SUB_NATIVE_IK')
    if value is not None:
        return value
    if not _native_ik_preference_enabled():
        return '0'
    return _DEFAULT_MODE


def enabled():
    """True when the resolved mode asks for the native backend at all."""
    return mode() in _ENABLED_MODES


def verifying():
    """True when every native candidate must be re-checked against Blender.

    False under SUB_NATIVE_IK=0 as well as under the accelerating modes, so this
    answers "verify or not" and never "native or not". Pair it with enabled()
    wherever both questions are being asked.
    """
    return mode() == '1'


class Solver:
    def __init__(self, obj, job, bones, con, frame):
        global _dll
        if _dll is None:
            path = Path(__file__).resolve().parents[2] / 'native/bin/sub_ik_match_native.dll'
            library = ctypes.CDLL(str(path))
            library.sub_ik_abi_version.restype = ctypes.c_uint32
            if library.sub_ik_abi_version() != 3:
                raise RuntimeError('Incompatible native IK library')
            library.sub_ik_create.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
            library.sub_ik_create.restype = ctypes.c_void_p
            library.sub_ik_create_raw.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
            library.sub_ik_create_raw.restype = ctypes.c_void_p
            library.sub_ik_solve.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
            library.sub_ik_solve.restype = ctypes.c_int
            library.sub_ik_free.argtypes = [ctypes.c_void_p]
            library.sub_ik_free.restype = None
            library.sub_ik_iterations.argtypes = [ctypes.c_void_p]
            library.sub_ik_iterations.restype = ctypes.c_size_t
            library.sub_ik_solve_many.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
                                              ctypes.POINTER(ctypes.c_float), ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint8)]
            library.sub_ik_solve_many.restype = ctypes.c_bool
            library.sub_ik_search.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
            library.sub_ik_search.restype = ctypes.c_int
            _dll = library
        rows = lambda matrix: [list(row) for row in matrix]
        case = dict(parent=rows(bones[0].parent.matrix) if bones[0].parent else rows(Matrix.Identity(4)),
                    poses=[rows(b.matrix) for b in bones], rests=[rows(b.bone.matrix) for b in bones],
                    heads=[list(b.head) for b in bones], tails=[list(b.tail) for b in bones],
                    lengths=[b.bone.length for b in bones], object=rows(obj.matrix_world),
                    target=rows(obj.pose.bones[con.subtarget].matrix),
                    pole=rows(obj.pose.bones[con.pole_subtarget].matrix), iterations=con.iterations,
                    # Unrecognised values deserialize to the approximate
                    # backend in Rust, so a typo here cannot silently select
                    # an unverified solver.
                    backend=os.environ.get('SUB_NATIVE_SVD', 'approximate'))
        data = json.dumps(case).encode()
        self.handle = _dll.sub_ik_create_raw(data, len(data))
        if not self.handle:
            raise RuntimeError('Rust rejected the captured IK problem')
        self.buffer = (ctypes.c_float * (16*len(bones)))()
        self.bones = tuple(bones)
        self.fallback = False

    def solve(self, angle):
        status = _dll.sub_ik_solve(self.handle, angle, self.buffer, len(self.buffer))
        if status == 0:
            raise RuntimeError('Rust failed to solve the captured IK problem')
        if status == 2:
            return None
        return [Matrix([self.buffer[offset+r*4:offset+r*4+4] for r in range(4)])
                for offset in range(0,len(self.buffer),16)]

    def search(self, reference_columns, seeds, tolerance, refine_steps):
        """Run the whole pole search natively. None means fall back to Blender.

        reference_columns is one tuple of four columns per solved bone, in the
        same order the per-candidate path scores them.
        """
        flat = [value for columns in reference_columns
                for column in columns for value in column]
        reference = (ctypes.c_float * len(flat))(*flat)
        seed_buffer = (ctypes.c_double * 3)(*seeds)
        angle = ctypes.c_double()
        status = _dll.sub_ik_search(self.handle, reference, len(flat), seed_buffer,
                                    tolerance, refine_steps, ctypes.byref(angle),
                                    self.buffer, len(self.buffer))
        if status != 1:
            self.fallback = True
            return None
        matrices = [Matrix([self.buffer[offset+r*4:offset+r*4+4] for r in range(4)])
                    for offset in range(0, len(self.buffer), 16)]
        return angle.value, matrices

    def close(self):
        if self.handle:
            _dll.sub_ik_free(self.handle)
            self.handle = None

    def iterations(self):
        return _dll.sub_ik_iterations(self.handle)

    def __del__(self):
        if getattr(self, 'handle', None):
            self.close()


def supported(obj, bones, con):
    if (len(bones) != 2 or con.chain_count != 2 or con.use_stretch or con.use_rotation
            or not con.use_location or not con.use_tail or con.ik_type != 'COPY_POSE'
            or con.influence != 1.0 or con.weight != 1.0
            or con.owner_space != 'WORLD' or con.target_space != 'WORLD'
            or con.target != obj or con.pole_target != obj
            or not con.subtarget or not con.pole_subtarget):
        return False
    flags = ('lock_ik_x','lock_ik_y','lock_ik_z','use_ik_limit_x','use_ik_limit_y','use_ik_limit_z',
             'ik_stiffness_x','ik_stiffness_y','ik_stiffness_z')
    for bone in bones:
        if any(getattr(bone, name) for name in flags) or any(c != con for c in bone.constraints):
            return False
        if any(v <= 0 for v in bone.scale):
            return False
    return True


class Factory:
    def __init__(self):
        self.solvers = []

    def __call__(self, obj, job, bones, con, frame):
        if not supported(obj, bones, con):
            return None
        try:
            solver = Solver(obj, job, bones, con, frame)
        except (OSError, ValueError, RuntimeError, AttributeError):
            return None
        self.solvers.append(solver)
        diag.add('native_solves', 0.0, 1)
        return solver

    def close(self):
        for solver in self.solvers:
            solver.close()
        self.solvers.clear()


def get_factory():
    import bpy
    import sys
    import platform
    # Bundled binary and numerical comparisons currently cover these Windows
    # builds. Other platforms/versions retain Blender's existing implementation.
    if (not enabled() or sys.platform != 'win32'
            or platform.machine().lower() not in {'amd64','x86_64'}
            or bpy.app.version[:2] not in {(4,5),(5,2)}
            or not (Path(__file__).resolve().parents[2] / 'native/bin/sub_ik_match_native.dll').is_file()):
        return None
    return Factory()


class Request:
    def __init__(self, solver, angle):
        self.solver, self.angle = solver, angle
        self.matrices = None


def evaluate_steps(context, steps, batch):
    if not batch:
        for step in steps:
            evaluate_steps(context, [step], True)
        return
    pending = steps
    while pending:
        waiting, requests = [], []
        evaluate_scene = False
        for step in pending:
            try:
                value = next(step)
            except StopIteration:
                continue
            waiting.append(step)
            if isinstance(value, Request):
                requests.append(value)
            else:
                evaluate_scene = True
        if evaluate_scene:
            if diag.enabled():
                start = time.perf_counter()
                context.view_layer.update()
                diag.add('search', time.perf_counter() - start, 1)
            else:
                context.view_layer.update()
        if requests:
            native_requests = [r for r in requests if not r.solver.fallback]
            if native_requests:
                handles = (ctypes.c_void_p*len(native_requests))(*(r.solver.handle for r in native_requests))
                angles = (ctypes.c_float*len(native_requests))(*(r.angle for r in native_requests))
                output = (ctypes.c_float*sum(len(r.solver.buffer) for r in native_requests))()
                statuses = (ctypes.c_uint8*len(native_requests))()
                # These batches contain at most four tiny solves. Measured
                # thread scheduling cost exceeds the parallel compute saving.
                threads = int(os.environ.get('SUB_NATIVE_THREADS','1'))
                if not _dll.sub_ik_solve_many(handles,angles,len(native_requests),output,len(output),threads,statuses):
                    # A rejected native batch must not leave a partial match.
                    # All candidates already have their pole angles set, so one
                    # normal graph evaluation supplies the original results.
                    for i in range(len(statuses)):
                        statuses[i] = 2
                offset = 0
                for request,status in zip(native_requests,statuses):
                    size = len(request.solver.buffer)
                    if status == 2:
                        request.solver.fallback = True
                    else:
                        request.matrices = [Matrix([output[i+r*4:i+r*4+4] for r in range(4)])
                                            for i in range(offset,offset+size,16)]
                    offset += size
            verify = verifying()
            if verify or any(r.solver.fallback for r in requests):
                if diag.enabled():
                    start = time.perf_counter()
                    context.view_layer.update()
                    diag.add('search', time.perf_counter() - start, 1)
                else:
                    context.view_layer.update()
                for request in requests:
                    if verify or request.solver.fallback:
                        actual = [b.matrix.copy() for b in request.solver.bones]
                        if (request.matrices is None or
                                any(tuple(a) != tuple(b)
                                    for proposed, observed in zip(request.matrices, actual)
                                    for a, b in zip(proposed, observed))):
                            request.solver.fallback = True
                        request.matrices = actual
        pending = waiting
