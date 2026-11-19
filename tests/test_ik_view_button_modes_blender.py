from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_ik_endpoint_hiding_blender.py')
exec(compile(fixture.read_text().split("endpoints =")[0], str(fixture), 'exec'))
gizmos = importlib.import_module(MODULE + '.source.extras.ik_gizmos')
compat = importlib.import_module(MODULE + '.source.blender_compat')
data[rig.ARMATURE_FLAG] = True

def selected_button(name):
    for bone in arm.pose.bones:
        compat.set_pose_bone_select(bone, False)
    bone = arm.pose.bones[name]
    compat.set_pose_bone_select(bone, True)
    data.bones.active = bone.bone
    return gizmos.selected(bpy.context)

for kind, control, fk in (('ARMS', 'HandIKL', 'HandL'), ('LEGS', 'FootIKL', 'FootL')):
    for frame, enabled in ((1, True), (5, False), (9, True)):
        scene.frame_set(frame)
        assert bpy.ops.sub.anim_rig_toggle_ik_fk(
            limbs=kind, set_enabled=True, enable_ik=enabled) == {'FINISHED'}
        bpy.context.view_layer.update()
        assert bool(selected_button(control)) == enabled
        found = selected_button(fk)
        assert bool(found) == (not enabled)
        if found:
            assert found[2] == (kind, fk, 'FK', '')
            assert gizmos.SUB_OP_ik_view_button.execute(
                SimpleNamespace(action='IK'), bpy.context) == {'FINISHED'}
            bpy.context.view_layer.update()
            assert selected_button(fk) is None
            assert selected_button(control) is not None
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(
        limbs=kind, set_enabled=True, enable_ik=False) == {'FINISHED'}
    rig.set_off_mode_bones_hidden(arm, False)
    bpy.context.view_layer.update()
    assert selected_button(control) is None
    assert selected_button(fk)[2][2] == 'FK'

appearance = importlib.import_module(MODULE + '.source.extras.control_appearance')
lengths = {name: arm.pose.bones[name].length for name in ('HandIKL', 'FootIKL')}
for bone_size in (False, True):
    for name in ('HandL', 'FootL'):
        pb = arm.pose.bones[name]
        rig._assign_shape(pb, rig._widget_object(bpy.context, 'box'), (.3, .4, .5), 'THEME04', False)
        pb.use_custom_shape_bone_size = bone_size
    appearance.style_ik_controls(bpy.context, arm)
    for control, fk in (('HandIKL', 'HandL'), ('FootIKL', 'FootL')):
        pb, source = arm.pose.bones[control], arm.pose.bones[fk]
        factor = source.length if bone_size else 1
        assert not pb.use_custom_shape_bone_size
        for color in (pb.color, pb.bone.color):
            assert color.palette == 'CUSTOM'
            assert tuple(round(value * 255) for value in color.custom.normal) == (255, 89, 13)
            assert color.custom.select.g > color.custom.normal.g
            assert color.custom.active.g > color.custom.select.g
        assert all(abs(a - b * factor * 1.15) < 1e-5
                   for a, b in zip(pb.custom_shape_scale_xyz, source.custom_shape_scale_xyz))
        assert abs(pb.length - lengths[control]) < 1e-5
pb = arm.pose.bones['HandIKL']
pb.custom_shape_scale_xyz = (.7, .8, .9)
appearance.remember(pb, 'box')
appearance.style_ik_controls(bpy.context, arm)
assert all(abs(a-b) < 1e-5 for a, b in zip(pb.custom_shape_scale_xyz, (.7, .8, .9)))
print('HAND/FOOT IK/FK BUTTONS AND CONTROL SIZES PASSED')
