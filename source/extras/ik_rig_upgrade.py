import math

import bpy
from bpy.app.handlers import persistent

from . import create_animation_rig as rig, ik_channels as ik
from ..anim.fcurve_compat import get_all_action_fcurves

REVISION_KEY = 'sub_ik_rig_revision'
# 2: one IK per limb matched 1:1 from FK; no correction bones or pole orbit.
# 3: the solver follows FK joints moved by location keys, so controls sit on the visible hand/foot.
CURRENT_REVISION = 3
BACKUP_KEY = 'sub_ik_update_backup'
BACKUP_SUFFIX = ' [before IK update]'
SWITCH_PATHS = ('sub_use_ik', 'sub_use_ik_arms', 'sub_use_ik_legs')
TOLERANCE = 2e-3


def needs_update(obj):
    if obj.type != 'ARMATURE' or obj.library or obj.override_library:
        return False
    revision = obj.data.get(REVISION_KEY, 0)
    return (not isinstance(revision, int) or revision < CURRENT_REVISION) and bool(list(ik.chains(obj)))


def pending_rigs(scene):
    return [obj for obj in sorted(scene.objects, key=lambda obj: obj.name) if needs_update(obj)]


def _frame_range(obj, scene):
    ranges = [action.frame_range for action in rig._iter_armature_actions(obj)]
    if obj.data.animation_data and obj.data.animation_data.action:
        ranges.append(obj.data.animation_data.action.frame_range)
    if not ranges:
        return scene.frame_current, scene.frame_current
    return (math.floor(min(scene.frame_start, *(pair[0] for pair in ranges))),
            math.ceil(max(scene.frame_end, *(pair[1] for pair in ranges))))


def _matrix_error(a, b):
    return max(abs(x - y) for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))


def _straight_limbs(obj, jobs, matrices):
    """Limb bones on near-straight limbs, with each limb's length.

    The new IK bends these very slightly toward their pole so they fold the
    right way when edited, so they may differ from the old pose by that much.
    """
    straight = {}
    for _kind, names, _target, _pole in jobs:
        path = ik.limb_path(obj, names)
        bend = ik.bend_name(obj, names)
        if bend not in path or not all(name in matrices for name in path):
            continue
        root, joint, end = (matrices[name].translation for name in (path[0], bend, path[-1]))
        length = sum((matrices[b].translation - matrices[a].translation).length for a, b in zip(path, path[1:]))
        axis = end - root
        if length < 1e-8 or axis.length < 1e-8:
            continue
        axis.normalize()
        offset = joint - root
        offset -= axis * offset.dot(axis)
        if offset.length < length * ik._STRAIGHT:
            straight.update((name, length) for name in path)
    return straight


def _nudged_within(actual, wanted, length):
    angle = actual.to_quaternion().rotation_difference(wanted.to_quaternion()).angle
    angle = min(angle, 2 * math.pi - angle)
    return angle < math.radians(1.5) and (actual.translation - wanted.translation).length < length * 0.015


def _owned_actions(obj):
    actions = []
    for id_data in (obj, obj.data):
        anim = id_data.animation_data
        if anim and anim.action and anim.action not in actions:
            actions.append(anim.action)
    return actions


def _make_backup(obj):
    """Pristine copies of every ID the update writes to; also the rollback source."""
    actions = [(action, action.copy()) for action in _owned_actions(obj)]
    data = obj.data.copy()
    backup = obj.copy()
    backup.data = data
    copies = dict(actions)
    for id_data in (backup, data):
        anim = id_data.animation_data
        if anim and anim.action in copies:
            slot = getattr(anim, 'action_slot', None)
            identifier = slot.identifier if slot else None
            anim.action = copies[anim.action]
            # Reuse the original slot; auto-assignment would add an empty one for the new name.
            if identifier and identifier in anim.action.slots:
                anim.action_slot = anim.action.slots[identifier]
    for item, name in ((backup, obj.name), (data, obj.data.name),
                       *((copy, action.name) for action, copy in actions)):
        item.name = name + BACKUP_SUFFIX
        item.use_fake_user = True
    return backup, actions


