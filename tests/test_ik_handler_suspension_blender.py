"""The add-on's own viewport handlers must not fire during IK matching.

They are UI/viewport synchronisation only, but each runs once per depsgraph
update and matching performs thousands of those. Suspension must be invisible
in the output and must restore every handler, in order, afterwards.
"""
from pathlib import Path
import os
import importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'

WATCHED = (
    ('source.anim.motion_list_ui', 'motion_list_auto_sync_handler'),
    ('source.extras.stage_tools.light_nuanmb', '_stage_light_depsgraph_update'),
    ('source.retargeting', 'auto_detect_smash_armature'),
)
LISTS = ('frame_change_pre', 'frame_change_post',
         'depsgraph_update_pre', 'depsgraph_update_post')

wanted = {MODULE + '.' + module + '.' + name for module, name in WATCHED}
calls = {}
installed = []


def identity(function):
    return getattr(function, '__module__', '') + '.' + getattr(function, '__name__', '')


def wrap(function):
    """Blender chooses how many arguments to pass by inspecting the handler,
    so the counter must declare the same arity as the function it replaces."""
    name = identity(function)
    if function.__code__.co_argcount <= 1:
        def counting(scene):
            calls[name] = calls.get(name, 0) + 1
            return function(scene)
    else:
        def counting(scene, depsgraph):
            calls[name] = calls.get(name, 0) + 1
            return function(scene, depsgraph)
    # Keep the identity the suspension logic matches on.
    counting.__module__ = function.__module__
    counting.__name__ = function.__name__
    return counting


# Loading a file clears handlers that are not @persistent, so the fixture must
# be open before the counters are installed.
bpy.ops.wm.open_mainfile(filepath=str(baseline))

for listname in LISTS:
    handlers = getattr(bpy.app.handlers, listname)
    for index, function in enumerate(list(handlers)):
        if identity(function) in wanted:
            replacement = wrap(function)
            handlers[index] = replacement
            installed.append((listname, index, function, replacement))

print('WATCHED_HANDLERS_INSTALLED', sorted(identity(f) for _, _, f, _ in installed), flush=True)
assert installed, 'no watched handlers were registered; check the module paths'
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ik.create_controls(bpy.context, obj, 'BOTH')
start = bpy.context.scene.frame_start


def match_over(frames):
    """Return per-handler call counts for a match spanning `frames` frames."""
    bpy.context.scene.frame_end = start + frames - 1
    calls.clear()
    assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT', cleanup_mode='BOTH',
                                         entire_animation=True) == {'FINISHED'}
    return dict(calls)


# A few calls legitimately remain: the operator evaluates the scene before and
# after match() suspends anything. What must not survive is any call inside the
# per-frame loop, so the count has to be constant in the frame count rather
# than merely small.
short = match_over(16)
long = match_over(48)

restored = []
for listname, index, _, replacement in installed:
    handlers = getattr(bpy.app.handlers, listname)
    restored.append(list(handlers).index(replacement) == index)

for listname, index, function, _ in installed:
    getattr(bpy.app.handlers, listname)[index] = function

print('HANDLER_CALLS_16_FRAMES', short, flush=True)
print('HANDLER_CALLS_48_FRAMES', long, flush=True)
assert short == long, (short, long)
assert set(short) == {identity(f) for _, _, f, _ in installed}, short
assert all(restored), restored
print('HANDLER_SUSPENSION_OK', flush=True)
