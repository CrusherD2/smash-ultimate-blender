from pathlib import Path
import importlib
from mathutils import Vector

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
anim = importlib.import_module(MODULE + '.source.anim.import_anim')


def rig(name):
    bpy.ops.object.armature_add()
    obj = bpy.context.object
    obj.name = name
    bpy.ops.object.mode_set(mode='EDIT')
    obj.data.edit_bones[0].name = 'rot'
    bone = obj.data.edit_bones.new('throw')
    bone.head = (0, 0, 2)
    bone.tail = (0, 1, 2)
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


attacker = rig('Attacker')
victim = rig('Victim')
attacker.location = (3, 4, 5)
victim.location = (-2, 1, 0)
victim.pose.bones['rot'].location = (1, 0, 0)
victim.pose.bones['rot'].keyframe_insert('location', frame=1)
action = victim.animation_data.action
victim.sub_make_thrown = True
assert not victim.pose.bones['rot'].constraints
victim.sub_thrown_attacker = attacker
for frame, position in ((1, (1, 2, 3)), (10, (5, 6, 7))):
    attacker.pose.bones['throw'].location = position
    attacker.pose.bones['throw'].keyframe_insert('location', frame=frame)
for frame in (1, 5, 10):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    a = attacker.evaluated_get(graph)
    v = victim.evaluated_get(graph)
    expected = a.matrix_world @ a.pose.bones['throw'].matrix
    actual = v.matrix_world @ v.pose.bones['rot'].matrix
    assert all(abs(actual[r][c] - expected[r][c]) < 1e-5
               for r in range(4) for c in range(4)), (actual, expected)
assert not anim.poll_thrown_attacker(victim, victim)
assert not anim.poll_thrown_attacker(attacker, victim)
assert victim.animation_data.action == action
victim.sub_make_thrown = False
assert not victim.pose.bones['rot'].constraints
victim.sub_make_thrown = True
assert len(victim.pose.bones['rot'].constraints) == 1
victim.sub_thrown_attacker = None
assert not victim.pose.bones['rot'].constraints
print('Thrown link tests passed')

import tempfile
from types import SimpleNamespace

victim.sub_thrown_attacker = attacker
calls = []
reports = []
original = anim._import_animation_file

def fake_import(context, operator, obj, filepath, *options):
    calls.append((obj, Path(filepath)))
    return True

anim._import_animation_file = fake_import
try:
    with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
        folder = Path(folder)
        other = Path(other)
        attacker[anim.ANIM_FOLDER_KEY] = str(folder)
        reporter = SimpleNamespace(report=lambda level, message: reports.append(message))
        for direction in ('f', 'b', 'hi', 'lw'):
            throw = folder / f'a00throw{direction}.nuanmb'
            thrown = folder / f'a00thrown{direction}.nuanmb'
            throw.touch()
            thrown.touch()
            calls.clear()
            assert anim.import_animation_file(bpy.context, reporter, attacker, str(throw), True, True, True, 1)
            assert calls == [(attacker, throw), (victim, thrown)], calls
            assert bpy.context.object == victim
            calls.clear()
            assert anim.import_animation_file(bpy.context, reporter, victim,
                str(other / thrown.name), True, True, True, 1)
            assert calls == [(victim, thrown), (attacker, throw)], calls
        victim.sub_make_thrown = False
        calls.clear()
        anim.import_animation_file(bpy.context, reporter, attacker, str(throw), True, True, True, 1)
        assert calls == [(attacker, throw)]
        victim.sub_make_thrown = True
        calls.clear()
        missing = folder / 'throwf.nuanmb'
        missing.touch()
        anim.import_animation_file(bpy.context, reporter, attacker, str(missing), True, True, True, 1)
        assert calls == [(attacker, missing)] and reports
finally:
    anim._import_animation_file = original
print('Paired throw selection tests passed')

attacker.pose.bones['throw'].name = 'Throw'
victim.pose.bones['rot'].name = 'Rot'
anim.update_thrown_link(victim, bpy.context)
assert victim.pose.bones['Rot'].constraints[anim.THROWN_CONSTRAINT_NAME].subtarget == 'Throw'
no_throw = rig('Armature without throw')
no_throw.data.bones['throw'].name = 'Other'
assert anim.poll_thrown_attacker(victim, no_throw)
victim.sub_thrown_attacker = no_throw
assert not victim.pose.bones['Rot'].constraints
victim.sub_thrown_attacker = attacker
assert victim.pose.bones['Rot'].constraints[anim.THROWN_CONSTRAINT_NAME].target == attacker
print('Armature picker and capitalized bone tests passed')