def _rollback(obj, backup, actions):
    """Swap every user of the edited IDs back to the pristine copies."""
    name, data_name = obj.name, obj.data.name
    edited_data = obj.data
    for edited, pristine in actions:
        action_name = edited.name
        edited.user_remap(pristine)
        bpy.data.actions.remove(edited)
        pristine.use_fake_user = False
        pristine.name = action_name
    obj.user_remap(backup)
    bpy.data.objects.remove(obj)
    edited_data.user_remap(backup.data)
    bpy.data.armatures.remove(edited_data)
    for item, item_name in ((backup, name), (backup.data, data_name)):
        item.use_fake_user = False
        item.name = item_name
    return backup


def _switch_snapshot(obj):
    curves = {}
    for id_data, id_type in ((obj.data, 'ARMATURE'), (obj, 'OBJECT')):
        anim = id_data.animation_data
        if not (anim and anim.action):
            continue
        for fc in get_all_action_fcurves(anim.action, id_type=id_type):
            if fc.data_path in SWITCH_PATHS and fc.data_path not in curves:
                curves[fc.data_path] = (fc.extrapolation, [
                    (tuple(k.co), k.interpolation, k.easing, tuple(k.handle_left), tuple(k.handle_right),
                     k.handle_left_type, k.handle_right_type) for k in fc.keyframe_points])
    values = {path: getattr(obj.data, path) for path in SWITCH_PATHS if hasattr(obj.data, path)}
    return curves, values


def _restore_switches(obj, snapshot):
    curves, values = snapshot
    rig._remove_ik_fk_switch_keys(obj)
    rig._IK_FK_APPLYING = True
    try:
        for path, value in values.items():
            setattr(obj.data, path, value)
    finally:
        rig._IK_FK_APPLYING = False
    for path, (extrapolation, keys) in curves.items():
        _, fc = rig._bool_switch_fcurve(obj, path)
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(keys))
        for point, (co, interpolation, easing, left, right, left_type, right_type) in zip(fc.keyframe_points, keys):
            point.co, point.interpolation, point.easing = co, interpolation, easing
            point.handle_left_type, point.handle_right_type = left_type, right_type
            point.handle_left, point.handle_right = left, right
        fc.extrapolation = extrapolation
        fc.update()


def _limb_bake_names(obj, jobs):
    """Bones per chain that the IK result moves, keyed by the chain's target."""
    from . import ik_floor_contact
    root = obj.pose.bones.get('Trans')
    body = root.constraints.get(ik_floor_contact.BODY_CONSTRAINT) if root else None
    limbs = {}
    for kind, names, target, _ in jobs:
        bones = list(ik.limb_path(obj, names))
        if kind == 'LEGS':
            bones.extend(ik.connected_toe_bones(obj, names))
            if body:
                bones.append('Trans')
        limbs[target] = bones
    return limbs, body


def _depth_order(obj, names):
    return sorted(names, key=lambda name: len(obj.pose.bones[name].parent_recursive))


def _bake_intended(obj, names, intended):
    from . import pose_math
    from ..anim.fcurve_bulk import PoseKeyWriter
    order = _depth_order(obj, names)
    writer = PoseKeyWriter(obj)
    for current, matrices in intended.items():
        for name in order:
            pb = obj.pose.bones[name]
            parent = matrices.get(pb.parent.name) if pb.parent else None
            basis = pose_math.basis_from_world(pb, matrices[name], parent)
            if basis is None:
                raise RuntimeError(f'{name} uses bone inheritance the update cannot bake; rig restored')
            writer.stash_matrix_basis(pb, current, basis)
    writer.flush()


