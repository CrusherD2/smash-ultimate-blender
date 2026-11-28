"""Bind runs from the panel's settings (no popup) and Match Source Pose lines the rigs up."""
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
retarget = importlib.import_module(MODULE + '.source.retargeting')
guided = importlib.import_module(MODULE + '.source.retargeting.guided')
pose_match = importlib.import_module(MODULE + '.source.retargeting.pose_match')
preset_handler = importlib.import_module(MODULE + '.expy_kit.preset_handler')
Path(preset_handler.get_retarget_dir()).mkdir(parents=True, exist_ok=True)

scene = bpy.context.scene


def make_rig(name, arm_dir):
    """Spine straight up; right arm from the chest along arm_dir."""
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    bones, parent = {}, None
    for i, bone_name in enumerate(('hips', 'spine1', 'spine2', 'neck', 'head')):
        bone = data.edit_bones.new(f'{name}_{bone_name}')
        bone.head, bone.tail = (0, 0, i), (0, 0, i + 1)
        bone.parent = parent
        bones[bone_name] = parent = bone
    parent, start = bones['spine2'], (0.0, 0.0, 2.5)
    for i, bone_name in enumerate(('shoulder', 'arm', 'forearm', 'hand')):
        bone = data.edit_bones.new(f'{name}_{bone_name}')
        bone.head = [start[k] + arm_dir[k] * i for k in range(3)]
        bone.tail = [start[k] + arm_dir[k] * (i + 1) for k in range(3)]
        bone.parent = parent
        bones[bone_name] = parent = bone
    bpy.ops.object.mode_set(mode='OBJECT')
    mapping = ob.data.expykit_retarget
    for slot, bone_name in (('hips', 'hips'), ('spine1', 'spine1'), ('spine2', 'spine2'), ('neck', 'neck'), ('head', 'head')):
        setattr(mapping.spine, slot, f'{name}_{bone_name}')
    for slot in ('shoulder', 'arm', 'forearm', 'hand'):
        setattr(mapping.right_arm, slot, f'{name}_{slot}')
    return ob


driver = make_rig('anim', (1.0, 0.0, 0.0))       # T-pose
receiver = make_rig('model', (0.0, 0.0, -1.0))   # arms down
receiver.location = (5, 0, 0)

# Choosing both armatures fills in the defaults the panel then shows.
scene.expykit_constrain_root = 'None'
bpy.context.view_layer.objects.active = receiver
scene.expykit_bind_to = driver
# Both roles must be explicitly assigned before defaults are applied.
assert scene.sub_retarget_apply_to is None
scene.sub_retarget_pair_defaults = ''
scene.sub_retarget_apply_to = receiver
assert scene.sub_retarget_pair_defaults == retarget.pair_key(driver, receiver)
assert scene.expykit_src_preset == '--Current--' and scene.expykit_trg_preset == '--Current--'
assert scene.expykit_constrain_root == 'Bone'

# Before binding, step 2 already shows the settings, and Re-apply only appears once bound.
log = []


class Recorder:
    def __getattr__(self, name):
        def call(*args, **kwargs):
            log.append((name, args, kwargs))
            return (Recorder(), Recorder()) if name == 'panel' else Recorder()
        return call

    def __setattr__(self, key, value):
        pass


retarget.draw_bind_controls(Recorder(), bpy.context)
assert ('panel', ('sub_retarget_bind_settings',), {'default_closed': False}) in log
drawn_ops = [e[1][0] for e in log if e[0] == 'operator']
assert 'sub.retarget_match_rest_pose' in drawn_ops and 'object.ultimate_bind_armatures' in drawn_ops
order = [e[1][0] for e in log if e[0] in {'operator', 'panel'}]
assert order.index('sub.retarget_match_rest_pose') < order.index('sub_retarget_bind_settings'), 'button sits above Bind Settings'
# The approximation warning is a confirm popup on the button, not a label in the panel.
assert not any(e[0] == 'label' and 'approximation' in str(e[2].get('text')) for e in log)
assert 'invoke' in pose_match.SUB_OT_retarget_match_rest_pose.__dict__

