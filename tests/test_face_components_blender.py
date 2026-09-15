"""Pose endpoints, orbit geometry, expression blending and widget persistence."""

from pathlib import Path

fixture = Path(__file__).with_name('test_custom_components_blender.py')
exec(
    compile(
        fixture.read_text(encoding='utf-8').split('components = [')[0],
        str(fixture),
        'exec',
    )
)
face = importlib.import_module(MODULE + '.source.extras.face_components')
appearance = importlib.import_module(MODULE + '.source.extras.control_appearance')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
from mathutils import Quaternion


def update():
    obj.update_tag()
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())


def matrix(name):
    return update().pose.bones[name].matrix.copy()


def close(a, b, label=''):
    error = max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))
    assert error < 1e-5, (label, error, a, b)


def pose(action, label=''):
    assert bpy.ops.sub.face_pose(action=action, label=label) == {'FINISHED'}


component('LIDS', 'Eyelids', ['LidUpper', 'LidLower'])
editor.active_index = 0
pose('NEUTRAL')
neutral = {n: matrix(n) for n in ('LidUpper', 'LidLower')}
pose('EDIT')
obj.pose.bones['LidUpper'].location.z = -0.25
left = matrix('LidUpper')
pose('CAPTURE', 'Left Closed')
pose('EDIT')
obj.pose.bones['LidLower'].location.z = 0.3
right = matrix('LidLower')
pose('CAPTURE', 'Right Closed')
c = editor.components[0]
sliders = {p['expression']: p for p in face.owned(obj, c) if p.get('expression')}
sliders['Left Closed'].location.y = 1
close(matrix('LidUpper'), left, 'left close')
close(matrix('LidLower'), neutral['LidLower'], 'other eye stays neutral')
sliders['Left Closed'].location.y = 0
assert set(sliders)=={'Left Closed','Right Closed','Selected Expression'}
assert cc.control_name(obj,c) in obj.pose.bones
sliders['Left Closed'].location.y = 1
sliders['Right Closed'].location.y = 1
close(matrix('LidUpper'), left, 'both left')
close(matrix('LidLower'), right, 'both right')
sliders['Left Closed'].location.y = 1
close(matrix('LidUpper'), left, 'shared plus individual clamps')
sliders['Left Closed'].location.y = 0
sliders['Right Closed'].location.y = 0

component('MOUTH', 'Mouth', ['Jaw'])
editor.active_index = 1
pose('NEUTRAL')
pose('EDIT')
pb = obj.pose.bones['Jaw']
pb.matrix_basis = Matrix.LocRotScale(
    Vector((0.1, 0.2, -0.3)), Quaternion((0, 0, 1), 0.45), Vector((1.1, 0.8, 1))
)
expression = matrix('Jaw')
pose('CAPTURE', 'Smile')
c = editor.components[1]
slider = next(p for p in face.owned(obj, c) if p.get('expression') == 'Smile')
slider.location.y = 1
close(matrix('Jaw'), expression, 'full mouth expression')
assert cc.control_name(obj,c) in obj.pose.bones
assert {p.get('expression') for p in face.owned(obj,c) if not p.bone.get('sub_face_helper')}=={'Smile','Selected Expression'}
slider.location.y = 0
assert abs(matrix('Jaw').translation.z - 3.5) < 1e-5
slider.location.y = 0.5
half = matrix('Jaw')
assert abs(half.translation.z - (expression.translation.z + 3.5) / 2) < 1e-5
slider.location.y = 0

