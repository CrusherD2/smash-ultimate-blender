"""The Retargeting panel follows the map > bind > check > bake steps and keeps every control."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
retarget = importlib.import_module(MODULE + '.source.retargeting')
mapping_ui = importlib.import_module(MODULE + '.source.retargeting.mapping_ui')
preset_handler = importlib.import_module(MODULE + '.expy_kit.preset_handler')
Path(preset_handler.get_retarget_dir()).mkdir(parents=True, exist_ok=True)


class Recorder:
    def __init__(self, log):
        object.__setattr__(self, 'log', log)

    def __setattr__(self, key, value):
        self.log.append(('set', key, value))

    def panel(self, identifier, **kwargs):
        self.log.append(('panel', identifier))
        return Recorder(self.log), Recorder(self.log)

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.log.append((method, args, kwargs))
            return Recorder(self.log)
        return call


def draw(draw_fn, *args):
    log = []
    draw_fn(Recorder(log), *args)
    return log


def operators_drawn(log):
    """[(idname, text, {prop: value})] in draw order."""
    found = []
    for entry in log:
        if entry[0] == 'operator':
            found.append((entry[1][0], entry[2].get('text'), {}))
        elif entry[0] == 'set' and found and entry[1] not in {'alert', 'alignment', 'scale_y', 'operator_context',
                                                             'use_property_split', 'use_property_decorate', 'enabled'}:
            found[-1][2][entry[1]] = entry[2]
    return found


def props_drawn(log):
    return {entry[1][1] for entry in log if entry[0] in {'prop', 'prop_search'}}


def labels(log):
    return [entry[2].get('text', '') for entry in log if entry[0] == 'label']


def make_armature(name, bones):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    for i, bone_name in enumerate(bones):
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = (0, 0, i), (0, 0, i + 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


scene = bpy.context.scene
assert not scene.sub_retarget_guided_open
scene.sub_retarget_guided_open = True
driver = make_armature('mixamo', ['Hips', 'Head', 'RightArm', 'LeftArm'])
receiver = make_armature('mario', ['Hip', 'Head', 'ArmR', 'ArmL'])
for ob in bpy.context.selected_objects:
    ob.select_set(False)
receiver.select_set(True)
bpy.context.view_layer.objects.active = receiver
scene.expykit_bind_to = driver
scene.sub_retarget_apply_to = receiver


def main_panel_log():
    return draw(lambda layout: retarget.SUB_PT_retargeting_main.draw(SimpleNamespace(layout=layout), bpy.context))


# Steps appear in working order after both roles are explicitly assigned.
log = main_panel_log()
steps = [e[1] for e in log if e[0] == 'panel' and e[1].startswith('sub_retarget_step_')]
# Only the current step has the "current" id (and opens by itself); nothing is mapped yet.
assert steps == ['sub_retarget_step_ground_done', 'sub_retarget_step_align_done', 'sub_retarget_step_map_current',
                 'sub_retarget_step_bind_todo', 'sub_retarget_step_check_todo', 'sub_retarget_step_bake_todo'], steps
for step in retarget.STEP_INFO:
    assert retarget.STEP_INFO[step][0] in labels(log), ('every step explains itself', step)
ops = [op for op, _, _ in operators_drawn(log)]
assert ops[0] == 'sub.retarget_edit_armature', 'the Next card leads with mapping the first unmapped armature'
assert 'Map the bones' in labels(log)
for idname in ('object.ultimate_bind_armatures', 'armature.ultimate_bake_actions',
               'object.ultimate_map_bones_by_proximity', 'object.expy_kit_active_bone_help',
               'sub.retarget_edit_armature', 'object.expy_kit_set_to_active_bone',
               'object.expy_kit_settings_mirror', 'object.expy_kit_armature_clear'):
    assert idname in ops, (idname, sorted(set(ops)))
assert {'expykit_bind_to', 'sub_retarget_apply_to', 'expykit_nearest_bone_ref'} <= props_drawn(log)
assert 'Using the selected armature: mario' not in labels(log)
mapping = [e[1] for e in log if e[0] == 'panel' and e[1].startswith('sub_retarget_mapping_')]
assert mapping == ['sub_retarget_mapping_' + s for s in ('core', 'arms', 'legs', 'fingers', 'root', 'custom')], mapping

# Groundwork lists every armature, selected or not, and From/To buttons set and swap the roles.
mesh = bpy.data.objects.new('not_an_armature', bpy.data.meshes.new('m'))
scene.collection.objects.link(mesh)
extra = make_armature('zelda', ['Hip'])
role_buttons = [(props['name'], props['role'], text) for op, text, props in operators_drawn(draw(mapping_ui.draw_armature_list, bpy.context))
                if op == 'sub.retarget_set_role']
assert sorted({name for name, _, _ in role_buttons}) == ['mario', 'mixamo', 'zelda'], role_buttons
assert len(role_buttons) == 6
assert mapping_ui.poll_animation_from(scene, bpy.context.object), 'the selected armature can be Animation From'
assert bpy.ops.sub.retarget_set_role(name='zelda', role='TO') == {'FINISHED'}
assert scene.sub_retarget_apply_to == extra
assert bpy.ops.sub.retarget_set_role(name='zelda', role='FROM') == {'FINISHED'}
assert (scene.expykit_bind_to, scene.sub_retarget_apply_to) == (extra, driver), 'picking the other role swaps'
assert bpy.ops.sub.retarget_set_role(name='zelda', role='FROM') == {'FINISHED'}
assert scene.expykit_bind_to is None, 'clicking a pressed button clears it'
scene.expykit_bind_to, scene.sub_retarget_apply_to = driver, receiver
bpy.data.objects.remove(extra)
bpy.data.objects.remove(mesh)
for ob in bpy.context.selected_objects:
    ob.select_set(False)
receiver.select_set(True)
bpy.context.view_layer.objects.active = receiver

# Map by Proximity is a guess: the Map step isn't complete until the matches are confirmed.
ref = make_armature('mario_ref', ['Hip', 'Head', 'ArmR', 'ArmL'])
ref.data.expykit_retarget.spine.hips = 'Hip'
ref.data.expykit_retarget.spine.head = 'Head'
scene.expykit_nearest_bone_ref = ref
for ob in bpy.context.selected_objects:
    ob.select_set(False)
receiver.select_set(True)
bpy.context.view_layer.objects.active = receiver
driver.data.expykit_retarget.spine.hips = 'Hips'
scene.sub_retarget_aligned_pair = retarget.pair_key(driver, receiver)
assert bpy.ops.object.ultimate_map_bones_by_proximity() == {'FINISHED'}
assert receiver.data.expykit_retarget.has_settings() and receiver.data.sub_retarget_mapping_unverified
state, status = retarget.retarget_step_states(bpy.context, driver, receiver)['map']
assert (state, status) == ('current', 'verify'), (state, status)
title, _, button = retarget.next_step(bpy.context, driver, receiver)
assert button[0] == 'sub.retarget_verify_mapping', (title, button)
assert 'Mapped by proximity: verify it' in labels(draw(retarget.draw_verify_mapping, bpy.context))
assert bpy.ops.sub.retarget_verify_mapping() == {'FINISHED'}
assert not receiver.data.sub_retarget_mapping_unverified
assert retarget.retarget_step_states(bpy.context, driver, receiver)['map'][0] == 'done'
assert retarget.next_step(bpy.context, driver, receiver)[2][0] == 'object.ultimate_bind_armatures'
assert not labels(draw(retarget.draw_verify_mapping, bpy.context))
receiver.data.expykit_retarget.spine.hips = receiver.data.expykit_retarget.spine.head = ''
driver.data.expykit_retarget.spine.hips = ''
scene.expykit_nearest_bone_ref = None
scene.sub_retarget_aligned_pair = ''
bpy.data.objects.remove(ref)

# Mapped counts, twist bones and the empty-slot warning.
skeleton = receiver.data.expykit_retarget
assert mapping_ui.section_count(receiver.data, 'core') == (0, 5)
skeleton.spine.head = 'Head'
skeleton.right_arm.arm = 'ArmR'
assert mapping_ui.section_count(receiver.data, 'core') == (1, 5)
assert mapping_ui.section_count(receiver.data, 'arms') == (1, 8)
assert mapping_ui.section_count(receiver.data, 'fingers') == (0, 30)
assert mapping_ui.mapping_count(receiver.data) == (2, 5 + 8 + 8 + 2)
receiver.data.expykit_twist_on = True
assert mapping_ui.section_count(receiver.data, 'arms') == (1, 16)
receiver.data.expykit_twist_on = False

core_log = draw(mapping_ui.draw_core, receiver)
alerts = [e[2] for e in core_log if e[0] == 'set' and e[1] == 'alert']
assert alerts == [False, True, True, True, True], 'only the filled Head slot is not flagged'

# Copy buttons name the direction, and the eyedroppers point at the right slots.
arm_ops = operators_drawn(draw(mapping_ui.draw_limb, receiver, 'arm'))
mirrors = {text: props for op, text, props in arm_ops if op == 'object.expy_kit_settings_mirror'}
assert mirrors == {'Copy R \u2192 L': {'src_setting': 'right_arm', 'trg_setting': 'left_arm'},
                   'Copy L \u2192 R': {'src_setting': 'left_arm', 'trg_setting': 'right_arm'}}, mirrors
picks = [props for op, _, props in arm_ops if op == 'object.expy_kit_set_to_active_bone']
assert {'attr_name': 'left_arm', 'sub_attr_name': '', 'slot_name': 'hand'} in picks, picks
finger_ops = operators_drawn(draw(mapping_ui.draw_fingers, receiver))
finger_picks = [props for op, _, props in finger_ops if op == 'object.expy_kit_set_to_active_bone']
assert len(finger_picks) == 30
assert {'attr_name': 'right_fingers', 'sub_attr_name': 'pinky', 'slot_name': 'c'} in finger_picks

# Switching the edited armature remembers Apply To, and binding then uses it.
assert bpy.ops.sub.retarget_edit_armature(role='FROM') == {'FINISHED'}
assert bpy.context.view_layer.objects.active == driver
assert scene.sub_retarget_apply_to == receiver
assert mapping_ui.apply_to(bpy.context) == receiver
assert bpy.ops.object.ultimate_bind_armatures.poll(), 'Apply To counts even when the driver is active'
assert bpy.ops.sub.retarget_edit_armature(role='TO') == {'FINISHED'}
assert bpy.context.view_layer.objects.active == receiver

# Bind settings still offer every option, spread over the groups.
expected = {
    'expykit_src_preset', 'expykit_trg_preset', 'expykit_match_transform', 'expykit_match_object_transform',
    'expykit_fit_target_scale', 'expykit_adjust_location', 'expykit_loc_constraints', 'expykit_no_finger_loc',
    'expykit_bind_floating', 'expykit_rot_constraints', 'expykit_math_look_at', 'expykit_scale_constraints',
    'expykit_copy_IK_roll_hands', 'expykit_copy_IK_roll_feet', 'expykit_constraint_policy',
    'expykit_only_selected', 'expykit_bind_by_name', 'expykit_name_prefix', 'expykit_name_replace',
    'expykit_name_replace_with', 'expykit_name_suffix', 'expykit_constrain_root', 'expykit_root_motion_bone',
    'expykit_root_copy_scale', 'expykit_ret_bones_collection',
} | {f'expykit_root_{kind}_{axis}' for axis in 'xyz'
     for kind in ('cp_loc', 'cp_rot', 'use_loc_min', 'loc_min', 'use_loc_max', 'loc_max')}
seen = set()
for loc, fit, by_name in ((True, 'hips', True), (False, '--', False)):
    scene.expykit_loc_constraints = loc
    scene.expykit_fit_target_scale = fit
    scene.expykit_bind_by_name = by_name
    scene.expykit_constrain_root = 'Bone'
    for axis in 'xyz':
        setattr(scene, f'expykit_root_cp_loc_{axis}', True)
    seen |= props_drawn(draw(retarget.draw_binded_settings_ui, bpy.context))
assert seen == expected, (expected - seen, seen - expected)

# One Tools panel holds every former Actions button.
tool_ops = [op for op, _, _ in operators_drawn(draw(
    lambda layout: retarget.ULTIMATE_PT_ActionsPanel.draw(SimpleNamespace(layout=layout), bpy.context)))]
for idname in ('armature.expykit_constrain_to_armature', 'object.expykit_set_constraints_status',
               'armature.expykit_select_constrained_ctrls', 'armature.expykit_convert_gamefriendly',
               'object.expykit_dot_bone_names', 'object.expykit_convert_bone_names',
               'object.expykit_extract_metarig', 'object.expykit_create_offset',
               'object.expykit_action_to_range', 'armature.expykit_rename_actions_fbx',
               'armature.expykit_add_rootmotion'):
    assert idname in tool_ops, (idname, tool_ops)
assert tool_ops.count('armature.expykit_select_constrained_ctrls') == 2
for retired in ('ULTIMATE_PT_ActionsBinding', 'ULTIMATE_PT_ActionsConversion', 'ULTIMATE_PT_ActionsAnimation'):
    assert not hasattr(bpy.types, retired), retired
# A narrow sidebar stacks Right then Left; the same slots and eyedroppers are drawn either way.
for limb in ('arm', 'leg'):
    wide = operators_drawn(draw(mapping_ui.draw_limb, receiver, limb, True))
    narrow_log = draw(mapping_ui.draw_limb, receiver, limb, False)
    narrow = operators_drawn(narrow_log)
    key = lambda ops: sorted((op, text, tuple(sorted(props.items()))) for op, text, props in ops)
    assert key(wide) == key(narrow), limb
    assert [t for t in labels(narrow_log) if t in {'Right', 'Left'}] == ['Right', 'Left']
wide_f = operators_drawn(draw(mapping_ui.draw_fingers, receiver, True))
narrow_f = operators_drawn(draw(mapping_ui.draw_fingers, receiver, False))
assert sorted(map(repr, wide_f)) == sorted(map(repr, narrow_f))
assert mapping_ui.wide_enough(SimpleNamespace(region=None))
print('RETARGET_PANEL_OK')

scene.sub_retarget_guided_open = False
closed_log = draw(retarget.draw_next_step, bpy.context, driver, receiver)
assert len([e for e in closed_log if e[0] == 'box']) == 1
assert not any(e[0] == 'panel' for e in closed_log)
assert 'sub_retarget_guided_open' in props_drawn(closed_log)
assert not operators_drawn(closed_log)
scene.sub_retarget_guided_open = True
open_log = draw(retarget.draw_next_step, bpy.context, driver, receiver)
assert len([e for e in open_log if e[0] == 'box']) == 1
assert labels(open_log)
print('RETARGET_GUIDANCE_CLOSED_OK')

check_log = draw(retarget.draw_check_controls, bpy.context, driver)
rows, current_row = {}, 0
for entry in check_log:
    if entry[0] == 'row':
        current_row += 1
    elif entry[0] == 'operator':
        rows[entry[1][0]] = current_row
assert rows['screen.animation_play'] != rows['sub.retarget_toggle_bind_preview']
assert rows['sub.retarget_source_meshes'] == rows['sub.retarget_toggle_bind_preview']
print('RETARGET_CHECK_LAYOUT_OK')

# Neither role is inferred from selection; both must be explicitly assigned.
scene.expykit_bind_to = None
scene.sub_retarget_apply_to = None
bpy.context.view_layer.objects.active = receiver
assert mapping_ui.animation_from(scene) is None
assert mapping_ui.apply_to(bpy.context) is None
empty_log = draw(mapping_ui.draw_armature_list, bpy.context)
assert all(not e[2].get('depress', False) for e in empty_log if e[0] == 'operator')
assert bpy.ops.sub.retarget_set_role(name=driver.name, role='FROM') == {'FINISHED'}
assert mapping_ui.apply_to(bpy.context) is None
assert retarget.retarget_step_states(bpy.context, driver, receiver)['ground'] == ('current', 'pick armatures')
assert bpy.ops.sub.retarget_set_role(name=receiver.name, role='TO') == {'FINISHED'}
assert retarget.retarget_step_states(bpy.context, driver, receiver)['ground'] == ('done', 'set')
assert bpy.ops.sub.retarget_set_role(name=receiver.name, role='TO') == {'FINISHED'}
assert retarget.retarget_step_states(bpy.context, driver, receiver)['ground'][0] == 'current'
print('RETARGET_GROUNDWORK_SELECTION_OK')
