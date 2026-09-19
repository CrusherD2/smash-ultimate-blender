"""Additive component API in the IK Rust library; safe NumPy fallbacks.

Only detached numeric arrays cross this boundary. Blender evaluation and writes
stay on its main thread. SUB_NATIVE_COMPONENTS=0 disables this backend.
"""
import ctypes as ct
import os
from pathlib import Path
import numpy as np

_library = None
_attempted = False
_pointer = ct.POINTER(ct.c_double)


def library():
    global _library, _attempted
    if os.environ.get('SUB_NATIVE_COMPONENTS', '1') == '0':
        return None
    if not _attempted:
        _attempted = True
        try:
            dll = ct.CDLL(str(Path(__file__).resolve().parents[2] / 'native/bin/sub_ik_match_native.dll'))
            dll.sub_component_abi_version.restype = ct.c_uint32
            if dll.sub_component_abi_version() != 1:
                return None
            dll.sub_component_project.argtypes = [_pointer, _pointer, ct.c_size_t, ct.c_size_t, ct.c_size_t, _pointer]
            dll.sub_component_expressions.argtypes = [_pointer, ct.c_size_t, _pointer, ct.c_size_t, ct.c_size_t, _pointer]
            dll.sub_component_lstsq.argtypes = [_pointer, _pointer, ct.c_size_t, ct.c_size_t, _pointer]
            dll.sub_component_relative.argtypes = [_pointer, _pointer, _pointer]
            _library = dll
        except (OSError, AttributeError):
            pass
    return _library


def array(value):
    return np.ascontiguousarray(value, dtype=np.float64)


def ptr(value):
    return value.ctypes.data_as(_pointer)


def relative(left, right):
    from mathutils import Matrix
    a, b = array(left), array(right)
    if a.shape != (4, 4) or b.shape != (4, 4):
        raise ValueError('Expected two 4x4 transforms')
    out = np.empty((4, 4))
    dll = library()
    if dll and dll.sub_component_relative(ptr(a), ptr(b), ptr(out)):
        return Matrix(out.tolist())
    return left.inverted_safe() @ right


def project(inverse, goals):
    a, b = array(inverse), array(goals)
    if a.ndim != 2 or b.ndim not in (1, 2) or b.shape[-1] != a.shape[1]:
        raise ValueError('Incompatible projection dimensions')
    rows, cols = a.shape
    out = np.empty((1 if b.ndim == 1 else len(b), rows))
    dll = library()
    if dll and dll.sub_component_project(ptr(a), ptr(b), rows, cols, len(out), ptr(out)):
        return out[0] if b.ndim == 1 else out
    return b @ a.T


def lstsq(matrix, goal):
    a, b = array(matrix), array(goal)
    if a.ndim != 2 or b.ndim != 1 or len(b) != a.shape[0]:
        raise ValueError('Incompatible solve dimensions')
    out = np.empty(a.shape[1])
    dll = library()
    if dll and dll.sub_component_lstsq(ptr(a), ptr(b), *a.shape, ptr(out)):
        return out
    return np.linalg.lstsq(a, b, rcond=1e-5)[0]


def expressions(segments, goals):
    b = array(goals)
    if b.ndim not in (1, 2):
        raise ValueError('Expected expression feature vectors')
    width = b.shape[-1]
    packed = array([np.concatenate(([i, lo, hi], start, end)) for i, lo, hi, start, end in segments])
    if len(segments) and packed.shape != (len(segments), 3+2*width):
        raise ValueError('Incompatible expression dimensions')
    targets = b.reshape(-1, width)
    out = np.empty((len(targets), 3))
    dll = library()
    if not (dll and dll.sub_component_expressions(ptr(packed), len(segments), ptr(b), width, len(targets), ptr(out))):
        for row, desired in zip(out, targets):
            row[:] = (float(desired@desired), 0, 0)
            for index, low, high, previous, endpoint in segments:
                delta = endpoint-previous
                denominator = float(delta@delta)
                t = float(np.clip(((desired-previous)@delta)/denominator, 0, 1)) if denominator > 1e-12 else 0.0
                residual = desired-previous-delta*t
                error = float(residual@residual)
                if error < row[0]-1e-12:
                    row[:] = (error, index, low+(high-low)*t)
    return out[0] if b.ndim == 1 else out
