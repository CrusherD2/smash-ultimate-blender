"""Native component math versus NumPy, including degenerate expressions/solves."""
from pathlib import Path
import importlib.util
import os
import numpy as np
from mathutils import Matrix

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('component_native', root/'source/extras/component_native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
os.environ['SUB_NATIVE_COMPONENTS'] = '1'
assert native.library() is not None, 'New DLL must be loaded; fallback alone is not a test'
assert native.library().sub_ik_abi_version() == 3
rng = np.random.default_rng(71)
for rows, cols in ((60, 12), (9, 2), (4, 10), (9, 9)):
    for singular in (False, True):
        a = rng.normal(size=(rows, cols))
        if singular:
            a[:, -1] = a[:, 0]
        b = rng.normal(size=rows)
        expected = np.linalg.lstsq(a, b, rcond=1e-5)[0]
        actual = native.lstsq(a, b)
        np.testing.assert_allclose(actual, expected, rtol=1e-7, atol=1e-8)
        inverse = np.linalg.pinv(a, rcond=1e-5)
        goals = rng.normal(size=(100, rows))
        np.testing.assert_allclose(native.project(inverse, goals), goals@inverse.T, atol=1e-10)
segments = [(1, 0., .5, np.zeros(9), rng.normal(size=9)),
            (1, .5, 1., rng.normal(size=9), rng.normal(size=9)),
            (2, 0., 1., np.zeros(9), np.zeros(9))]
goals = rng.normal(size=(100, 9))
actual = native.expressions(segments, goals)
os.environ['SUB_NATIVE_COMPONENTS'] = '0'
expected = native.expressions(segments, goals)
np.testing.assert_allclose(actual, expected, atol=1e-10)
os.environ['SUB_NATIVE_COMPONENTS'] = '1'
for _ in range(30):
    a = np.eye(4); a[:3, :3] += rng.normal(size=(3, 3))*.1
    b = np.eye(4); b[:3, :] += rng.normal(size=(3, 4))*.1
    np.testing.assert_allclose(native.relative(Matrix(a), Matrix(b)), np.linalg.solve(a, b), atol=3e-7)
assert native.relative(Matrix.Diagonal((0, 1, 1, 1)), Matrix.Identity(4)) is not None
print('NATIVE COMPONENT PARITY PASSED')