# The two rigs stand 5 m apart on purpose: Line Up flags it first, and keeping it lets the card move on.
assert retarget.next_step(bpy.context, driver, receiver)[2][0] == 'sub.retarget_line_up'
assert bpy.ops.sub.retarget_accept_alignment() == {'FINISHED'}

# Before binding, the opened Next card stacks Match above Bind.
scene.sub_retarget_guided_open = True
log.clear()
retarget.draw_next_step(Recorder(), bpy.context, driver, receiver)
card_ops = [e[1][0] for e in log if e[0] == 'operator']
assert card_ops == ['sub.retarget_match_rest_pose', 'object.ultimate_bind_armatures'], card_ops
assert not any(e[0] == 'row' and e[2].get('align') for e in log), 'buttons are stacked, not in an aligned row'
labels = {item.identifier: item.name for item in bpy.types.Scene.bl_rna.properties['expykit_match_transform'].enum_items}
assert labels['Pose'] == 'Current Pose is Source Rest Pose', labels
assert 'object.ultimate_apply_bind_settings' not in drawn_ops

# Match Source Pose: the receiver's arm now points along the driver's rest arm.
def world_dir(ob, a, b, posed):
    if posed:
        return ((ob.matrix_world @ ob.pose.bones[b].head) - (ob.matrix_world @ ob.pose.bones[a].head)).normalized()
    return ((ob.matrix_world @ ob.data.bones[b].head_local) - (ob.matrix_world @ ob.data.bones[a].head_local)).normalized()


assert world_dir(receiver, 'model_arm', 'model_forearm', True).dot(world_dir(driver, 'anim_arm', 'anim_forearm', False)) < 0.1
# The source's current (animated) pose and Rest Position display must not change the result: only its rest pose counts.
driver.pose.bones['anim_arm'].rotation_mode = 'XYZ'
driver.pose.bones['anim_arm'].rotation_euler = (0.0, 1.2, 0.0)
driver.data.pose_position = 'REST'
receiver.data.pose_position = 'REST'
locations = {pb.name: pb.location.copy() for pb in receiver.pose.bones}
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
assert driver.data.pose_position == 'REST', "Match leaves the source's display alone"
assert receiver.data.pose_position == 'POSE', 'the posed armature is switched so its new pose shows'
assert all((pb.location - locations[pb.name]).length < 1e-6 for pb in receiver.pose.bones), 'FK bones only rotate'
driver.pose.bones['anim_arm'].rotation_euler = (0.0, 0.0, 0.0)
assert scene.expykit_match_transform == 'Pose'
for a, b in (('shoulder', 'arm'), ('arm', 'forearm'), ('forearm', 'hand'), ('spine1', 'spine2')):
    dot = world_dir(receiver, f'model_{a}', f'model_{b}', True).dot(world_dir(driver, f'anim_{a}', f'anim_{b}', False))
    assert dot > 0.999, (a, b, dot)
assert receiver.pose.bones['model_hips'].matrix_basis.to_translation().length < 1e-6, 'only rotations change'

# Bind uses the panel settings straight away: constraints appear without a dialog.
# Rest Position would drop the helpers' pose scale, so Bind switches the animation rig back.
driver.data.pose_position = 'REST'
result = bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT')
assert result == {'FINISHED'}, result
assert driver.data.pose_position == 'POSE'
assert guided.bound_pair(scene) == (receiver, driver)
constrained = [pb.name for pb in receiver.pose.bones if any(c.type == 'COPY_ROTATION' for c in pb.constraints)]
assert 'model_arm' in constrained, constrained

