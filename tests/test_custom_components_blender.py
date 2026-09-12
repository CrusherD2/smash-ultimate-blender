"""Headless component editor, preset, custom IK, and whole-rig export regressions."""

from pathlib import Path
import importlib, json, tempfile
from mathutils import Matrix, Vector
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(
    compile(
        fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'
    )
)
cc = importlib.import_module(MODULE + '.source.extras.custom_components')
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
export = importlib.import_module(MODULE + '.source.anim.export_anim')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
rig_export = importlib.import_module(MODULE + '.source.extras.rig_export')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
data = bpy.data.armatures.new('Component Test')
obj = bpy.data.objects.new('Component Test', data)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')


def bone(name, head, parent=None):
    b = data.edit_bones.new(name)
    b.head = head
    b.tail = Vector(head) + Vector((0, 1, 0))
    b.parent = data.edit_bones.get(parent) if parent else None


bone('Trans', (0, 0, 0))
bone('Head', (0, 0, 4), 'Trans')
for name, head in [
    ('EyeL', (-0.3, 0, 4)),
    ('EyeR', (0.3, 0, 4)),
    ('Jaw', (0, 0, 3.5)),
    ('LidUpper', (0, 0, 4.2)),
    ('LidLower', (0, 0, 3.8)),
    ('WingL', (-1, 0, 3)),
    ('WingR', (1, 0, 3)),
]:
    bone(name, head, 'Head')
for prefix in ('Tail', 'Tentacle', 'Extra'):
    parent = 'Trans'
    for i in range(4):
        name = prefix + str(i)
        bone(name, (2 + (i % 2) * 0.15, i, 1), parent)
        parent = name
bpy.ops.object.mode_set(mode='POSE')
editor = bpy.context.scene.sub_component_editor
editor.armature = obj
editor.preset_name = 'Regression Components'
import uuid


def component(kind, name, names):
    c = editor.components.add()
    c.uid = uuid.uuid4().hex
    c.kind = kind
    c.name = name
    for n in names:
        c.bones.add().bone = n
    return c


components = [
    component('EYES', 'Eye Look', ['EyeL', 'EyeR']),
    component('JAW', 'Jaw', ['Jaw']),
    component('LIDS', 'Blink', ['LidUpper', 'LidLower']),
    component('FAN', 'Wings', ['WingL', 'WingR']),
    component('CURL', 'Tail', [f'Tail{i}' for i in range(4)]),
]
editor.components[2].bones[1].weight = -1
editor.components[3].bones[0].weight = -1
c = component('IK', 'Tentacle IK', [])
c.root, c.middle, c.end = 'Tentacle0', 'Tentacle2', 'Tentacle3'
components = list(editor.components)
assert cc.selected_chain(obj, ['Tentacle0', 'Tentacle3']) == (
    'Tentacle0',
    'Tentacle2',
    'Tentacle3',
)
assert bpy.ops.sub.component_build() == {'FINISHED'}
assert (cc.preset_dir() / 'Regression_Components.json').exists() or any(
    cc.preset_dir().glob('*.json')
)
count = len(obj.pose.bones)
control_names = [cc.control_name(obj, c) for c in components[:-1]]
for frame in (1, 5):
    bpy.context.scene.frame_set(frame)
    for i, name in enumerate(control_names):
        pb = obj.pose.bones[name]
        pb.location = (
            (0.25 * (frame - 1), 0, 0)
            if i == 0
            else (0, float(pb.bone['sub_component_travel']) * (frame - 1) / 4, 0)
        )
        pb.keyframe_insert('location', frame=frame)
assert bpy.ops.sub.component_build() == {'FINISHED'}
assert len(obj.pose.bones) == count, 'Update duplicated controls'
# Creating another custom IK must not write new keys on the existing target.
first = list(ik.custom_jobs(obj))[0][2]
action = obj.animation_data.action
before = [
    [(tuple(k.co)) for k in fc.keyframe_points]
    for fc in curves.get_all_action_fcurves(action)
    if first in fc.data_path
]
c2 = component('IK', 'Extra IK', [])
c2.root, c2.middle, c2.end = 'Extra0', 'Extra2', 'Extra3'
assert bpy.ops.sub.component_build() == {'FINISHED'}
after = [
    [(tuple(k.co)) for k in fc.keyframe_points]
    for fc in curves.get_all_action_fcurves(action)
    if first in fc.data_path
]
assert before == after, 'New component changed existing IK keys'
path = cc.save_preset(editor)
payload = json.loads(path.read_text(encoding='utf-8'))
cc.load_preset(editor, payload)
assert len(editor.components) == 7
invalid = json.loads(json.dumps(payload))
invalid['components'][0]['kind'] = 'EXECUTE_PYTHON'
try:
    cc.load_preset(editor, invalid)