component('EYES', 'Eye Orbit', ['EyeL', 'EyeR'])
editor.active_index = 2
pose('NEUTRAL')
pose('EDIT')
obj.pose.bones['EyeL'].location.x = -0.2
obj.pose.bones['EyeR'].location.x = -0.2
left = matrix('EyeL')
pose('CAPTURE', 'Left')
c = editor.components[2]
main = obj.pose.bones[cc.control_name(obj, c)]
look = next(p for p in face.owned(obj, c) if p.get('expression') == 'Look X / Y')
look.location.x = -1
close(matrix('EyeL'), left, 'authored look limit')
look.location.x = 0
start = matrix('EyeL').translation
pivot = matrix(main.name).translation
radius = (start - pivot).length
main.rotation_mode = 'XYZ'
main.rotation_euler.z = 0.8
end = matrix('EyeL').translation
assert abs((end - pivot).length - radius) < 1e-5, 'Eye must follow a circular orbit'
assert (end - start).length > 0.2
# An authored orbit limit also follows an arc through intermediate slider values.
main.rotation_euler.z = 0
pose('ORBIT')
main.rotation_euler.z = 0.6
orbit_endpoint = matrix('EyeL')
pose('CAPTURE', 'Right')
look.location.x = 1
close(matrix('EyeL'), orbit_endpoint, 'captured pivot endpoint')
look.location.x = 0.5
assert abs((matrix('EyeL').translation - pivot).length - radius) < 1e-5
look.location.x = 0
# Controller animation survives rebuild and generated helpers do not multiply.
main.keyframe_insert('rotation_euler', frame=1)
count = len(obj.data.bones)
cc.build_component(bpy.context, obj, c)
assert count == len(obj.data.bones)
close(matrix('EyeL'), update().pose.bones['EyeL'].matrix, 'rebuild')
# Appearance overrides persist through normal rig shape assignment.
pb = obj.pose.bones['Jaw']
pb.custom_shape = rig._widget_object(bpy.context, 'square')
pb.custom_shape_scale_xyz = (2, 3, 4)
pb.custom_shape_translation = (0.1, 0.2, 0.3)
appearance.remember(pb, 'square')
rig._assign_shape(pb, rig._widget_object(bpy.context, 'circle'), 1, 'THEME01', False)
assert tuple(pb.custom_shape_scale_xyz) == (2, 3, 4)
assert pb.custom_shape == rig._widget_object(bpy.context, 'square')
# Editing a widget creates independent geometry and returns to the rig.
compat = importlib.import_module(MODULE + '.source.blender_compat')
for other in obj.pose.bones:
    compat.set_pose_bone_select(other, False)
compat.set_pose_bone_select(pb, True)
obj.data.bones.active = pb.bone
source_widget = pb.custom_shape
assert bpy.ops.sub.control_shape(action='EDIT') == {'FINISHED'}
widget = bpy.context.scene.sub_shape_edit_object
assert (
    widget.mode == 'EDIT'
    and widget.data != source_widget.data
    and not widget.hide_viewport
)
assert bpy.ops.sub.control_shape(action='FINISH') == {'FINISHED'}
assert obj.mode == 'POSE' and widget.hide_get()
# Preset contains captured values and chosen shape, including legacy migration.
c.shape = 'diamond'
payload = dict(
    format=cc.FORMAT,
    version=cc.VERSION,
    name='Face',
    components=[cc.serialize(v) for v in editor.components],
)
cc.load_preset(editor, json.loads(json.dumps(payload)))
assert editor.components[2].shape == 'diamond'
assert 'Smile' in json.loads(editor.components[1].face_data)['poses']
legacy = cc.serialize(editor.components[0])
for key in cc.EXTRA_DEFAULTS:
    legacy.pop(key)
cc.validate_preset(dict(format=cc.FORMAT, version=1, name='Old', components=[legacy]))
# Removing face controllers removes helper drivers and preserves skeleton bones.
c = editor.components[0]
owner = c.uid
cc.remove_component(bpy.context, obj, c)
assert not [p for p in obj.pose.bones if p.bone.get('sub_face_owner') == owner]
assert all(n in obj.pose.bones for n in ('LidUpper', 'LidLower'))
assert all(d.is_valid for d in obj.animation_data.drivers)
assert rig._should_hide_bone('LegC') and rig._should_hide_bone('ClavicleC')
print('FACIAL POSES, ORBIT, PRESETS AND SHAPES PASSED')