def update_in_place(context, obj):
    if not needs_update(obj):
        raise RuntimeError('This rig does not need an IK update')
    if context.mode not in {'OBJECT', 'POSE'}:
        raise RuntimeError('Leave Edit Mode before updating the IK rig')
    if obj.animation_data and any(track.strips for track in obj.animation_data.nla_tracks):
        raise RuntimeError('Rigs with NLA strips or animation layers cannot be updated automatically')
    scene = context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    start_before, end_before = scene.frame_start, scene.frame_end
    active = context.view_layer.objects.active
    active_name = active.name if active else None
    selected = [item.name for item in context.selected_objects]
    mode = active.mode if active else 'OBJECT'
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    start, end = _frame_range(obj, scene)
    jobs = list(ik.chains(obj))
    kinds = {job[0] for job in jobs}
    limb_kind = next(iter(kinds)) if len(kinds) == 1 else 'BOTH'
    custom_records = obj.get('sub_custom_ik_chains', '[]')
    # Per-pole settings live on the control bones, which are rebuilt.
    pulls = {pole: getattr(obj.data.bones[pole], ik.ARM_PULL_PROPERTY)
             for _, _, _, pole in jobs
             if pole in obj.data.bones and hasattr(obj.data.bones[pole], ik.ARM_PULL_PROPERTY)}
    controls = set(rig._ik_control_bone_names(obj))
    controls.update(name for _, _, target, pole in jobs
                    for name in (target, pole, *ik.pole_rotation_names(pole)))
    names = [bone.name for bone in obj.data.bones
             if bone.name not in controls
             and not bone.name.startswith((ik.PREFIX, ik.PULL_PREFIX, ik.CORRECTION_PREFIX))]
    limbs, body = _limb_bake_names(obj, jobs)
    outputs = [con for _, con, _ in (*ik.outputs(obj), *ik.toe_outputs(obj))] + ([body] if body else [])
    visual, fk_only, factors = {}, {}, {}
    objects_before = set(bpy.data.objects)
    backup = actions = None
    try:
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context):
            rig.pause_ik_fk_mute_sync(True)
            states = [(con, con.mute) for con in outputs]
            try:
                for current in range(start, end + 1):
                    scene.frame_set(current)
                    context.view_layer.update()
                    visual[current] = {name: obj.pose.bones[name].matrix.copy() for name in names}
                    factors[current] = {kind: float(getattr(obj.data, 'sub_use_ik_' + kind.lower(), 0.0) or 0.0)
                                        for kind in ('ARMS', 'LEGS')}
                for con in outputs:
                    con.mute = True
                for current in range(start, end + 1):
                    scene.frame_set(current)
                    context.view_layer.update()
                    fk_only[current] = {name: obj.pose.bones[name].matrix.copy()
                                        for bones in limbs.values() for name in bones}
            finally:
                for con, mute in states:
                    con.mute = mute
            # Where the old IK moved a limb, its pose carries the old solver's twist;
            # those frames are re-solved by the new rig from the same control placement.
            retarget = {target: {f for f in visual
                                 # Old rigs that already reproduce their FK keys are matched from FK.
                                 if any(_matrix_error(visual[f][name], fk_only[f][name]) > TOLERANCE
                                        for name in bones)}
                        for target, bones in limbs.items()}
            retarget = {target: active for target, active in retarget.items() if active}
            bake = sorted({name for target in retarget for name in limbs[target]})
            switches = _switch_snapshot(obj)
            backup, actions = _make_backup(obj)
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            rig._activate_armature(context, obj)
            if obj.animation_data is None or obj.animation_data.action is None:
                from ..blender_compat import assign_action
                assign_action(obj.animation_data_create(), bpy.data.actions.new(obj.name + ' Action'))
            ik.remove(context, obj)
            obj['sub_custom_ik_chains'] = custom_records
            scene.frame_start, scene.frame_end = start, end
            scene.frame_set(frame, subframe=subframe)
            ik.create_controls(context, obj, limb_kind, _defer_match=True)
            for pole, value in pulls.items():
                if pole in obj.data.bones:
                    setattr(obj.data.bones[pole], ik.ARM_PULL_PROPERTY, value)
            kind_of = {target: kind for kind, _, target, _ in jobs}
            # The new rig matches FK 1:1, so what the old IK showed becomes FK keys
            # wherever IK fully drove the limb; partly blended frames keep their FK.
            fk_world = {}
            for current, matrices in visual.items():
                fk_world[current] = dict(matrices)
                for target in retarget:
                    if factors[current][kind_of[target]] < 1.0 - 1e-6:
                        fk_world[current].update((name, fk_only[current][name]) for name in limbs[target])
            if bake:
                _bake_intended(obj, bake, fk_world)
            ik.match(context, obj, limb_kind, entire=True, key=True)
            from .anim_rig_extras import mark_ik_matched
            mark_ik_matched(obj, limb_kind)
            _restore_switches(obj, switches)
            rig.pause_ik_fk_mute_sync(paused)
            for current, matrices in visual.items():
                if any(1e-6 < value < 1.0 - 1e-6 for value in factors[current].values()):
                    continue  # A partial IK/FK blend now blends toward FK-identical IK.
                scene.frame_set(current)
                context.view_layer.update()
                straight = _straight_limbs(obj, jobs, matrices)
                for name, matrix in matrices.items():
                    actual = obj.pose.bones[name].matrix
                    error = _matrix_error(actual, matrix)
                    if (math.isfinite(error) and error > TOLERANCE and name in straight
                            and _nudged_within(actual, matrix, straight[name])):
                        continue
                    if not math.isfinite(error) or error > TOLERANCE:
                        raise RuntimeError(f'{name} moved by {error:.4f} at frame {current}; rig restored')
            obj.data[REVISION_KEY] = CURRENT_REVISION
            obj[BACKUP_KEY] = backup.name
            return obj
    except Exception:
        if backup is not None:
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for item in set(bpy.data.objects) - objects_before - {backup}:
                bpy.data.objects.remove(item)
            obj = _rollback(obj, backup, actions)
        raise
    finally:
        rig.pause_ik_fk_mute_sync(paused)
        scene.frame_start, scene.frame_end = start_before, end_before
        scene.frame_set(frame, subframe=subframe)
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for item in context.selected_objects:
            item.select_set(False)
        for item_name in selected:
            if item_name in context.view_layer.objects:
                context.view_layer.objects[item_name].select_set(True)
        restored = context.view_layer.objects.get(active_name) if active_name else None
        context.view_layer.objects.active = restored
        if restored and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=mode)
        rig._IK_VIS_CACHE.clear()