log.clear()
retarget.draw_bind_controls(Recorder(), bpy.context)
drawn_ops = [e[1][0] for e in log if e[0] == 'operator']
assert 'object.ultimate_apply_bind_settings' in drawn_ops
assert 'object.ultimate_unbind_armatures' in drawn_ops and 'object.ultimate_bind_armatures' not in drawn_ops, drawn_ops

# Unbind removes the bind and brings the Bind button back.
assert bpy.ops.object.ultimate_unbind_armatures() == {'FINISHED'}
assert not scene.expykit_bind_is_active
assert not any(c.type.startswith('COPY') and c.target == driver for pb in receiver.pose.bones for c in pb.constraints)
assert not bpy.ops.object.ultimate_unbind_armatures.poll()
log.clear()
retarget.draw_bind_controls(Recorder(), bpy.context)
drawn_ops = [e[1][0] for e in log if e[0] == 'operator']
assert 'object.ultimate_bind_armatures' in drawn_ops and 'object.ultimate_unbind_armatures' not in drawn_ops, drawn_ops
assert bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT') == {'FINISHED'}

# A missing preset stops the bind with a message instead of silently doing nothing.
scene.expykit_src_preset = '--'
receiver.data.expykit_retarget.spine.hips = ''
saved = {}
mapping = receiver.data.expykit_retarget
for group in (mapping.spine, mapping.right_arm):
    for key in list(group.keys()):
        if key != 'name' and group.get(key):
            saved[(group, key)] = group[key]
            group[key] = ''
assert not mapping.has_settings()
try:
    bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT')
except RuntimeError as error:
    assert 'From Preset' in str(error), error
else:
    raise AssertionError('binding without presets should report an error')

# The Next card reads the scene: bound -> check and bake, Show Original -> turn the bind back on, baked -> done.
for group, key in saved:
    group[key] = saved[(group, key)]
scene.expykit_src_preset = '--Current--'
assert bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT') == {'FINISHED'}
title, _, button = retarget.next_step(bpy.context, driver, receiver)
assert title == 'Check, then bake' and button[0] == 'armature.ultimate_bake_actions', (title, button)
assert retarget.retarget_step_states(bpy.context, driver, receiver)['check'][0] == 'current'
assert not guided.bind_preview_off(scene)
assert bpy.ops.sub.retarget_toggle_bind_preview() == {'FINISHED'}
assert guided.bind_preview_off(scene) and receiver.hide_get()
assert not any(c.mute for c in guided.bind_constraints(receiver, driver))
assert not driver.hide_get()
title, _, button = retarget.next_step(bpy.context, driver, receiver)
assert button[0] == 'sub.retarget_toggle_bind_preview', (title, button)
assert bpy.ops.sub.retarget_toggle_bind_preview() == {'FINISHED'}
assert not any(c.mute for c in guided.bind_constraints(receiver, driver))
assert bpy.ops.object.ultimate_unbind_armatures() == {'FINISHED'}
title, _, button = retarget.next_step(bpy.context, driver, receiver)
assert button[0] == 'object.ultimate_bind_armatures', (title, button)
assert retarget.retarget_step_states(bpy.context, driver, receiver)['bake'][0] == 'todo'
scene.expykit_guided_phase = 'DONE'
assert retarget.next_step(bpy.context, driver, receiver)[0] == 'Done'
assert retarget.retarget_step_states(bpy.context, driver, receiver)['bake'] == ('done', 'baked')
scene.expykit_guided_phase = 'IDLE'
assert not hasattr(bpy.types, 'OBJECT_OT_ultimate_guided_mode'), 'the popup wizard is gone'
print('RETARGET_BIND_POSE_OK')


