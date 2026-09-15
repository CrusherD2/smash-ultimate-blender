"""Read-only playback profile of the supplied reference; no blend is saved."""

from pathlib import Path
import importlib, cProfile, pstats, time, os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(
    compile(
        fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'
    )
)
reference = Path(
    os.environ.get('SUB_REFERENCE_BLEND', Path.home() / 'Downloads/Untitled3.blend')
)
if not reference.exists():
    print('SKIP reference profile: supply SUB_REFERENCE_BLEND')
    raise SystemExit(0)
bpy.ops.wm.open_mainfile(filepath=str(reference), use_scripts=False)
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
for obj in bpy.context.scene.objects:
    if obj.type == 'ARMATURE':
        print(
            'RIG COUNTS',
            obj.name,
            len(obj.pose.bones),
            sum(len(pb.constraints) for pb in obj.pose.bones),
        )
scene = bpy.context.scene
for f in range(1, 4):
    scene.frame_set(f)
profile = cProfile.Profile()
profile.enable()
start = time.perf_counter()
for f in range(1, 31):
    scene.frame_set(f)
print('PLAYBACK_SECONDS', time.perf_counter() - start)
profile.disable()
pstats.Stats(profile).strip_dirs().sort_stats('cumulative').print_stats(16)
start = time.perf_counter()
for _ in range(100):
    rig._sync_ik_fk_visibility(scene)
print('VISIBILITY_100_SECONDS', time.perf_counter() - start)
