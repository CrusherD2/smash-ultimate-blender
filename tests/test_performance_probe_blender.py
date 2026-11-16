"""Playback profiling attributes frame handler time to the handler that spent it."""
from pathlib import Path
import time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
probe = importlib.import_module(MODULE + '.source.extras.performance_probe')


def slow_probe_handler(scene, *_):
    time.sleep(0.002)


bpy.app.handlers.frame_change_post.append(slow_probe_handler)
scene = bpy.context.scene
probe.start(10)
for frame in range(1, 12):
    scene.frame_set(frame)
assert not probe.running()
assert probe._record not in bpy.app.handlers.frame_change_pre
report = bpy.data.texts[probe.REPORT_NAME].as_string()
entries = report.split('Entry points')[1].split('Slowest')[0]
assert 'slow_probe_handler' in entries, report
row = next(line for line in entries.splitlines() if 'slow_probe_handler' in line)
assert float(row.split()[0]) >= 1.5, row
assert 'Frames: 10' in report, report
assert probe._evaluated not in bpy.app.handlers.frame_change_post
evaluation = float(report.split('depsgraph): ')[1].split(' ms')[0])
# The slow post handler is add-on time, not Blender evaluation time.
assert 0 <= evaluation < 1.5, report
bpy.app.handlers.frame_change_post.remove(slow_probe_handler)
print('PERFORMANCE_PROBE_OK')

# The suspect comparison finds a slow visibility driver and restores everything.
mesh = bpy.data.meshes.new('Probe mesh')
obj = bpy.data.objects.new('Probe mesh', mesh)
scene.collection.objects.link(obj)
data = bpy.data.armatures.new('Probe rig')
rig = bpy.data.objects.new('Probe rig', data)
scene.collection.objects.link(rig)
modifier = obj.modifiers.new('Armature', 'ARMATURE')
modifier.object = rig


def slow_probe_visibility(value):
    time.sleep(0.003)
    return 0.0


bpy.app.driver_namespace['slow_probe_visibility'] = slow_probe_visibility
curve = obj.driver_add('hide_viewport')
curve.driver.expression = 'slow_probe_visibility(frame)'
scene.frame_start, scene.frame_end, scene.frame_current = 1, 20, 7
report = probe.compare_suspects(scene, 20)
row = next(line for line in report.splitlines() if 'Mesh visibility drivers' in line)
assert float(row.split()[1]) >= 2.0, report
assert not curve.mute and modifier.show_viewport, report
assert scene.frame_current == 7
assert probe._record not in bpy.app.handlers.frame_change_pre
assert len(bpy.app.handlers.frame_change_post) > 0
print(report)
print('PERFORMANCE_SUSPECTS_OK')