# Smash-style IK limbs: the mapping points at IK controls (HandIK / ArmIK pole), not at a parented FK chain.
def make_ik_rig(name):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(n, head, tail, parent=None):
        b = data.edit_bones.new(n)
        b.head, b.tail, b.parent = head, tail, parent
        return b
    hip = bone('Hip', (0, 0, 0), (0, 0, 1))
    waist = bone('Waist', (0, 0, 1), (0, 0, 2), hip)
    bust = bone('Bust', (0, 0, 2), (0, 0, 3), waist)
    clav = bone('ClavicleR', (0, 0, 2.5), (-0.5, 0, 2.5), bust)
    shoulder = bone('ShoulderR', (-0.5, 0, 2.5), (-0.5, 0, 1.5), clav)     # arms hang down
    arm = bone('ArmR', (-0.5, 0, 1.5), (-0.5, 0.05, 0.5), shoulder)
    bone('HandR', (-0.5, 0.05, 0.5), (-0.5, 0.05, 0.2), arm)
    bone('HandIKR', (-0.5, 0.05, 0.5), (-0.5, 0.05, 0.2))
    bone('ArmIKR', (-0.5, 1.5, 1.5), (-0.5, 1.5, 1.2))
    bpy.ops.object.mode_set(mode='OBJECT')
    ik = ob.pose.bones['ArmR'].constraints.new('IK')
    ik.target, ik.subtarget, ik.pole_target, ik.pole_subtarget = ob, 'HandIKR', ob, 'ArmIKR'
    ik.chain_count, ik.pole_angle = 2, -pi / 2
    rot = ob.pose.bones['HandR'].constraints.new('COPY_ROTATION')
    rot.target, rot.subtarget = ob, 'HandIKR'
    m = ob.data.expykit_retarget
    m.spine.hips, m.spine.spine1, m.spine.spine2 = 'Hip', 'Waist', 'Bust'
    m.right_arm.shoulder, m.right_arm.forearm, m.right_arm.hand = 'ClavicleR', 'ArmIKR', 'HandIKR'
    return ob


from math import pi
smash = make_ik_rig('SmashLike')
tpose = make_rig('tpose', (1.0, 0.0, 0.0))
for ob in bpy.context.selected_objects:
    ob.select_set(False)
smash.select_set(True)
bpy.context.view_layer.objects.active = smash
scene.expykit_bind_is_active = False
scene.expykit_bind_to = tpose
scene.sub_retarget_apply_to = smash
assert len(pose_match.ik_limbs(smash, tpose)) == 1, 'the IK arm is found through its controls'
tpose.data.pose_position = 'REST'
ik_controls = {'HandIKR', 'ArmIKR'}
locations = {pb.name: pb.location.copy() for pb in smash.pose.bones}
bpy.context.view_layer.update()
assert world_dir(smash, 'ShoulderR', 'ArmR', True).x < 0.1, 'arm starts hanging down'
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
assert tpose.data.pose_position == 'REST', "Match leaves the source's display alone"
moved = {pb.name for pb in smash.pose.bones if (pb.location - locations[pb.name]).length > 1e-6}
assert moved <= ik_controls, ('only IK controls may move', moved)
bpy.context.view_layer.update()
for (a, b), (da, db) in ((('ShoulderR', 'ArmR'), ('tpose_arm', 'tpose_forearm')),
                         (('ArmR', 'HandR'), ('tpose_forearm', 'tpose_hand')),
                         (('ClavicleR', 'ShoulderR'), ('tpose_shoulder', 'tpose_arm'))):
    dot = world_dir(smash, a, b, True).dot(world_dir(tpose, da, db, False))
    assert dot > 0.995, ('IK arm should follow the T-pose', a, b, dot)
hand_bone, want_bone = smash.pose.bones['HandR'], tpose.data.bones['tpose_hand']
hand = (smash.matrix_world.to_3x3() @ (hand_bone.tail - hand_bone.head)).normalized()
want = (tpose.matrix_world.to_3x3() @ (want_bone.tail_local - want_bone.head_local)).normalized()
assert hand.dot(want) > 0.995, ('hand should face like the T-pose hand', hand, want)

