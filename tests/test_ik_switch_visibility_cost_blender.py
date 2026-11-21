from pathlib import Path
from unittest.mock import patch
from collections import Counter

fixture = Path(__file__).with_name('test_ik_visibility_between_switches_blender.py')
exec(compile(fixture.read_text(), str(fixture), 'exec'))
obj.data.sub_hide_ik_foot_toe = True
scene.frame_set(43)
writes = []
original = rig.set_pose_bone_hidden

def record(bone, hidden=True):
    if bone is not None:
        writes.append(bone.name)
    original(bone, hidden)

with patch.object(ik, 'chains', wraps=ik.chains) as scans:
    with patch.object(rig, 'set_pose_bone_hidden', side_effect=record):
        rig._set_ik_bone_visibility(obj, True, 'LEGS')
    assert scans.call_count == 1, scans.call_count
assert max(Counter(writes).values()) == 1, writes
for side in ('L', 'R'):
    assert rig.is_pose_bone_hidden(obj.pose.bones['Foot' + side])
    assert not rig.is_pose_bone_hidden(obj.pose.bones['FootIK' + side])
with patch.object(rig, '_set_ik_bone_visibility', wraps=rig._set_ik_bone_visibility) as updates:
    scene.frame_set(44)
    scene.frame_set(45)
    assert updates.call_count == 0, updates.call_count
print('SWITCH USES ONE CHAIN SCAN, ONE WRITE PER BONE, AND NO STEADY-FRAME VISIBILITY UPDATES PASSED')
