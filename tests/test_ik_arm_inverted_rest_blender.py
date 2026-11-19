from pathlib import Path

fixture = Path(__file__).with_name('test_ik_arm_pole_alignment_blender.py')
setup, checks = fixture.read_text().split("bpy.ops.object.mode_set(mode='POSE')", 1)
exec(compile(setup, str(fixture), 'exec'))
for suffix in suffixes:
    side = 1 if suffix.startswith('L') else -1
    data.edit_bones['Shoulder' + suffix].tail = (side * 6, -.05, 15)
    data.edit_bones['Arm' + suffix].head = (side * 6, -.05, 15)
    data.edit_bones['Arm' + suffix].tail = (side * 10, 0, 15)
exec(compile("bpy.ops.object.mode_set(mode='POSE')" + checks, str(fixture), 'exec'))
for suffix in suffixes:
    evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    bone = evaluated.pose.bones[ikc.PREFIX + 'Shoulder' + suffix]
    original_z = data.bones['Shoulder' + suffix].matrix_local.col[2].xyz
    assert bone.matrix.col[2].xyz.normalized().dot(original_z.normalized()) > .5, suffix
print('INVERTED REST BENDS FOLLOW THE ARM POLE WITHOUT A HALF-TURN ROLL PASSED')
