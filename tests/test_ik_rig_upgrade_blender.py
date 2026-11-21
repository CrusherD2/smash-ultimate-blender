from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
upgrade = importlib.import_module(MODULE + '.source.extras.ik_rig_upgrade')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
assert not upgrade.needs_update(obj)
del obj.data[upgrade.REVISION_KEY]
assert upgrade.needs_update(obj) and upgrade.pending_rigs(scene) == [obj]
hip = obj.pose.bones['Hip']
hip.rotation_mode = 'XYZ'
for frame, angle in ((1, 0.0), (9, 0.2), (16, -0.1)):
    hip.rotation_euler.z = angle
    hip.keyframe_insert('rotation_euler', frame=frame)
rig._key_bool_prop(obj, 'sub_use_ik_legs', 10, old_value=True, new_value=False)
NAME = obj.name


def keys(action):
    return sorted((fc.data_path, fc.array_index, tuple((tuple(k.co), k.interpolation) for k in fc.keyframe_points))
                  for fc in compat.get_all_action_fcurves(action, id_type='OBJECT'))


def switch_keys(rig_obj):
    curves, _ = upgrade._switch_snapshot(rig_obj)
    return curves


def state(rig_obj):
    return (keys(rig_obj.animation_data.action), switch_keys(rig_obj), tuple(rig_obj.data.bones.keys()),
            {pb.name: [con.name for con in pb.constraints] for pb in rig_obj.pose.bones})


def poses(rig_obj):
    result = {}
    for frame in range(1, 17):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result[frame] = {name: rig_obj.pose.bones[name].matrix.copy() for name in ('Hip', 'H_Helper', *source[frame])}
    return result


def assert_poses(rig_obj, wanted, tolerance):
    for frame, matrices in poses(rig_obj).items():
        for name, matrix in matrices.items():
            assert upgrade._matrix_error(matrix, wanted[frame][name]) < tolerance, (frame, name)


box = Mock()
assert upgrade.draw_update_box(SimpleNamespace(box=Mock(return_value=box)), bpy.context)
assert box.operator.call_args.args[0] == 'sub.update_old_ik' and box.operator.return_value.rig_name == obj.name
# A dismissed popup reveals the Misc. button only while the rig is still pending.
with patch.object(upgrade, 'reveal_update_button') as reveal:
    upgrade._reveal_if_still_pending()
    reveal.assert_called_once()
misc = next(cls for panel_id, cls in importlib.import_module(MODULE + '.source.panel_order')._iter_ultimate_panel_classes()
            if panel_id == upgrade.MISC_PANEL)
upgrade.reveal_update_button(bpy.context)
assert 'DEFAULT_CLOSED' in misc.bl_options and misc.is_registered
print('MISC. UPDATE BUTTON AND DISMISSED-POPUP REVEAL PASSED')
scene.frame_set(7)
before_poses = poses(obj)
before_state = state(obj)
hip_keys = [entry for entry in before_state[0] if 'Hip' in entry[0]]
assert hip_keys and before_state[1]['sub_use_ik_legs']
# Guard drill: a failure mid-rebuild restores every edited ID from the backup.
counts = (len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.actions))
scene.frame_set(7)
with patch.object(upgrade.ik, 'match', side_effect=RuntimeError('injected matching failure')):
    try:
        upgrade.update_in_place(bpy.context, obj)
    except RuntimeError as error:
        assert 'injected' in str(error)
    else:
        raise AssertionError('Failure was swallowed')
obj = bpy.data.objects[NAME]
assert (len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.actions)) == counts
assert obj.name in scene.objects and upgrade.needs_update(obj)
assert state(obj) == before_state
assert scene.frame_current == 7 and bpy.context.object == obj
assert len(obj.animation_data.action.slots) == 1
assert_poses(obj, before_poses, 1e-6)
print('FAILED IK UPDATE ROLLS BACK THE RIG, ITS ACTIONS AND SWITCH KEYS PASSED')

data_before = obj.data
with patch.object(upgrade.ik, 'upgrade_pull_controls') as auto_upgrade:
    rig._ensure_ik_drivers_on_loaded_rigs()
    auto_upgrade.assert_not_called()
scene.frame_set(7)
updated = upgrade.update_in_place(bpy.context, obj)
assert updated == obj and obj.data == data_before and obj.name == NAME
assert not upgrade.needs_update(obj) and not upgrade.pending_rigs(scene)
assert not upgrade.draw_update_box(SimpleNamespace(box=Mock()), bpy.context)
with patch.object(upgrade, 'reveal_update_button') as reveal:
    upgrade._reveal_if_still_pending()
    reveal.assert_not_called()
assert scene.frame_current == 7 and bpy.context.object == obj
after_state = state(obj)
assert [entry for entry in after_state[0] if 'Hip' in entry[0]] == hip_keys
assert after_state[1] == before_state[1]
# The hip keys make the old IK hold the feet, so the legs are re-solved by the new rig:
# unrelated bones stay exact and the feet stay where the old controls put them.
for frame, matrices in poses(obj).items():
    assert upgrade._matrix_error(matrices['Hip'], before_poses[frame]['Hip']) < 1e-5, frame
    # Frames 11-15 blend IK into FK; there the new solve legitimately differs from the old one.
    for name in (('FootL', 'FootR') if frame <= 10 or frame == 16 else ()):
        assert (matrices[name].translation - before_poses[frame][name].translation).length < 0.05, (frame, name)
backup = bpy.data.objects[obj[upgrade.BACKUP_KEY]]
assert backup.use_fake_user and backup.name not in scene.objects and backup.data != obj.data
assert backup.animation_data.action != obj.animation_data.action
assert keys(backup.animation_data.action) == before_state[0]
print('IN-PLACE IK UPDATE KEEPS NAMES, UNRELATED KEYS, SWITCH KEYS AND THE EVALUATED POSE PASSED')

with patch.object(upgrade.bpy.ops.sub, 'ik_update_prompt', create=True) as prompt:
    upgrade._show_update_prompt()
    prompt.assert_not_called()
wm = Mock()
fake = SimpleNamespace(scene=scene, window_manager=wm)
with patch.object(upgrade, 'pending_rigs', return_value=[obj]):
    operator = SimpleNamespace()
    assert upgrade.SUB_OT_ik_update_prompt.invoke(operator, fake, None) == {'RUNNING_MODAL'}
# The modal handler must be queued before the popup so the popup blocks it while open.
assert [call[0] for call in wm.method_calls] == ['modal_handler_add', 'popup_menu']
menu_draw = wm.popup_menu.call_args.args[0]
layout = Mock()
menu_draw(SimpleNamespace(layout=layout), None)
assert layout.operator.call_args.args[0] == 'sub.update_old_ik'
assert layout.operator.return_value.rig_name == obj.name
with tempfile.TemporaryDirectory(prefix='ik-upgrade-reload-') as directory:
    path = str(Path(directory) / 'upgraded.blend')
    backup_name = backup.name
    bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=path)
    assert upgrade._load_post in bpy.app.handlers.load_post
    assert not upgrade.needs_update(bpy.data.objects[NAME])
    assert backup_name in bpy.data.objects
    assert not upgrade.pending_rigs(bpy.context.scene)
print('UPDATE PROMPT TARGETING, DISMISSAL AFTER UPDATE, AND SAVE/REOPEN VERSION DETECTION PASSED')
