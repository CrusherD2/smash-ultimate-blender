"""Locked orthographic views must project like Blender's ortho camera, at every depth."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from mathutils import Euler, Matrix, Vector

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')


def ortho_view(rotation, pivot, distance, half_h, aspect, clip_end):
    rot = rotation.to_matrix().to_4x4()
    eye = Vector(pivot) + rotation @ Vector((0, 0, distance))
    view = rot.inverted() @ Matrix.Translation(-eye)
    half_w = half_h * aspect
    window = Matrix((
        (1 / half_w, 0, 0, 0),
        (0, 1 / half_h, 0, 0),
        (0, 0, -2 / clip_end, 0),
        (0, 0, 0, 1),
    ))
    rv3d = SimpleNamespace(view_matrix=view, window_matrix=window, view_location=Vector(pivot),
                           view_distance=distance, view_perspective='ORTHO')
    return rv3d, SimpleNamespace(clip_end=clip_end)


def ndc(matrix, point):
    clip = matrix @ point.to_4d()
    return Vector((clip.x / clip.w, clip.y / clip.w, clip.z / clip.w))


def gpu_ndc(view, proj, point):
    # The renderer multiplies in float32, so check what the GPU actually gets.
    v = np.array(view, dtype=np.float32).reshape(4, 4).T
    p = np.array(proj, dtype=np.float32).reshape(4, 4).T
    clip = p @ (v @ np.array([*point, 1.0], dtype=np.float32))
    return clip[:3] / clip[3]


width, height = 1600, 900
for rotation, pivot, distance, half_h in (
        (Euler((1.5708, 0, 1.5708)), (0, 0, 10), 15.0, 12.0),  # Right view, close zoom
        (Euler((1.5708, 0, 0)), (3, -2, 8), 60.0, 4.0),  # Front view, tight ortho zoom
        (Euler((1.5708, 0, -1.5708)), (0, 0, 9), 15.0, 0.3),  # -X view zoomed far in
        (Euler((1.5708, 0, 0)), (0, 0, 9), 15.0, 300.0),  # zoomed far out
):
    rv3d, space = ortho_view(rotation.to_quaternion(), pivot, distance, half_h, width / height, 1000.0)
    # The character stands 300 units behind the view pivot, as during a dash in a side view.
    axes = [rotation.to_quaternion() @ Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    character = Vector(pivot) - axes[2] * 300
    focus = (rv3d.view_matrix @ character).z
    view, proj, _eye = viewport._camera_to_smash(rv3d, None, width, height, space, focus)
    smash_view = Matrix([[view[c * 4 + r] for c in range(4)] for r in range(4)])
    smash_proj = Matrix([[proj[c * 4 + r] for c in range(4)] for r in range(4)])
    blender = rv3d.window_matrix @ rv3d.view_matrix
    worst = 0.0
    checked = 0
    # Hands/feet sit well in front of and behind the pivot plane during animation.
    for a in (-0.9, 0, 0.9):
        for b in (-0.9, 0, 0.9):
            for depth in (-30, -10, 0, 10, 30):  # the character's own extent
                point = (character + axes[0] * a * half_h * width / height
                         + axes[1] * b * half_h + axes[2] * depth)
                want = ndc(blender, point)
                got = gpu_ndc(view, proj, viewport._Z_UP_TO_Y_UP @ point)
                assert 0.0 <= got[2] <= 1.0, ('clipped', point, got)
                checked += 1
                worst = max(worst, abs(got[0] - want.x) * width / 2, abs(got[1] - want.y) * height / 2)
    assert checked >= 9, checked
    assert worst < 0.5, f'ortho preview is off by {worst:.2f} px at half height {half_h}'
# Without a character the plane stays at Blender's pivot.
rv3d, space = ortho_view(Euler((1.5708, 0, 0)).to_quaternion(), (0, 0, 9), 15.0, 5.0, width / height, 1000.0)
assert viewport._camera_to_smash(rv3d, None, width, height, space) == viewport._camera_to_smash(rv3d, None, width, height, space, -15.0)
print('SMASH_VIEWPORT_ORTHO_CAMERA_OK')

# Panning a zoomed camera frame changes only the projection's off-axis terms.
camera_view = SimpleNamespace(view_matrix=Matrix.Identity(4),
                              window_matrix=Matrix(((2, 0, 0, 0), (0, 2, 0, 0),
                                                    (0, 0, -1, -0.2), (0, 0, -1, 0))),
                              view_perspective='CAMERA', view_camera_zoom=30.0)
before = viewport._camera_key(camera_view, 1200, 800, 1.0)
assert before == viewport._camera_key(camera_view, 1200, 800, 1.0)
camera_view.window_matrix[0][2] = 0.4
assert before != viewport._camera_key(camera_view, 1200, 800, 1.0)
after_pan = viewport._camera_key(camera_view, 1200, 800, 1.0)
camera_view.window_matrix[1][2] = -0.3
assert after_pan != viewport._camera_key(camera_view, 1200, 800, 1.0)
print('SMASH_VIEWPORT_CAMERA_PAN_OK')
