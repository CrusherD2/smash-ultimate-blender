from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_components_lifecycle_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('editor.save_on_build = False')[0], str(fixture), 'exec'))
editor.save_on_build = False
component('ISOLATED', 'Toggle test', ['LidUpper'])
c = editor.components[-1]
c.hide_controlled = True
assert bpy.ops.sub.component_build() == {'FINISHED'}
control = obj.pose.bones[cc.control_name(obj, c)]
source = obj.pose.bones['LidUpper']
constraint = next(con for con in source.constraints if con.name.startswith('SUB Component ' + c.uid))

def matrix():
    obj.update_tag()
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[source.name].matrix.copy()

assert source.bone.hide
bpy.context.scene.frame_set(1)
assert bpy.ops.sub.isolated_toggle(control=control.name, enabled=False) == {'FINISHED'}
assert not source.bone.hide and not source.bone.hide_select
assert not getattr(source, 'hide', False)
before = matrix()
source.location.x += 0.7
assert (matrix().translation - before.translation).length > 0.6
constraint.mute = True
original = matrix()
constraint.mute = False
assert max(abs(matrix()[r][k] - original[r][k]) for r in range(4) for k in range(4)) < 2e-5
bpy.context.scene.frame_set(5)
assert bpy.ops.sub.isolated_toggle(control=control.name, enabled=True) == {'FINISHED'}
assert source.bone.hide
before = matrix()
source.location.x += 0.8
assert (matrix().translation - before.translation).length < 2e-5
path = control.path_from_id() + '["follows_parent_bone"]'
fc = next(fc for fc in curves.get_all_action_fcurves(obj.animation_data.action) if fc.data_path == path)
assert all(key.interpolation == 'CONSTANT' for key in fc.keyframe_points)
for frame, expected in ((1, 0.0), (3, 0.0), (5, 1.0)):
    bpy.context.scene.frame_set(frame)
    matrix()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert abs(ev.pose.bones[source.name].constraints[constraint.name].influence - expected) < 1e-5

class Layout:
    def __init__(self):
        self.buttons = []
    def row(self, **kwargs):
        return self
    def label(self, **kwargs):
        pass
    def operator(self, name, **kwargs):
        op = SimpleNamespace()
        self.buttons.append((name, kwargs, op))
        return op

layout = Layout()
workflow.draw_isolated_switches(layout, obj)
assert len(layout.buttons) == 1
name, kwargs, op = layout.buttons[0]
assert name == 'sub.isolated_toggle' and kwargs['text'] == 'Isolation ON'
assert op.control == control.name and not op.enabled
print('ISOLATED ON/OFF, ORIGINAL EDITING, CONSTANT KEYS AND PANEL UI PASSED')