class SUB_OT_update_old_ik(bpy.types.Operator):
    bl_idname = 'sub.update_old_ik'
    bl_label = 'Update IK Rig'
    bl_description = 'Rebuild the old IK rig in place and match it to the current animation'
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: bpy.props.StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        self.layout.label(text='The IK controls are rebuilt on this rig; names and links stay the same.')
        self.layout.label(text='IK controls keep their animation; the new rig re-solves the limbs.')
        self.layout.label(text='Hidden solver data is reset, so the old twist is not carried over.')
        self.layout.label(text='IK/FK switch keys are kept.')
        self.layout.label(text='A backup of the rig and its actions is saved in this file.')
        self.layout.label(text='If the result does not match, the rig is restored automatically.')

    def execute(self, context):
        obj = context.scene.objects.get(self.rig_name) if self.rig_name else context.object
        if obj is None:
            self.report({'ERROR'}, 'The old IK rig is no longer available')
            return {'CANCELLED'}
        try:
            update_in_place(context, obj)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Updated ' + obj.name + '; backup kept as ' + obj[BACKUP_KEY])
        return {'FINISHED'}


MISC_PANEL = 'SUB_PT_misc_utilities'


def draw_update_box(layout, context):
    """Pending-update box drawn at the top of the Misc. panel."""
    candidates = pending_rigs(context.scene)
    if not candidates:
        return False
    box = layout.box()
    box.alert = True
    box.label(text='IK Rig Update Available', icon='ERROR')
    for obj in candidates:
        box.operator(SUB_OT_update_old_ik.bl_idname, text='Update: ' + obj.name,
                     icon='FILE_REFRESH').rig_name = obj.name
    box.label(text='A backup is kept when updating.')
    return True


