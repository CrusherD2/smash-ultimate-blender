"""A rig saved by the old IK system (revision 1) updates to one-IK-per-limb without changing the animation.

The fixture was built with the previous release: legs and arms in IK, matched,
then the left foot and hand controls moved so the old IK, not FK, decides the pose.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_rig_upgrade_old_file_blender.py
"""
import importlib
import math
import shutil
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
ik = importlib.import_module(ROOT.name + '.source.extras.ik_channels')
upgrade = importlib.import_module(ROOT.name + '.source.extras.ik_rig_upgrade')

with tempfile.TemporaryDirectory() as folder:
    copy = Path(folder) / 'old_rig.blend'
    shutil.copyfile(Path(__file__).with_name('fixtures') / 'old_ik_rig_rev1.blend', copy)
    bpy.ops.wm.open_mainfile(filepath=str(copy), load_ui=False)
scene = bpy.context.scene
obj = bpy.data.objects['OldRig']
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
assert upgrade.needs_update(obj)
assert any(bone.name.startswith(ik.CORRECTION_PREFIX) for bone in obj.data.bones)
shown = sorted(bone.name for bone in obj.data.bones
               if not bone.name.startswith('BL_') and 'IK' not in bone.name)
frames = range(scene.frame_start, scene.frame_end + 1)


def snapshot():
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result[frame] = {name: obj.pose.bones[name].matrix.copy() for name in shown}
    return result


def limb_length(name):
    for _kind, names, _target, _pole in ik.chains(obj):
        path = ik.limb_path(obj, names)
        if name in path:
            return ik._chain_rest_length(obj, path)
    return None


before = snapshot()
scene.frame_set(1)
upgrade.update_in_place(bpy.context, obj)
obj = bpy.data.objects['OldRig']
assert not upgrade.needs_update(obj)
assert not any(bone.name.startswith(ik.CORRECTION_PREFIX) for bone in obj.data.bones)
for name in ('LegL', 'KneeL', 'FootL', 'ShoulderL', 'ArmL', 'HandL'):
    assert [con.name for con in obj.pose.bones[name].constraints if not con.mute] == [ik.OUTPUT], name
after = snapshot()
for frame, matrices in before.items():
    for name, wanted in matrices.items():
        actual = after[frame][name]
        moved = (actual.translation - wanted.translation).length
        angle = actual.to_quaternion().rotation_difference(wanted.to_quaternion()).angle
        angle = min(angle, 2 * math.pi - angle)
        length = limb_length(name)
        # Near-straight limbs may bend by the small fold-direction nudge; nothing else moves.
        limit, turn = (0.015 * length, math.radians(1.5)) if length else (2e-4, 1e-3)
        assert moved < limit and angle < turn, (frame, name, moved, math.degrees(angle))
print('OLD IK RIG FILE UPDATES WITHOUT CHANGING THE ANIMATION PASSED')
