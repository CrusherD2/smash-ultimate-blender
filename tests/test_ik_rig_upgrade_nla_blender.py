"""Update IK Rig on a rig with NLA strips: refused by default, removes them when asked, backup keeps them.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_rig_upgrade_nla_blender.py
"""
from pathlib import Path

fixture = Path(__file__).with_name('test_ik_stored_channels_blender.py')
source = fixture.read_text()
exec(compile(source.split('# New rigs:')[0], str(fixture), 'exec'))

old = build('NlaRig')
fk = matrices(old, watch)
ik.create_controls(bpy.context, old, 'ARMS')
rig._set_ik_enabled(bpy.context, old, True, limbs='ARMS')
ik.match(bpy.context, old, 'ARMS', entire=True, key=True)
old.data[upgrade.REVISION_KEY] = 3
# A muted strip leaves the pose alone, so removing it must not change anything.
layer_action = bpy.data.actions.new('Layer')
track = old.animation_data.nla_tracks.new()
track.name = 'Layer Track'
strip = track.strips.new('Layer', 1, layer_action)
strip.mute = True
before = matrices(old, watch)
assert upgrade.needs_update(old) and upgrade.has_nla_strips(old)

try:
    upgrade.update_in_place(bpy.context, old)
except RuntimeError as error:
    assert 'Remove NLA Strips' in str(error)
else:
    raise AssertionError('NLA strips were removed without asking')
assert upgrade.has_nla_strips(old) and upgrade.needs_update(old)

result = bpy.ops.sub.update_old_ik('EXEC_DEFAULT', rig_name=old.name, remove_nla=True)
assert result == {'FINISHED'}, result
assert not upgrade.has_nla_strips(old) and not upgrade.needs_update(old)
assert worst(old, before) < 1e-6
assert worst(old, fk) < 2e-4
backup = bpy.data.objects[old[upgrade.BACKUP_KEY]]
kept = [s.action for t in backup.animation_data.nla_tracks for s in t.strips]
assert kept == [layer_action], kept

# Strips that animate the rig (here the hip, which IK does not drive) cannot be dropped without changing it, so the update is undone.
bpy.data.objects.remove(backup)
loud = build('LoudRig')
ik.create_controls(bpy.context, loud, 'ARMS')
rig._set_ik_enabled(bpy.context, loud, True, limbs='ARMS')
ik.match(bpy.context, loud, 'ARMS', entire=True, key=True)
loud.data[upgrade.REVISION_KEY] = 3
anim = loud.animation_data
base, base_slot = anim.action, anim.action_slot
layer = bpy.data.actions.new('Loud Layer')
anim.action = layer
hip = loud.pose.bones['Hip']
hip.rotation_mode = 'XYZ'
# Two different keys: a bone left unkeyed keeps its last value, which only matches on one frame.
for frame, angle in ((1, 0.9), (20, -0.6)):
    hip.rotation_euler = (0.0, angle, 0.0)
    hip.keyframe_insert('rotation_euler', frame=frame)
hip.rotation_euler = (0.0, 0.0, 0.0)
anim.action, anim.action_slot = base, base_slot
anim.nla_tracks.new().strips.new('Loud', 1, layer).blend_type = 'ADD'
before = matrices(loud, watch + ['Hip'])
assert abs(before[1]['Hip'].to_euler().y) > 0.5 or abs(before[1]['Hip'].to_euler().z) > 0.5
try:
    bpy.ops.sub.update_old_ik('EXEC_DEFAULT', rig_name=loud.name, remove_nla=True)
except RuntimeError as error:
    assert 'NLA strips animate the rig' in str(error), error
else:
    raise AssertionError('removing animating strips was allowed')
loud = bpy.data.objects['LoudRig']
assert upgrade.has_nla_strips(loud) and upgrade.needs_update(loud)
assert worst(loud, before) < 1e-6
assert not [o.name for o in bpy.data.objects if o.name.endswith(upgrade.BACKUP_SUFFIX)]
print('IK RIG UPGRADE NLA PASSED')
