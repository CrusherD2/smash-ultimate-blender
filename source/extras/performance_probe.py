"""Measure which Python callbacks cost time during viewport playback."""
import cProfile
from pathlib import Path
import pstats
from time import perf_counter

import bpy
from bpy.props import IntProperty

REPORT_NAME = 'Smash Performance Report'
_ROOT = Path(__file__).resolve().parents[2]
_state = {}


def running():
    return 'profiler' in _state


def _label(func):
    filename, line, name = func
    path = Path(filename)
    if path.is_relative_to(_ROOT):
        return f'{path.relative_to(_ROOT).as_posix()}:{line} {name}'
    return f'{path.name}:{line} {name}  (outside this add-on)'


def build_report(stats, stamps, evaluated=()):
    frames = max(len(stamps) - 1, 1)
    elapsed = stamps[-1] - stamps[0] if len(stamps) > 1 else 0.0
    gaps = [b - a for a, b in zip(stamps, stamps[1:])] or [0.0]
    python = sum(row[2] for row in stats.values())
    frame_ms = elapsed / frames * 1000
    python_ms = python / frames * 1000
    lines = [
        REPORT_NAME,
        f'Frames: {frames}   Playback: {frames / elapsed if elapsed else 0:.1f} fps   '
        f'Average frame: {frame_ms:.2f} ms   Worst frame: {max(gaps) * 1000:.2f} ms',
        f'Python per frame: {python_ms:.2f} ms ({python_ms / frame_ms * 100 if frame_ms else 0:.0f}% of frame). '
        'The rest is Blender itself: drivers, depsgraph, drawing, and waiting for the frame rate.',
        f'Blender animation evaluation (actions, NLA, drivers, visibility, depsgraph): '
        f'{sum(evaluated) / len(evaluated) * 1000 if evaluated else 0:.2f} ms per frame. '
        'The rest of the frame after that is add-on handlers, viewport drawing and waiting.',
        'Profiling adds overhead, so fps here is lower than normal. Compare the rows with each other.',
        '',
        'Entry points (handlers, timers, panel draws) - ms per frame, calls per frame:',
    ]
    # Blender calls handlers, timers and draws from C, so they have no Python caller.
    roots = [(ct, nc, func) for func, (_, nc, _, ct, callers) in stats.items()
             if func[0] != '~' and all(caller[0] == '~' for caller in callers)]
    for ct, nc, func in sorted(roots, key=lambda row: (-row[0], _label(row[2])))[:25]:
        lines.append(f'  {ct / frames * 1000:8.3f} ms  {nc / frames:6.1f}x  {_label(func)}')
    lines += ['', 'Slowest add-on functions by own time - ms per frame, calls per frame:']
    own = [(tt, nc, func) for func, (_, nc, tt, _, _) in stats.items()
           if func[0] != '~' and Path(func[0]).is_relative_to(_ROOT)]
    for tt, nc, func in sorted(own, key=lambda row: (-row[0], _label(row[2])))[:25]:
        lines.append(f'  {tt / frames * 1000:8.3f} ms  {nc / frames:6.1f}x  {_label(func)}')
    return '\n'.join(lines) + '\n'


def _record(scene, *_):
    if not running():
        return
    _state['stamps'].append(perf_counter())
    _state['pending'] = _state['stamps'][-1]
    if len(_state['stamps']) > _state['frames']:
        finish()


def _evaluated(scene, *_):
    started = _state.pop('pending', None) if running() else None
    if started is not None:
        _state['evaluated'].append(perf_counter() - started)


def start(frames):
    finish(write=False)
    _state.update(profiler=cProfile.Profile(), stamps=[], evaluated=[], frames=frames)
    bpy.app.handlers.frame_change_pre.append(_record)
    # Run first after evaluation so other add-on handlers are not counted as Blender time.
    bpy.app.handlers.frame_change_post.insert(0, _evaluated)
    _state['profiler'].enable()


def finish(*, write=True):
    if _record in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_record)
    if _evaluated in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_evaluated)
    profiler = _state.pop('profiler', None)
    stamps = _state.pop('stamps', [])
    evaluated = _state.pop('evaluated', [])
    _state.clear()
    if profiler is None:
        return None
    profiler.disable()
    if not write:
        return None
    report = build_report(pstats.Stats(profiler).stats, stamps, evaluated)
    text = bpy.data.texts.get(REPORT_NAME) or bpy.data.texts.new(REPORT_NAME)
    text.clear()
    text.write(report)
    print(report)
    return report


class SUB_OT_profile_playback(bpy.types.Operator):
    bl_idname = 'sub.profile_playback'
    bl_label = 'Profile Playback'
    bl_description = ('Play the timeline and time every add-on handler, timer and panel. '
                      f'The result is written to the "{REPORT_NAME}" text')

    frames: IntProperty(name='Frames', default=240, min=30, max=5000)

    def execute(self, context):
        if running():
            finish()
            self.report({'INFO'}, f'Report written to the "{REPORT_NAME}" text')
            return {'FINISHED'}
        start(self.frames)
        screen = context.screen
        if screen is not None and not screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        self.report({'INFO'}, f'Profiling {self.frames} frames of playback')
        return {'FINISHED'}


