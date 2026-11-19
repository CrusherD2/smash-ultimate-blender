from pathlib import Path

fixture = Path(__file__).with_name('test_components_lifecycle_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('editor.save_on_build = False')[0], str(fixture), 'exec'))
editor.save_on_build = False
component('ISOLATED', 'Follow test', ['LidUpper'])
c = editor.components[-1]
assert bpy.ops.sub.component_build() == {'FINISHED'}
control = obj.pose.bones[cc.control_name(obj, c)]
source = obj.pose.bones['LidUpper']
constraint = next(con for con in source.constraints if con.name.startswith('SUB Component ' + c.uid))

def matrix():
    obj.update_tag()
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[source.name].matrix.copy()

def error(a, b):
    return max(abs(a[r][k] - b[r][k]) for r in range(4) for k in range(4))

independent = matrix()
parent = source.parent
assert parent is not None
parent.location.x += 2.0
source.location.y += 0.4
assert error(matrix(), independent) < 2e-5
control['follows_parent_bone'] = 1.0
followed = matrix()
constraint.mute = True
original = matrix()
constraint.mute = False
assert error(followed, original) < 2e-5
assert error(followed, independent) > 0.1
for frame, value in ((1, 0.0), (11, 1.0)):
    control['follows_parent_bone'] = value
    control.keyframe_insert(data_path='["follows_parent_bone"]', frame=frame)
for frame, expected in ((1, 1.0), (6, 0.5), (11, 0.0)):
    bpy.context.scene.frame_set(frame)
    matrix()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    actual = evaluated.pose.bones[source.name].constraints[constraint.name].influence
    assert abs(actual - expected) < 1e-5, (frame, actual)
assert bpy.ops.sub.component_build() == {'FINISHED'}
assert control['follows_parent_bone'] == 1.0
print('ISOLATED PARENT FOLLOW PASSED')

graph_module = importlib.import_module(MODULE + '.source.extras.component_graph')
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
control_path = control.path_from_id() + '["follows_parent_bone"]'
for fc in compat.get_all_action_fcurves(obj.animation_data.action):
    if fc.data_path == control_path:
        fc.mute = True
native = graph_module.Graph(obj, {source.name}, set(), set())
try:
    for follow in (0., .5, 1., -.5, 1.5, 0.):
        control['follows_parent_bone'] = follow
        expected_matrix = matrix()
        actual_matrix = native.evaluate().pose.bones[source.name].matrix
        assert error(actual_matrix, expected_matrix) < 2e-5, (follow, error(actual_matrix, expected_matrix))
finally:
    native.close()
constraint = next(con for con in source.constraints if con.name == 'SUB Component ' + c.uid)
path = constraint.path_from_id() + '.influence'
fc = next(fc for fc in obj.animation_data.drivers if fc.data_path == path)
original_expression = fc.driver.expression
fc.driver.expression = 'follow'
try:
    try:
        graph_module.Graph(obj, {source.name}, set(), set())
        raise AssertionError('Unrecognised influence driver was accepted')
    except ValueError as exc:
        assert 'Driver-controlled constraint settings' in str(exc), exc
finally:
    fc.driver.expression = original_expression
print('NATIVE ISOLATION FOLLOW AND DRIVER GUARDS PASSED')