# A second match finds nothing left to change.
assert pose_match.match_rest_pose(smash, tpose, bpy.context.view_layer) == 0, 'already lined up'
assert not any(c.type.startswith('COPY') and c.target == tpose for pb in smash.pose.bones for c in pb.constraints),     'Match never binds'
print('RETARGET_IK_MATCH_OK')


# Hands match fully: IK hands sit on the source hand and the palm faces the same way, not just points the same way.
def add_fingers(ob, hand, middle, index, pinky, side='right'):
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    eb = ob.data.edit_bones
    for finger, head in (('middle', middle), ('index', index), ('pinky', pinky)):
        bone = eb.new(f'{ob.name}_{finger}')
        bone.head = head
        bone.tail = [head[k] + (head[k] - eb[hand].head[k]) * 0.5 for k in range(3)]
        bone.parent = eb[hand]
    bpy.ops.object.mode_set(mode='OBJECT')
    fingers = getattr(ob.data.expykit_retarget, f'{side}_fingers')
    for finger in ('middle', 'index', 'pinky'):
        getattr(fingers, finger).a = f'{ob.name}_{finger}'


def palm(ob, hand, posed):
    if posed:
        point = lambda n: ob.matrix_world @ ob.pose.bones[n].head
    else:
        point = lambda n: ob.matrix_world @ ob.data.bones[n].head_local
    frame = pose_match.palm_frame(point(hand), *(point(f'{ob.name}_{f}') for f in ('middle', 'index', 'pinky')))
    return point(hand), frame


def make_ik_source(name):
    """Arm out to -X (reachable by the SmashLike arm), palm facing so index-to-pinky runs along Z."""
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(n, head, tail, parent=None):
        b = data.edit_bones.new(f'{name}_{n}')
        b.head, b.tail, b.parent = head, tail, parent
        return b
    hip = bone('hips', (0, 0, 0), (0, 0, 1))
    waist = bone('spine1', (0, 0, 1), (0, 0, 2), hip)
    bust = bone('spine2', (0, 0, 2), (0, 0, 3), waist)
    clav = bone('shoulder', (0, 0, 2.5), (-0.5, 0, 2.5), bust)
    upper = bone('arm', (-0.5, 0, 2.5), (-1.5, 0, 2.5), clav)
    fore = bone('forearm', (-1.5, 0, 2.5), (-2.45, 0.3, 2.5), upper)
    bone('hand', (-2.45, 0.3, 2.5), (-2.75, 0.3, 2.5), fore)
    bpy.ops.object.mode_set(mode='OBJECT')
    m = ob.data.expykit_retarget
    m.spine.hips, m.spine.spine1, m.spine.spine2 = f'{name}_hips', f'{name}_spine1', f'{name}_spine2'
    for slot in ('shoulder', 'arm', 'forearm', 'hand'):
        setattr(m.right_arm, slot, f'{name}_{slot}')
    return ob


source = make_ik_source('src')
add_fingers(source, 'src_hand', (-2.85, 0.3, 2.5), (-2.75, 0.3, 2.6), (-2.75, 0.3, 2.4))
ik_model = make_ik_rig('IKModel')
# Hand points down with index-to-pinky along X: lining up forward alone would leave the palm 90 degrees off.
add_fingers(ik_model, 'HandR', (-0.5, 0.05, 0.1), (-0.4, 0.05, 0.2), (-0.6, 0.05, 0.2))
for ob in bpy.context.selected_objects:
    ob.select_set(False)
ik_model.select_set(True)
bpy.context.view_layer.objects.active = ik_model
scene.expykit_bind_to = source
scene.sub_retarget_apply_to = ik_model
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
bpy.context.view_layer.update()
got_head, got = palm(ik_model, 'HandR', True)
want_head, want = palm(source, 'src_hand', False)
assert (got_head - want_head).length < 1e-3, ('IK hand should sit on the source hand', got_head, want_head)
for axis, label in ((0, 'pointing'), (1, 'palm facing')):
    dot = got.col[axis].dot(want.col[axis])
    assert dot > 0.995, (f'IK hand {label} should match the source', dot)
