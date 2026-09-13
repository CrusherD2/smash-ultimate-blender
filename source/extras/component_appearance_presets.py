"""Portable controller appearance snapshots; no external widget objects required."""

import hashlib
import json
import math
import bpy
from mathutils import Matrix


def validate(records):
    if not isinstance(records, dict):
        raise ValueError('Invalid preset appearances')
    for name, data in records.items():
        if not isinstance(name, str) or not isinstance(data, dict):
            raise ValueError('Invalid controller appearance')
        if not {'vertices', 'edges', 'faces'} <= set(data):
            raise ValueError('Missing widget geometry')
        for key in ('scale', 'offset', 'rotation'):
            values = data.get(key)
            if (
                not isinstance(values, list)
                or len(values) != 3
                or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in values
                )
            ):
                raise ValueError('Invalid widget transform')
        if not isinstance(data.get('enabled', True), bool) or not isinstance(
            data.get('bone_size', False), bool
        ):
            raise ValueError('Invalid widget size mode')
        vertices = data.get('vertices', [])
        if not isinstance(vertices, list) or any(
            not isinstance(v, list)
            or len(v) != 3
            or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v)
            for v in vertices
        ):
            raise ValueError('Invalid widget geometry')
        for key, size in (('edges', 2), ('faces', None)):
            elements = data.get(key, [])
            if not isinstance(elements, list) or any(
                not isinstance(e, list)
                or (len(e) != size if size else len(e) < 3)
                or any(not isinstance(i, int) or i < 0 or i >= len(vertices) for i in e)
                for e in elements
            ):
                raise ValueError('Invalid widget indices')
        adjustment = data.get('adjustment')
        if adjustment is not None and (
            not isinstance(adjustment, list)
            or len(adjustment) != 16
            or any(
                not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in adjustment
            )
        ):
            raise ValueError('Invalid functional control transform')
    return records


def capture(editor):
    records = json.loads(editor.appearances)
    obj = editor.armature
    if not obj:
        return records
    from ..blender_compat import is_pose_bone_selected

    for pb in obj.pose.bones:
        if not pb.bone.get('sub_shape_override') and not is_pose_bone_selected(pb):
            continue
        widget = pb.custom_shape
        if widget and widget.type != 'MESH':
            continue
        if (
            widget is None
            and not pb.bone.get('sub_shape_override')
            and pb.name not in records
        ):
            continue
        records[pb.name] = dict(
            enabled=widget is not None,
            scale=list(pb.custom_shape_scale_xyz),
            offset=list(pb.custom_shape_translation),
            rotation=list(pb.custom_shape_rotation_euler),
            bone_size=pb.use_custom_shape_bone_size,
            vertices=[list(v.co) for v in widget.data.vertices] if widget else [],
            edges=[list(e.vertices) for e in widget.data.edges] if widget else [],
            faces=[list(p.vertices) for p in widget.data.polygons] if widget else [],
            adjustment=(
                list(pb.bone['sub_control_adjustment'])
                if 'sub_control_adjustment' in pb.bone
                else None
            ),
        )
    editor.appearances = json.dumps(records)
    return records


def apply(context, obj, records):
    validate(records)
    from .create_animation_rig import _ensure_widget_object, _activate_armature
    from .control_appearance import remember

    changes = {}
    for name, data in records.items():
        pb = obj.pose.bones.get(name)
        if not pb:
            continue
        geometry = {k: data[k] for k in ('vertices', 'edges', 'faces')}
        digest = hashlib.sha256(
            json.dumps(geometry, sort_keys=True).encode()
        ).hexdigest()[:20]
        widget = _ensure_widget_object(
            context, 'Preset_' + digest, data['vertices'], data['edges']
        )
        if data['faces'] and not widget.data.polygons:
            widget.data.clear_geometry()
            widget.data.from_pydata(data['vertices'], data['edges'], data['faces'])
            widget.data.update()
        pb.custom_shape = widget if data.get('enabled', True) else None
        pb.custom_shape_scale_xyz = data['scale']
        pb.custom_shape_translation = data['offset']
        pb.custom_shape_rotation_euler = data['rotation']
        pb.use_custom_shape_bone_size = data['bone_size']
        remember(pb)
        identity = [v for row in Matrix.Identity(4) for v in row]
        wanted = data.get('adjustment') or identity
        if list(pb.bone.get('sub_control_adjustment', identity)) != wanted:
            changes[name] = wanted
    if changes:
        _activate_armature(context, obj)
        bpy.ops.object.mode_set(mode='EDIT')
        for name, wanted in changes.items():
            b = obj.data.edit_bones[name]
            raw = b.get('sub_control_adjustment')
            old = (
                Matrix([raw[i : i + 4] for i in range(0, 16, 4)])
                if raw
                else Matrix.Identity(4)
            )
            new = Matrix([wanted[i : i + 4] for i in range(0, 16, 4)])
            if 'sub_control_rest' not in b:
                b['sub_control_rest'] = [v for row in b.matrix for v in row]
            b.matrix = b.matrix @ old.inverted_safe() @ new
            b['sub_control_adjustment'] = wanted
        bpy.ops.object.mode_set(mode='POSE')


def save_changes(context, force=False):
    editor = context.scene.sub_component_editor
    if not editor.armature or not editor.components:
        return
    from .custom_components import save_preset

    capture(editor)
    if editor.auto_save_appearance or force:
        save_preset(editor)
        editor.appearance_status = 'Appearance saved to preset'
    else:
        editor.appearance_status = 'Appearance changed ? save preset to keep it'


_owner = object()
_pending = set()


def _changed():
    # RNA notifications come from user edits, not dependency graph evaluation.
    scene = bpy.context.scene
    if scene and any(
        w.screen.get('sub_components_window')
        for w in bpy.context.window_manager.windows
    ):
        _pending.add(scene.name)
        if not bpy.app.timers.is_registered(_flush):
            bpy.app.timers.register(_flush, first_interval=0.4)


def _flush():
    from .custom_components import save_preset

    for name in list(_pending):
        scene = bpy.data.scenes.get(name)
        if not scene:
            continue
        editor = scene.sub_component_editor
        if editor.armature and editor.components:
            from .control_appearance import remember
            from ..blender_compat import is_pose_bone_selected

            for pb in editor.armature.pose.bones:
                if (
                    is_pose_bone_selected(pb)
                    or editor.armature.data.bones.active == pb.bone
                ) and pb.custom_shape:
                    remember(pb)
            try:
                capture(editor)
                if editor.auto_save_appearance:
                    save_preset(editor)
                    editor.appearance_status = 'Appearance saved to preset'
            except (OSError, ValueError) as exc:
                editor.appearance_status = 'Could not save appearance: ' + str(exc)
    _pending.clear()
    return None


@bpy.app.handlers.persistent
def _subscribe(_dummy=None):
    bpy.msgbus.clear_by_owner(_owner)
    for prop in (
        'custom_shape',
        'custom_shape_scale_xyz',
        'custom_shape_translation',
        'custom_shape_rotation_euler',
        'use_custom_shape_bone_size',
    ):
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.PoseBone, prop), owner=_owner, args=(), notify=_changed
        )


def register():
    _subscribe()
    bpy.app.handlers.load_post.append(_subscribe)


def unregister():
    bpy.msgbus.clear_by_owner(_owner)
    if _subscribe in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_subscribe)
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
    _pending.clear()