except ValueError:
    pass
else:
    raise AssertionError('Invalid preset accepted')
assert len(editor.components) == 7


# UI draws all component options, with no unresolved RNA fields.
class Layout:
    def __getattr__(self, name):
        if name in {'prop', 'prop_search'}:
            return lambda owner, field, *args, **kwargs: getattr(owner, field)
        if name == 'operator':
            return lambda *a, **k: SimpleNamespace()
        return lambda *a, **k: self


for index in range(len(editor.components)):
    editor.active_index = index
    cc.draw_editor(Layout(), bpy.context)
# Export must collapse source modifiers and handle axis-angle bones as well.
pb = obj.pose.bones['Tail0']
pb.rotation_mode = 'AXIS_ANGLE'
for frame in (1, 5):
    pb.rotation_axis_angle = (0.1 * frame, 0, 1, 0)
    pb.keyframe_insert('rotation_axis_angle', frame=frame)
pb = obj.pose.bones['Jaw']
pb.rotation_mode = 'XYZ'
pb.keyframe_insert('rotation_euler', frame=1)
fc = next(
    f
    for f in curves.get_all_action_fcurves(obj.animation_data.action)
    if f.data_path == pb.path_from_id() + '.rotation_euler' and f.array_index == 0
)
noise = fc.modifiers.new('NOISE')
noise.strength = 0.12
# Capture actual local transforms before exporting, including all mechanisms.
frames = {}
names = rig_export.export_bone_names(obj)
for frame in range(1, 6):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    frames[frame] = {}
    for name in names:
        pb = evaluated.pose.bones[name]
        frames[frame][name] = (
            export.get_smash_transform(pb.parent.matrix.inverted_safe() @ pb.matrix)
            if pb.parent
            else export.get_smash_root_matrix(pb.matrix)
        )
original_action = obj.animation_data.action
original_constraints = [(pb.name, len(pb.constraints)) for pb in obj.pose.bones]
reporter = SimpleNamespace(report=lambda *a, **k: None)
with tempfile.TemporaryDirectory() as folder:
    file = str(Path(folder) / 'components.nuanmb')
    export.export_model_anim_fast(
        bpy.context, reporter, obj, file, True, False, False, 1, 5
    )
    anim = addon.dependencies.ssbh_data_py.anim_data.read_anim(file)
    nodes = next(g.nodes for g in anim.groups if g.group_type.name == 'Transform')
    assert set(n.name for n in nodes) == set(names)
    worst = 0
    for node in nodes:
        for index, value in enumerate(node.tracks[0].values):
            expected = frames[index + 1][node.name]
            loc, rot, scale = expected.decompose()
            from mathutils import Quaternion

            actual = Matrix.LocRotScale(
                Vector(value.translation),
                Quaternion((value.rotation[3], *value.rotation[:3])),
                Vector(value.scale),
            )
            clean = Matrix.LocRotScale(loc, rot, scale)
            error = max(
                abs(actual[i][j] - clean[i][j]) for i in range(4) for j in range(4)
            )
            worst = max(worst, error)
            assert error < 0.0003, (node.name, index, error)
assert obj.animation_data.action == original_action
assert original_constraints == [(pb.name, len(pb.constraints)) for pb in obj.pose.bones]
first_record = list(ik.custom_jobs(obj))[0]
second_record = list(ik.custom_jobs(obj))[1]
cc.remove_component(bpy.context, obj, editor.components[5])
assert first_record[2] not in obj.pose.bones
assert second_record[2] in obj.pose.bones
assert obj.pose.bones['Extra1'].constraints.get(ik.OUTPUT) is not None
assert data.sub_use_ik_arms == 1.0
foreign = obj.pose.bones['Jaw'].constraints.new('LIMIT_ROTATION')
foreign.name = 'Keep User Constraint'
cc.remove_component(bpy.context, obj, editor.components[1])
assert obj.pose.bones['Jaw'].constraints.get('Keep User Constraint') is not None
assert cc.control_name(obj, editor.components[1]) not in obj.pose.bones
print('COMPONENTS AND FULL RIG EXPORT PASSED', worst)