assert pose_match.match_rest_pose(ik_model, source, bpy.context.view_layer) == 0, 'already lined up'

# FK hand (no IK controls): same palm match, by rotation only.
fk_model = make_rig('fk', (0.0, 0.0, -1.0))
add_fingers(fk_model, 'fk_hand', (0.0, 0.0, -1.9), (0.1, 0.0, -1.8), (-0.1, 0.0, -1.8))
fk_source = make_rig('fksrc', (1.0, 0.0, 0.0))
add_fingers(fk_source, 'fksrc_hand', (4.4, 0.0, 2.5), (4.3, 0.0, 2.6), (4.3, 0.0, 2.4))
for ob in bpy.context.selected_objects:
    ob.select_set(False)
fk_model.select_set(True)
bpy.context.view_layer.objects.active = fk_model
scene.expykit_bind_to = fk_source
scene.sub_retarget_apply_to = fk_model
locations = {pb.name: pb.location.copy() for pb in fk_model.pose.bones}
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
bpy.context.view_layer.update()
_, got = palm(fk_model, 'fk_hand', True)
_, want = palm(fk_source, 'fksrc_hand', False)
assert got.col[0].dot(want.col[0]) > 0.995 and got.col[1].dot(want.col[1]) > 0.995, (got, want)
assert all((pb.location - locations[pb.name]).length < 1e-6 for pb in fk_model.pose.bones), 'FK hands only rotate'
poser = pose_match._Poser(fk_model, fk_source, bpy.context.view_layer, True)
assert poser.driver_palm('fksrc_hand', []) is None and poser.receiver_palm('fk_hand', []) is None, 'feet have no palm'
print('RETARGET_HAND_MATCH_OK')


# IK legs (Smash-style FootIK / KneeIK / ToeIK under FootIK): the foot sits on the source foot with the same
# rotation, the toe matches too, and whatever the model's current frame had (foot roll, toe bend) doesn't leak in.
from mathutils import Euler, Vector


def make_ik_leg_model(name):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(n, head, tail, parent=None):
        b = data.edit_bones.new(n)
        b.head, b.tail, b.parent = head, tail, parent
        return b
    hip = bone('Hip', (0, 0, 2), (0, 0, 2.5))
    leg = bone('LegR', (-0.3, 0, 2), (-0.3, 0.05, 1), hip)
    knee = bone('KneeR', (-0.3, 0.05, 1), (-0.3, 0, 0.1), leg)
    foot = bone('FootR', (-0.3, 0, 0.1), (-0.3, -0.3, 0.02), knee)
    bone('ToeR', (-0.3, -0.3, 0.02), (-0.3, -0.45, 0.02), foot)
    foot_ik = bone('FootIKR', (-0.3, 0, 0.1), (-0.3, -0.3, 0.02))
    bone('ToeIKR', (-0.3, -0.3, 0.02), (-0.3, -0.45, 0.02), foot_ik)
    bone('KneeIKR', (-0.3, -1.0, 1), (-0.3, -1.0, 0.8))
    bpy.ops.object.mode_set(mode='OBJECT')
    ik = ob.pose.bones['KneeR'].constraints.new('IK')
    ik.target, ik.subtarget, ik.pole_target, ik.pole_subtarget = ob, 'FootIKR', ob, 'KneeIKR'
    ik.chain_count = 2
    for owner, target in (('FootR', 'FootIKR'), ('ToeR', 'ToeIKR')):
        c = ob.pose.bones[owner].constraints.new('COPY_ROTATION')
        c.target, c.subtarget = ob, target
    m = ob.data.expykit_retarget
    m.spine.hips = 'Hip'
    m.right_leg.leg, m.right_leg.foot, m.right_leg.toe = 'KneeIKR', 'FootIKR', 'ToeIKR'
    return ob


