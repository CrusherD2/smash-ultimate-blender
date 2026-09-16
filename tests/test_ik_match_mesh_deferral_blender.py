"""Exact downstream geometry and visibility restoration during IK matching."""
from pathlib import Path
import importlib
import os
import tempfile

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND', ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
if not baseline.exists():
    print(f'SKIP IK mesh deferral: missing real-rig fixture {baseline}')
    raise SystemExit(0)
bpy.ops.wm.open_mainfile(filepath=str(baseline))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ik.create_controls(bpy.context, obj, 'BOTH')
scene = bpy.context.scene
scene.frame_end = min(scene.frame_end, scene.frame_start + 19)
scene.frame_set(scene.frame_start + 3)

# Test geometry with a nontrivial downstream modifier and several visibility
# sources. None of the custom visibility channels may be changed by the scope.
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.mesh.primitive_cube_add()
mesh = bpy.context.object
mesh.name = 'Match visibility fixture'
mesh.parent = obj
modifier = mesh.modifiers.new('Detail', 'SUBSURF')
modifier.levels = 2
mesh.hide_viewport = False
animated = mesh.copy()
scene.collection.objects.link(animated)
animated.name = 'Keyed visibility'
animated.keyframe_insert('hide_viewport', frame=scene.frame_start)
custom = mesh.copy()
scene.collection.objects.link(custom)
custom.name = 'Custom driven visibility'
custom.driver_add('hide_viewport').driver.expression = 'False'
hidden = mesh.copy()
scene.collection.objects.link(hidden)
hidden.name = 'Already hidden'
hidden.hide_viewport = True
hidden.hide_set(True)
nla_mesh = mesh.copy()
scene.collection.objects.link(nla_mesh)
nla_mesh.name = 'NLA visibility'
nla_mesh.animation_data_create().nla_tracks.new()
generated = mesh.copy()
scene.collection.objects.link(generated)
generated.name = 'Imported visibility'
bpy.context.view_layer.objects.active = obj
entries = obj.data.sub_anim_properties.vis_track_entries
entry = entries.add()
entry.name = 'Match visibility test'
entry.value = True
entry.keyframe_insert('value', frame=scene.frame_start)
entry.value = False
entry.keyframe_insert('value', frame=scene.frame_end)
driver_curve = generated.driver_add('hide_viewport')
driver = driver_curve.driver
variable = driver.variables.new()
variable.name = 'var'
variable.type = 'SINGLE_PROP'
variable.targets[0].id_type = 'ARMATURE'
variable.targets[0].id = obj.data
variable.targets[0].data_path = f'sub_anim_properties.vis_track_entries[{len(entries)-1}].value'
driver.expression = '1 - var'
scene.frame_set(scene.frame_current)

bpy.context.view_layer.objects.active = obj
obj.select_set(True)
mesh.select_set(False)
bpy.ops.object.mode_set(mode='POSE')


def visibility():
    return {o.name: (o.hide_viewport, o.hide_get(),
                    [(fc.data_path, fc.mute) for fc in o.animation_data.drivers]
                    if o.animation_data else [])
            for o in scene.objects if o.type == 'MESH'}


before = visibility()
try:
    with ik._defer_match_meshes(bpy.context, obj, True):
        assert mesh.hide_viewport
        assert not animated.hide_viewport
        assert not custom.hide_viewport
        assert hidden.hide_viewport
        assert not nla_mesh.hide_viewport
        assert generated.hide_viewport and driver_curve.mute
        raise ValueError('injected failure')
except ValueError:
    pass
assert visibility() == before

# Failure through the real matching path must also restore frame and drivers.
original = ik._evaluate_match_steps
original_frame = scene.frame_current
def fail(*args):
    assert mesh.hide_viewport
    raise ValueError('injected solve failure')
ik._evaluate_match_steps = fail
try:
    try:
        ik.match(bpy.context, obj, 'BOTH', _batch=True)
        raise AssertionError('failure was swallowed')
    except ValueError:
        pass
finally:
    ik._evaluate_match_steps = original
assert scene.frame_current == original_frame
assert visibility() == before


def capture():
    keys = {(fc.data_path, fc.array_index): [(tuple(k.co), k.interpolation) for k in fc.keyframe_points]
            for fc in compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')}
    poses, meshes = [], []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        poses.extend(float(v) for bone in obj.pose.bones for row in bone.matrix for v in row)
        dg = bpy.context.evaluated_depsgraph_get()
        for candidate in scene.objects:
            if candidate.type == 'MESH' and not candidate.hide_viewport:
                meshes.extend(float(v) for vertex in candidate.evaluated_get(dg).data.vertices for v in vertex.co)
    return keys, poses, meshes


with tempfile.TemporaryDirectory(prefix='sub_mesh_match_') as folder:
    path = str(Path(folder) / 'start.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    results = []
    for batch in (False, True):
        bpy.ops.wm.open_mainfile(filepath=path)
        obj = bpy.context.object
        scene = bpy.context.scene
        states = visibility()
        ik.match(bpy.context, obj, 'BOTH', _batch=batch)
        assert visibility() == states
        assert scene.frame_current == original_frame
        results.append(capture())
    assert results[0] == results[1], 'keys, all pose matrices and final mesh vertices must match exactly'
print('IK mesh deferral: exact keys, poses, vertices and failure restoration OK')
