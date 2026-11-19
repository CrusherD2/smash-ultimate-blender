from pathlib import Path

fixture = Path(__file__).with_name('test_ik_arm_pole_alignment_blender.py')
setup, checks = fixture.read_text().split("bpy.ops.object.mode_set(mode='POSE')", 1)
exec(compile(setup, str(fixture), 'exec'))
for index, suffix in enumerate(suffixes):
    side = 1 if suffix.startswith('L') else -1
    shoulder = data.edit_bones['Shoulder' + suffix]
    elbow = data.edit_bones['Arm' + suffix]
    # Jiren's joints are effectively collinear, with separate, slightly offset bone tails.
    shoulder.tail = (side * 6, -.06, 15)
    elbow.head = (side * 6, (index - 2) * 1e-7, 15 - (index + 1) * 1e-6)
    elbow.tail = (side * 10, .056, 15)
exec(compile("bpy.ops.object.mode_set(mode='POSE')" + checks, str(fixture), 'exec'))
print('NEAR-STRAIGHT ARMS IGNORE IMPORT NOISE WHEN CALIBRATING POLE ANGLES PASSED')