def make_leg_source(name):
    """Longer legs than the model, foot turned out and pointing down-forward, toe angled."""
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(n, head, tail, parent=None):
        b = data.edit_bones.new(f'{name}_{n}')
        b.head, b.tail, b.parent = head, tail, parent
        return b
    hip = bone('hips', (0, 0, 2), (0, 0, 2.5))
    up = bone('upleg', (-0.3, 0, 2), (-0.35, -0.1, 1.05), hip)
    low = bone('leg', (-0.35, -0.1, 1.05), (-0.4, 0.05, 0.12), up)
    foot = bone('foot', (-0.4, 0.05, 0.12), (-0.5, -0.22, 0.03), low)
    toe = bone('toe', (-0.5, -0.22, 0.03), (-0.56, -0.36, 0.0), foot)
    bone('toe_end', (-0.56, -0.36, 0.0), (-0.6, -0.45, 0.0), toe)
    bpy.ops.object.mode_set(mode='OBJECT')
    m = ob.data.expykit_retarget
    m.spine.hips = f'{name}_hips'
    for slot in ('upleg', 'leg', 'foot', 'toe'):
        setattr(m.right_leg, slot, f'{name}_{slot}')
    return ob


leg_model = make_ik_leg_model('LegModel')
leg_source = make_leg_source('legsrc')
# The model is on some animated frame: foot rolled sideways, toe curled.
for name, euler in (('FootIKR', (0.0, 0.5, 0.3)), ('ToeIKR', (0.6, 0.0, 0.0))):
    leg_model.pose.bones[name].rotation_mode = 'XYZ'
    leg_model.pose.bones[name].rotation_euler = euler
for ob in bpy.context.selected_objects:
    ob.select_set(False)
leg_model.select_set(True)
bpy.context.view_layer.objects.active = leg_model
scene.expykit_bind_to = leg_source
scene.sub_retarget_apply_to = leg_model
limbs = pose_match.ik_limbs(leg_model, leg_source)
assert [(l['effector'], l['pole'], l['toe_control'], l['toe']) for l in limbs] == [('FootIKR', 'KneeIKR', 'ToeIKR', 'ToeR')], limbs
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
bpy.context.view_layer.update()

mw, smw = leg_model.matrix_world, leg_source.matrix_world
up = Vector((0, 0, 1))
src = lambda n: smw @ leg_source.data.bones[f'legsrc_{n}'].head_local
rest = lambda n: mw @ leg_model.data.bones[n].head_local


def expected(bone, rest_ahead, source_head, source_ahead):
    frame_rest = pose_match.heading_frame(rest(bone), rest_ahead, up)
    frame_src = pose_match.heading_frame(source_head, source_ahead, up)
    return frame_src @ frame_rest.transposed() @ (mw.to_3x3() @ leg_model.data.bones[bone].matrix_local.to_3x3()).normalized()


def rotation_error(bone, want):
    got = (mw.to_3x3() @ leg_model.pose.bones[bone].matrix.to_3x3()).normalized()
    return got.to_quaternion().rotation_difference(want.to_quaternion()).angle


foot_head = mw @ leg_model.pose.bones['FootR'].head
assert (foot_head - src('foot')).length < 0.01, ('foot sits on the source foot', foot_head, src('foot'))
rest_heading = rest('ToeR') - rest('FootR')
source_heading = src('toe') - src('foot')
rest_heading.z = source_heading.z = 0
assert rotation_error('FootR', expected('FootR', rest('FootR') + rest_heading,
                                      src('foot'), src('foot') + source_heading)) < 0.01, 'level IK foot rotation incl. roll'
toe_tip = mw @ leg_model.data.bones['ToeR'].tail_local
assert rotation_error('ToeR', expected('ToeR', toe_tip, src('toe'), src('toe_end'))) < 0.01, 'toe rotation'
assert pose_match.match_rest_pose(leg_model, leg_source, bpy.context.view_layer) == 0, 'feet already lined up'
print('RETARGET_FOOT_MATCH_OK')

