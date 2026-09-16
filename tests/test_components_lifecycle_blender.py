"""Functional planes, isolation, presets and bake/export round trips."""

from pathlib import Path

fixture = Path(__file__).with_name('test_custom_components_blender.py')
exec(
    compile(
        fixture.read_text(encoding='utf-8').split('components = [')[0],
        str(fixture),
        'exec',
    )
)
workflow = importlib.import_module(MODULE + '.source.extras.component_workflow')
face = importlib.import_module(MODULE + '.source.extras.face_components')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
compat = importlib.import_module(MODULE + '.source.blender_compat')
editor.save_on_build = False
component('ISOLATED', 'Floating Feet', ['LidUpper', 'LidLower'])
component('LOOK_TARGET', 'Aim', ['EyeL'])
component('EYES', 'Authored Eye', ['EyeR'])
components = list(editor.components)
assert bpy.ops.sub.component_build() == {'FINISHED'}
iso = components[0]
# d4cf27f gave isolated components foot roll / toe handles, so each controlled
# bone now carries a ROOT control plus _Heel and _Toe children and an _Output
# helper -- six controllers and two helpers for these two bones, where this
# asserted two. The intent is the top-level control per controlled bone, which
# component_workflow marks sub_isolated_role == 'ROOT' (the handles are tagged
# with the role they play and a sub_isolated_target instead). Selecting on that
# marker rather than on parentage keeps the assertion below meaningful, and
# keeps controllers[0] the same bone the rest of this test poses and keys.
controllers = [p for p in face.owned(obj, iso)
               if not p.bone.get('sub_face_helper')
               and p.bone.get('sub_isolated_role') == 'ROOT']
assert len(controllers) == 2, [p.name for p in controllers]
assert all(p.parent is None for p in controllers)


def update():
    obj.update_tag()
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())


def matrix(name):
    return update().pose.bones[name].matrix.copy()


def close(a, b):
    error = max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))
    assert error < 2e-5, error


before = {n: matrix(n) for n in ['LidUpper', 'LidLower']}
obj.pose.bones['Trans'].location = (1, 2, 3)
obj.pose.bones['Head'].rotation_mode = 'XYZ'
obj.pose.bones['Head'].rotation_euler.z = 0.3
for n in before:
    close(before[n], matrix(n))
controllers[0].location.x = 0.4
assert (matrix('LidUpper').translation - before['LidUpper'].translation).length > 0.3
# The default eye pad moves vertically, rather than deeper into the head.
c = components[2]
pivot = cc.control_name(obj, c)
assert obj.data.bones[pivot].hide
pad = obj.pose.bones[pivot + '_Look']
origin = matrix(pad.name).translation
pad.location.y = 0.5
motion = matrix(pad.name).translation - origin
# Head is rotated around Z only; local up still maps to armature Z.
assert abs(motion.z - 0.5) < 1e-5 and abs(motion.y) < 1e-5, motion
pad.location.y = 0
c.show_orbit = True
cc.build_component(bpy.context, obj, c)
assert not obj.data.bones[pivot].hide
c.show_orbit = False
cc.build_component(bpy.context, obj, c)
# Functional placement transforms the actual controller and survives rebuilding.
for pb in obj.pose.bones:
    compat.set_pose_bone_select(pb, False)
compat.set_pose_bone_select(pad, True)
obj.data.bones.active = pad.bone
pad.custom_shape_translation = (0.2, 0, 0)
pad.custom_shape_rotation_euler = (0, 0.3, 0)
old = pad.bone.matrix_local.copy()
assert bpy.ops.sub.control_shape(action='FUNCTIONAL') == {'FINISHED'}
changed = obj.data.bones[pad.name].matrix_local.copy()
assert (changed.translation - old.translation).length > 0.19
assert tuple(pad.custom_shape_translation) == (0, 0, 0)
cc.build_component(bpy.context, obj, c)
close(changed, obj.data.bones[pad.name].matrix_local)
# Serialize placement and all component types through the normal preset loader.
path = cc.save_preset(editor)
assert workflow.read_preset(path.name)['components'][0]['kind'] == 'ISOLATED'
# Animate source parents and isolated handles, then export the entire live rig.
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 3
for f in (1, 3):
    scene.frame_set(f)
    obj.pose.bones['Trans'].location = (f * 0.3, 0, f * 0.2)
    obj.pose.bones['Trans'].keyframe_insert('location', frame=f)
    controllers[0].location.x = f * 0.2
    controllers[0].keyframe_insert('location', frame=f)
    obj.pose.bones[cc.control_name(obj, components[1])].location.x = f * 0.15
    obj.pose.bones[cc.control_name(obj, components[1])].keyframe_insert(
        'location', frame=f
    )
expected = {}
names = rig_export.export_bone_names(obj)
for f in range(1, 4):
    scene.frame_set(f)
    evaluated = update()
    expected[f] = {n: evaluated.pose.bones[n].matrix.copy() for n in names}
from types import SimpleNamespace

with tempfile.TemporaryDirectory() as folder:
    file = str(Path(folder) / 'all_components.nuanmb')
    export.export_model_anim_fast(
        bpy.context,
        SimpleNamespace(report=lambda *a: None),
        obj,
        file,
        True,
        False,
        False,
        1,
        3,
    )
    anim = addon.dependencies.ssbh_data_py.anim_data.read_anim(file)
    nodes = next(g.nodes for g in anim.groups if g.group_type.name == 'Transform')
    assert set(n.name for n in nodes) == set(names)
    from mathutils import Quaternion

    for node in nodes:
        parent = obj.pose.bones[node.name].parent
        for index, v in enumerate(node.tracks[0].values):
            local = expected[index + 1][node.name]
            local = (
                export.get_smash_transform(
                    expected[index + 1][parent.name].inverted_safe() @ local
                )
                if parent
                else export.get_smash_root_matrix(local)
            )
            actual = Matrix.LocRotScale(
                Vector(v.translation),
                Quaternion((v.rotation[3], *v.rotation[:3])),
                Vector(v.scale),
            )
            close(actual, Matrix.LocRotScale(*local.decompose()))
assert workflow.has_components(obj)
assert bpy.ops.sub.components_bake_remove(bake=True) == {'FINISHED'}
assert not workflow.has_components(obj)
for f in range(1, 4):
    scene.frame_set(f)
    for n in ['LidUpper', 'LidLower', 'EyeL', 'EyeR']:
        close(matrix(n), expected[f][n])
# Building from a saved preset is also used by Create Animation Rig.
workflow.build_preset(bpy.context, obj, path.name)
assert workflow.has_components(obj)
assert bpy.ops.sub.components_bake_remove(bake=False) == {'FINISHED'}
assert not workflow.has_components(obj)
assert (
    'setup_custom_components'
    in bpy.ops.sub.create_animation_rig.get_rna_type().properties
)
assert (
    'bake_custom_components'
    in bpy.ops.sub.bake_and_remove_rig.get_rna_type().properties
)
workflow.preset_items(None, bpy.context)
assert bpy.ops.sub.create_animation_rig(
    setup_ik=False,
    setup_eye_look=False,
    setup_finger_sliders=False,
    setup_custom_components=True,
    custom_component_preset=path.name,
) == {'FINISHED'}
assert workflow.has_components(obj) and rig.armature_has_animation_rig(obj)
assert bpy.ops.sub.bake_and_remove_rig(
    bake_fingers=False, bake_eyes=False, bake_ik=False, bake_custom_components=True
) == {'FINISHED'}
assert not workflow.has_components(obj)
print('COMPONENT PLACEMENT, ISOLATION, EXPORT AND BAKE PASSED')
