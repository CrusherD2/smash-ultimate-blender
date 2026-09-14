"""Run in factory background Blender with --python-exit-code 1."""
from pathlib import Path
import importlib
import tempfile
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
channels = importlib.import_module(MODULE + '.source.extras.ik_channels')
model = importlib.import_module(MODULE + '.source.model.import_model')
progress = importlib.import_module(MODULE + '.source.export_progress')

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    costume = root / 'fighter/test/model/body/c03'
    shared = root / 'fighter/test/motion/body/c00/a00defaulteyelid.nuanmb'
    specific = shared.parent.parent / 'c03' / shared.name
    assert model.find_default_eyelid(costume) is None
    shared.parent.mkdir(parents=True)
    shared.touch()
    assert model.find_default_eyelid(costume) == shared
    specific.parent.mkdir()
    specific.touch()
    assert model.find_default_eyelid(costume) == specific
    assert model.find_default_eyelid(root / 'fighter/other/model/body/c03') is None

calls = []
context = SimpleNamespace(window_manager=SimpleNamespace(
    progress_begin=lambda *args: calls.append('begin'),
    progress_end=lambda: calls.append('end')))
try:
    with progress.ExportProgress(context):
        with progress.ExportProgress(context):
            raise ValueError('test cleanup')
except ValueError:
    pass
assert calls == ['begin', 'end'] and progress.ExportProgress.depth == 0

bpy.ops.object.armature_add()
obj = bpy.context.object
bpy.ops.object.mode_set(mode='EDIT')
bones = obj.data.edit_bones
bones.remove(bones[0])
parent = None
names = ('LegL', 'UpperOffsetL', 'KneeL', 'LowerOffsetL', 'FootL')
points = [(0, 0, 4), (0, -.2, 3), (0, -.4, 2), (0, -.2, 1), (0, 0, 0), (0, 1, 0)]
for i, name in enumerate(names):
    bone = bones.new(name)
    bone.head, bone.tail = points[i], points[i+1]
    bone.parent = parent
    bone.use_connect = parent is not None
    parent = bone
bpy.ops.object.mode_set(mode='OBJECT')
assert channels.create_controls(bpy.context, obj, 'LEGS') == 1
con = channels.solve_bone(obj, ('LegL', 'KneeL', 'FootL')).constraints['SUB IK Solve']
assert con.chain_count == 4
assert (obj.pose.bones[channels.PREFIX + 'FootL'].matrix.translation - obj.pose.bones['FootIKL'].matrix.translation).length < .02
assert con.id_data == obj
for name in names:
    solver = obj.pose.bones[channels.PREFIX + name]
    assert obj.pose.bones[name].constraints.get(channels.OUTPUT)
assert obj.data.bones['KneeL'].parent.name == 'UpperOffsetL'
control = obj.pose.bones['FootIKL']
control.location.x += .3
control.location.y += .5
obj.update_tag()
bpy.context.view_layer.update()
end = obj.pose.bones[channels.PREFIX + 'FootL']
assert (end.matrix.translation - control.matrix.translation).length < .02, (tuple(end.matrix.translation), tuple(control.matrix.translation))
channels.create_controls(bpy.context, obj, 'LEGS')
assert sum(c.name.startswith(channels.OUTPUT) for c in obj.pose.bones['KneeL'].constraints) == 1
print('EXPORT / EYELID / INTERMEDIATE IK TESTS PASSED')