scene.expykit_bind_to = driver
driver.hide_set(False)
mesh = bpy.data.objects.new('source_mesh', bpy.data.meshes.new('source_mesh'))
scene.collection.objects.link(mesh)
mesh.parent = driver
assert bpy.ops.sub.retarget_source_meshes() == {'FINISHED'}
assert mesh.hide_get() and not driver.hide_get()
assert bpy.ops.sub.retarget_source_meshes() == {'FINISHED'}
assert not mesh.hide_get()
for name, end in [('motion_a', 12), ('motion_b', 27)]:
    driver.animation_data_create()
    driver.animation_data.action = bpy.data.actions.new(name)
    bone = driver.pose.bones[0]
    bone.keyframe_insert('location', frame=1)
    bone.keyframe_insert('location', frame=end)
assert bpy.ops.sub.retarget_action(action_name='motion_a') == {'FINISHED'}
assert scene.frame_end == 12
assert bpy.ops.sub.retarget_action(direction=1) == {'FINISHED'}
assert driver.animation_data.action.name == 'motion_b' and scene.frame_end == 27
assert bpy.ops.sub.retarget_action(direction=-1) == {'FINISHED'}
assert scene.frame_end == 12
print('RETARGET_MOTION_OK')

# FK feet with different ankle heights must retain level soles, not copy ankle-to-toe pitch.
fk_source = make_leg_source('fk_source')
fk_target = make_leg_source('fk_target')
bpy.context.view_layer.objects.active = fk_target
bpy.ops.object.mode_set(mode='EDIT')
foot = fk_target.data.edit_bones['fk_target_foot']
foot.head.z += 0.4
bpy.ops.object.mode_set(mode='OBJECT')
scene.expykit_bind_to = fk_source
scene.sub_retarget_apply_to = fk_target
fk_source.data.pose_position = 'POSE'
solid_views = [area.spaces.active for window in bpy.context.window_manager.windows
               for area in window.screen.areas if area.type == 'VIEW_3D']
assert solid_views
for space in solid_views:
    space.shading.type = 'SOLID'
    space.shading.show_xray = False
    space.shading.xray_alpha = 1.0
fk_target.pose.bones['fk_target_foot'].rotation_mode = 'XYZ'
fk_target.pose.bones['fk_target_foot'].rotation_euler.x = 0.5
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
assert fk_source.data.pose_position == 'REST'
bpy.context.view_layer.update()
bone = fk_target.pose.bones['fk_target_foot']
assert bone.matrix.to_quaternion().rotation_difference(bone.bone.matrix_local.to_quaternion()).angle < 0.001
assert pose_match.match_rest_pose(fk_target, fk_source, bpy.context.view_layer) == 0
print('RETARGET_FK_FEET_OK')

for space in solid_views:
    assert space.shading.type == 'SOLID'
    assert space.shading.show_xray
    assert abs(space.shading.xray_alpha - 0.7) < 1e-6
print('RETARGET_MATCH_OPACITY_OK')

assert scene.get('sub_retarget_confirm_mapping')
log.clear()
pose_match.draw_match_button(Recorder(), bpy.context)
assert [e[1][0] for e in log if e[0] == 'operator'] == ['sub.retarget_confirm_pose_mapping']
before_confirm = fk_target.pose.bones['fk_target_foot'].matrix.copy()
assert bpy.ops.sub.retarget_confirm_pose_mapping() == {'FINISHED'}
assert not scene.get('sub_retarget_confirm_mapping')
assert fk_target.pose.bones['fk_target_foot'].matrix == before_confirm
for space in solid_views:
    assert not space.shading.show_xray and space.shading.xray_alpha == 1.0
log.clear()
pose_match.draw_match_button(Recorder(), bpy.context)
assert [e[1][0] for e in log if e[0] == 'operator'] == ['sub.retarget_match_rest_pose']
print('RETARGET_CONFIRM_MAPPING_OK')
