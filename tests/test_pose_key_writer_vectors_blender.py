from pathlib import Path
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
bulk = importlib.import_module(MODULE + '.source.anim.fcurve_bulk')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
obj = bpy.data.objects.new('Writer test', None)
bpy.context.scene.collection.objects.link(obj)
writer = bulk.PoseKeyWriter(obj)
writer.stash_channel('location', 0, 1, 2.0, 'Original group')
writer.stash_vector('location', 2, (3.0, 4.0, 5.0), 'Other group')
writer.stash_vector('location', 3, (value for value in (6.0, 7.0, 8.0)))
assert writer.flush() == 7
assert not writer

def values(index):
    fc = curves.find_fcurve(obj.animation_data.action, 'location', index=index)
    return [(tuple(key.co), key.interpolation) for key in fc.keyframe_points]

assert values(0) == [((1.0, 2.0), 'LINEAR'), ((2.0, 3.0), 'LINEAR'), ((3.0, 6.0), 'LINEAR')]
assert values(1) == [((2.0, 4.0), 'LINEAR'), ((3.0, 7.0), 'LINEAR')]
fc = curves.find_fcurve(obj.animation_data.action, 'location', index=0)
fc.keyframe_points[0].interpolation = 'CONSTANT'
writer.stash_vector('location', 2, (9.0, 10.0, 11.0))
assert writer.flush() == 3
assert values(0) == [((1.0, 2.0), 'CONSTANT'), ((2.0, 9.0), 'LINEAR'), ((3.0, 6.0), 'LINEAR')]
assert values(1) == [((2.0, 10.0), 'LINEAR'), ((3.0, 7.0), 'LINEAR')]
assert writer.flush() == 0
print('VECTOR CACHE, GENERATORS, MIXED CHANNELS, WRITER REUSE AND EXISTING KEYS PASSED')