def _open_misc_panel():
    """Top-level panel open state has no RNA; re-registering resets it to bl_options."""
    from .. import panel_order
    cls = next((item for panel_id, item in panel_order._iter_ultimate_panel_classes()
                if panel_id == MISC_PANEL), None)
    if cls is None:
        return
    options = set(cls.bl_options)
    cls.bl_options = options - {'DEFAULT_CLOSED'}
    try:
        panel_order._reregister([MISC_PANEL])
    finally:
        cls.bl_options = options


def _sidebars(window_manager):
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                yield area, next(region for region in area.regions if region.type == 'UI')


def _select_ultimate_tab(attempts=10):
    """A freshly opened sidebar only knows its tabs after it has drawn once."""
    pending = False
    for area, region in _sidebars(bpy.context.window_manager):
        try:
            region.active_panel_category = 'Ultimate'
        except (TypeError, ValueError, AttributeError):
            pending = True
        area.tag_redraw()
    if pending and attempts > 1:
        bpy.app.timers.register(lambda: _select_ultimate_tab(attempts - 1), first_interval=0.1)
    return None


def reveal_update_button(context):
    """Open the sidebar on the Ultimate tab with Misc. expanded at the update button."""
    for area, _region in _sidebars(context.window_manager):
        area.spaces.active.show_region_ui = True
        area.tag_redraw()
    _open_misc_panel()
    bpy.app.timers.register(_select_ultimate_tab, first_interval=0.05)


def _reveal_if_still_pending():
    # Runs after the popup's own button handling, so a clicked update has already finished.
    if pending_rigs(bpy.context.scene):
        reveal_update_button(bpy.context)
    return None


class SUB_OT_ik_update_prompt(bpy.types.Operator):
    bl_idname = 'sub.ik_update_prompt'
    bl_label = 'IK Rig Update Available'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        candidates = pending_rigs(context.scene)
        if not candidates:
            return {'CANCELLED'}

        def draw(menu, _context):
            menu.layout.label(text='Older IK rigs detected. A backup is kept when updating.')
            for obj in candidates:
                menu.layout.operator(SUB_OT_update_old_ik.bl_idname,
                                     text='Update: ' + obj.name).rig_name = obj.name
            menu.layout.label(text='Also available later in Ultimate > Misc.')
        # Register before the popup so the popup's handler sits in front and blocks this one
        # until the popup (and any update dialog it opens) has closed.
        context.window_manager.modal_handler_add(self)
        context.window_manager.popup_menu(draw, title='IK Rig Update Available', icon='INFO')
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'TIMER', 'TIMER_REPORT', 'NONE'}:
            return {'PASS_THROUGH'}
        bpy.app.timers.register(_reveal_if_still_pending, first_interval=0.2)
        return {'FINISHED', 'PASS_THROUGH'}


def _show_update_prompt():
    if bpy.app.background:
        return None
    wm = bpy.context.window_manager
    window = bpy.context.window or (wm.windows[0] if wm and wm.windows else None)
    if window is None or not pending_rigs(window.scene):
        return None
    area = next((item for item in window.screen.areas if item.type == 'VIEW_3D'), None)
    with bpy.context.temp_override(window=window, screen=window.screen, area=area):
        bpy.ops.sub.ik_update_prompt('INVOKE_DEFAULT')
    return None


@persistent
def _load_post(_dummy):
    if not bpy.app.timers.is_registered(_show_update_prompt):
        bpy.app.timers.register(_show_update_prompt, first_interval=1.0)


def register():
    bpy.utils.register_class(SUB_OT_update_old_ik)
    bpy.utils.register_class(SUB_OT_ik_update_prompt)
    bpy.app.handlers.load_post.append(_load_post)
    _load_post(None)


def unregister():
    if bpy.app.timers.is_registered(_show_update_prompt):
        bpy.app.timers.unregister(_show_update_prompt)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    bpy.utils.unregister_class(SUB_OT_ik_update_prompt)
    bpy.utils.unregister_class(SUB_OT_update_old_ik)