def _suspects(scene):
    meshes = sorted((obj for obj in scene.objects if obj.type == 'MESH'), key=lambda obj: obj.name)
    def drivers(owner, paths=None):
        animation = owner.animation_data if owner else None
        return [(curve, 'mute', True) for curve in (animation.drivers if animation else ())
                if paths is None or curve.data_path in paths]
    materials = sorted({slot.material for obj in meshes for slot in obj.material_slots
                        if slot.material and slot.material.node_tree}, key=lambda mat: mat.name)
    armatures = sorted({mod.object.data for obj in meshes for mod in obj.modifiers
                        if mod.type == 'ARMATURE' and mod.object}, key=lambda data: data.name)
    groups = [
        ('Mesh visibility drivers', [change for obj in meshes
                                     for change in drivers(obj, {'hide_viewport', 'hide_render'})]),
        ('Material drivers (SAP colors/UVs)', [change for mat in materials
                                               for change in drivers(mat.node_tree)]),
        ('Armature data animation (SAP visibility/material NLA)',
         [(track, 'mute', True) for data in armatures if data.animation_data
          for track in data.animation_data.nla_tracks]),
        ('Armature deformation of meshes', [(mod, 'show_viewport', False) for obj in meshes
                                            for mod in obj.modifiers
                                            if mod.type == 'ARMATURE' and mod.show_viewport]),
        ('Other mesh modifiers', [(mod, 'show_viewport', False) for obj in meshes
                                  for mod in obj.modifiers
                                  if mod.type != 'ARMATURE' and mod.show_viewport]),
        ('Shape keys', [(obj.data.shape_keys.animation_data, 'action_influence', 0.0)
                        for obj in meshes if obj.data.shape_keys and obj.data.shape_keys.animation_data]),
    ]
    return [(label, changes) for label, changes in groups if changes]


def _time_frames(scene, frames):
    started = perf_counter()
    for frame in frames:
        scene.frame_set(frame)
    return (perf_counter() - started) / len(frames) * 1000


def compare_suspects(scene, count=60):
    """Time frame evaluation with each suspect switched off, restoring everything."""
    original = scene.frame_current
    first = scene.frame_start
    frames = [first + index % max(scene.frame_end - first + 1, 1) for index in range(count)]
    handlers = (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post)
    rows = []
    try:
        _time_frames(scene, frames)
        baseline = _time_frames(scene, frames)
        for label, changes in _suspects(scene):
            saved = [(owner, attr, getattr(owner, attr)) for owner, attr, _ in changes]
            try:
                for owner, attr, value in changes:
                    setattr(owner, attr, value)
                _time_frames(scene, frames[:5])
                rows.append((label, len(changes), _time_frames(scene, frames)))
            finally:
                for owner, attr, value in reversed(saved):
                    setattr(owner, attr, value)
        saved_handlers = [list(handler) for handler in handlers]
        try:
            for handler in handlers:
                handler.clear()
            rows.append(('All Python frame handlers (every add-on)',
                         sum(map(len, saved_handlers)), _time_frames(scene, frames)))
        finally:
            for handler, callbacks in zip(handlers, saved_handlers):
                handler.clear()
                handler.extend(callbacks)
        again = _time_frames(scene, frames)
    finally:
        scene.frame_set(original)
    lines = [
        'Smash Playback Suspects',
        f'Normal frame evaluation: {baseline:.2f} ms (re-measured at the end: {again:.2f} ms; '
        'the difference is measurement noise).',
        'Each row turns one thing off briefly, re-times the same frames, then restores it.',
        'Drawing is not included here. "Saves" is how much faster frames were without it.',
        '',
    ]
    for label, count_changed, elapsed in sorted(rows, key=lambda row: (row[2], row[0])):
        lines.append(f'  saves {baseline - elapsed:7.2f} ms   ({count_changed} items)  {label}')
    return '\n'.join(lines) + '\n'


class SUB_OT_compare_playback_suspects(bpy.types.Operator):
    bl_idname = 'sub.compare_playback_suspects'
    bl_label = 'Find Slow Animation Parts'
    bl_description = ('Briefly switch off visibility drivers, material drivers, deformation and other '
                      'suspects one at a time, time the frames, and restore everything. '
                      f'The result is added to the "{REPORT_NAME}" text')

    frames: IntProperty(name='Frames', default=60, min=10, max=1000)

    def execute(self, context):
        if running():
            self.report({'WARNING'}, 'Stop profiling playback first')
            return {'CANCELLED'}
        screen = context.screen
        if screen is not None and screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=True)
        report = compare_suspects(context.scene, self.frames)
        text = bpy.data.texts.get(REPORT_NAME) or bpy.data.texts.new(REPORT_NAME)
        text.clear()
        text.write(report)
        print(report)
        self.report({'INFO'}, f'Report written to the "{REPORT_NAME}" text')
        return {'FINISHED'}


def draw(layout):
    if running():
        layout.operator(SUB_OT_profile_playback.bl_idname, text='Stop Profiling', icon='CANCEL')
    else:
        row = layout.row(align=True)
        row.operator(SUB_OT_profile_playback.bl_idname, icon='TIME')
        row.operator(SUB_OT_compare_playback_suspects.bl_idname, icon='VIEWZOOM')


def register():
    bpy.utils.register_class(SUB_OT_profile_playback)
    bpy.utils.register_class(SUB_OT_compare_playback_suspects)


def unregister():
    finish(write=False)
    bpy.utils.unregister_class(SUB_OT_compare_playback_suspects)
    bpy.utils.unregister_class(SUB_OT_profile_playback)
