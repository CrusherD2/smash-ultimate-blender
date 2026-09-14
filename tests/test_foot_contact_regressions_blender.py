"""Regression coverage for reverse-foot floor clearance and releasing toe pins."""
from pathlib import Path

# Reuse the existing synthetic leg/toe rig and actual addon registration.
fixture = Path(__file__).with_name('test_floor_contact_blender.py')
exec(compile(fixture.read_text().split("contact_collection =")[0], str(fixture), 'exec'))

control = arm.pose.bones['FootIKL']
control.rotation_mode = 'XYZ'
left.softness = 0
left.pin_toe = True
control.location.z = -2
for angle in (-.7, -.2, 0, .2, .7):
    control.rotation_euler.x = angle
    solved = matrix(left.solved)
    heights = [(solved @ marker.location).z for marker in (left.heel, left.toe)]
    assert min(heights) >= -1e-4, ('pinned heel penetrates', angle, heights)
    close(min(heights), 0, 'lowest sample touches floor')
    contact = solved @ left.toe.location
    anchor = matrix(left.anchor_toe).translation
    close(contact.x, anchor.x, 'toe horizontal pin x')
    close(contact.y, anchor.y, 'toe horizontal pin y')

# Existing .blend files carry the old expression; repair it at load time.
curve = next(fc for fc in left.solved.animation_data.drivers if fc.data_path == '["height"]')
curve.driver.expression = curve.driver.expression.replace(
    'z-min(hz,tz)+floor', 'z-(tz if toe_pin else min(hz,tz))+floor')
floor._restore_contacts()
assert 'z-min(hz,tz)+floor' in curve.driver.expression
assert min((matrix(left.solved) @ marker.location).z for marker in (left.heel, left.toe)) >= -1e-4

# Release clears every source of explicit/spatial attachment.
left.planted = left.auto_plant = left.pin_toe = True
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
assert bpy.ops.sub.floor_contact(action='RELEASE', control=left.control) == {'FINISHED'}
assert not (left.planted or left.auto_plant or left.pin_toe)
control.location.z = 4
close(matrix(left.solved).translation.z, matrix(left.raw).translation.z, 'released foot lifts')
floor.unregister()
print('FOOT CONTACT REGRESSIONS PASSED')
