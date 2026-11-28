"""Guided retargeting wizard and bind/bake helpers."""
import bpy
import json


_REBIND_BUSY = False
_REBIND_TOKEN = 0
_SYNCING_BIND_PROPS = False
_SELECT_TOKEN = 0

def expand_last_operator():
    """Bind settings live on the Retargeting tab. Do not force the HUD.

    Setting SpaceView3D.show_region_hud from a timer crashes Blender 5.2
    (ED_area_init / rna_Space_show_region_hud_update).
    """
    tag_retargeting_redraw()


def apply_root_bind_defaults(scene, source, target, *, force_root_bone=False):
    """Default Root Animation to Bone mode; motion bone from Bind To Root mapping."""
    del source
    if getattr(scene, 'expykit_constrain_root', 'None') in {'None', ''}:
        scene.expykit_constrain_root = 'Bone'
        scene.expykit_root_cp_loc_x = True
        scene.expykit_root_cp_loc_y = True
        scene.expykit_root_cp_loc_z = True
        scene.expykit_root_cp_rot_x = True
        scene.expykit_root_cp_rot_y = True
        scene.expykit_root_cp_rot_z = True
        if hasattr(scene, 'expykit_root_use_loc_min_z'):
            scene.expykit_root_use_loc_min_z = True

    # Root motion bone lives on Bind To (constraints reference this armature).
    # Never invent "Trans" — leave empty when that Root slot is unset.
    root_name = ""
    if target is not None and getattr(target, 'type', None) == 'ARMATURE':
        try:
            root_name = (target.data.expykit_retarget.root or "").strip()
        except Exception:
            root_name = ""

    current = (getattr(scene, 'expykit_root_motion_bone', '') or "").strip()
    if force_root_bone or not current:
        scene.expykit_root_motion_bone = root_name


def view3d_override(context):
    """3D View override so bind operators work when clicked from the N-panel."""
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return None
    scene = getattr(context, "scene", None)
    view_layer = getattr(context, "view_layer", None)
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            return {
                'window': window,
                'screen': screen,
                'area': area,
                'region': region,
                'scene': scene or window.scene,
                'view_layer': view_layer or window.view_layer,
            }
    return None


def bind_keep_target(scene, target=None):
    """The Bind To armature (Smash / target). Never the source animation rig."""
    keep = getattr(scene, 'expykit_bind_to', None)
    if keep is not None and getattr(keep, 'type', None) == 'ARMATURE':
        return keep
    bound_src, bound_trg = bound_pair(scene)
    if bound_trg is not None and bound_trg != bound_src:
        return bound_trg
    if target is not None and getattr(target, 'type', None) == 'ARMATURE':
        return target
    return bound_trg


def bind_keep_drop(scene, source=None, target=None):
    """Keep Bind To. Drop the other armature of the pair."""
    keep = bind_keep_target(scene, target)
    bound_src, bound_trg = bound_pair(scene)
    drop = None
    # Prefer the pair from the bind operation that just completed. The stored
    # pair can belong to an earlier bind and used to make the old source win.
    for ob in (source, target, bound_src, bound_trg):
        if ob is not None and ob != keep:
            drop = ob
            break
    return drop, keep


def select_only_target(context, source, target):
    """Leave only the Bind To / target armature selected in pose mode."""
    scene = getattr(context, 'scene', None) or getattr(bpy.context, 'scene', None)
    keep = bind_keep_target(scene, target) if scene is not None else target
    if not keep:
        return
    drop, _keep = bind_keep_drop(scene, source, keep) if scene is not None else (source, keep)

    _select_only_armature(context, keep, drop)


def select_only_constrained(context, constrained, driver):
    """Leave selected the armature that received the retarget constraints."""
    if constrained:
        _select_only_armature(context, constrained, driver)


def _select_only_armature(context, keep, drop=None):
    """Select one armature reliably across Blender's pose-mode restoration."""

    override = view3d_override(context)
    ctx = context

    def _run():
        c = bpy.context
        view_layer = c.view_layer
        if c.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        keep_name = keep.name
        # Deselect through the view layer, not selected_objects captured while
        # in multi-object pose mode. Blender can retain the previous active
        # source in that collection until the mode switch has fully settled.
        for ob in list(getattr(view_layer, 'objects', []) or []):
            if ob is None:
                continue
            try:
                ob.select_set(False)
            except Exception:
                pass
        if drop is not None and drop.name != keep_name:
            try:
                drop.select_set(False)
            except Exception:
                pass

        try:
            keep.hide_set(False)
            keep.hide_viewport = False
        except Exception:
            pass
        view_layer.objects.active = keep
        try:
            keep.select_set(True)
        except Exception:
            pass
        try:
            bpy.ops.object.mode_set(mode='POSE')
        except Exception:
            pass
        # Some Blender versions restore the former active pose object while
        # entering pose mode. Assert the intended final state once more.
        view_layer.objects.active = keep
        try:
            keep.select_set(True)
        except Exception:
            pass
        if drop is not None and drop.name != keep_name:
            try:
                drop.select_set(False)
            except Exception:
                pass

    if override:
        try:
            with ctx.temp_override(**override):
                _run()
                return
        except Exception:
            pass
    _run()


def schedule_select_only_target(source, target):
    """Dialog close restores the source as active; re-apply after that."""
    global _SELECT_TOKEN
    _SELECT_TOKEN += 1
    token = _SELECT_TOKEN

    def _make():
        def _do():
            if token != _SELECT_TOKEN:
                return None
            try:
                select_only_target(bpy.context, source, target)
            except Exception:
                pass
            return None
        return _do

    for delay in (0.0, 0.08, 0.25):
        try:
            bpy.app.timers.register(_make(), first_interval=delay)
        except Exception:
            pass


def schedule_select_only_constrained(constrained, driver):
    """Reassert constrained-armature selection after a bind dialog closes."""
    global _SELECT_TOKEN
    _SELECT_TOKEN += 1
    token = _SELECT_TOKEN

    def _make():
        def _do():
            if token != _SELECT_TOKEN:
                return None
            try:
                select_only_constrained(bpy.context, constrained, driver)
            except Exception:
                pass
            return None
        return _do

    for delay in (0.0, 0.08, 0.25):
        try:
            bpy.app.timers.register(_make(), first_interval=delay)
        except Exception:
            pass


def clear_bound_constraints(source, target):
    """Remove only constraints created by the previous bind for this pair.

    The original operator's ``remove`` policy only considers constraint types
    that are enabled in the *new* settings. Turning Copy Location/Rotation off
    therefore left the old constraint behind, making Apply Bind Settings look
    like it did nothing.
    """
    if not source or not target:
        return 0
    copy_types = {'COPY_LOCATION', 'COPY_ROTATION', 'COPY_SCALE'}
    limit_types = {'LIMIT_LOCATION', 'LIMIT_ROTATION', 'LIMIT_SCALE'}
    removed = 0
    settings = getattr(getattr(source, 'data', None), 'expykit_retarget', None)
    root_name = getattr(settings, 'root', '') if settings is not None else ''

    for pbone in getattr(getattr(source, 'pose', None), 'bones', []) or []:
        constraints = getattr(pbone, 'constraints', None)
        if constraints is None:
            continue
        bound_here = any(
            getattr(con, 'type', '') in copy_types
            and getattr(con, 'target', None) == target
            for con in constraints
        )
        for con in reversed(constraints):
            is_pair_copy = (
                getattr(con, 'type', '') in copy_types
                and getattr(con, 'target', None) == target
            )
            # Expy adds root limit constraints alongside the target copy
            # constraint. Remove those as part of replacing that root bind.
            is_root_limit = (
                bound_here
                and bool(root_name)
                and getattr(pbone, 'name', '') == root_name
                and getattr(con, 'type', '') in limit_types
            )
            if not (is_pair_copy or is_root_limit):
                continue
            constraints.remove(con)
            removed += 1

    constraints = getattr(source, 'constraints', None)
    if constraints is not None:
        bound_object = any(
            getattr(con, 'type', '') in copy_types
            and getattr(con, 'target', None) == target
            for con in constraints
        )
        for con in reversed(constraints):
            is_pair_copy = (
                getattr(con, 'type', '') in copy_types
                and getattr(con, 'target', None) == target
            )
            is_root_limit = bound_object and getattr(con, 'type', '') in limit_types
            if not (is_pair_copy or is_root_limit):
                continue
            constraints.remove(con)
            removed += 1
    return removed


def tag_retargeting_redraw():
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, 'screen', None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _invalidate_smash_viewport():
    """Make native model visibility/pose changes effective on the next draw."""
    try:
        from ..extras import smash_viewport
        smash_viewport.on_retarget_bind_changed()
    except Exception:
        try:
            from ..extras import smash_viewport
            smash_viewport.invalidate_animation_state(redraw=True)
        except Exception:
            pass


def iter_source_meshes(source):
    """Meshes driven by or parented to the source armature."""
    if not source:
        return
    for ob in bpy.data.objects:
        if ob == source:
            continue
        if ob.parent == source:
            yield ob
            continue
        for mod in getattr(ob, 'modifiers', []):
            if mod.type == 'ARMATURE' and mod.object == source:
                yield ob
                break


def hide_source_keep_target(context, source, target):
    """Hide the bake driver and its meshes; keep the baked armature selected."""
    if source:
        source.hide_set(True)
        for ob in iter_source_meshes(source):
            ob.hide_set(True)
    _invalidate_smash_viewport()

    # Do not use select_only_target here. That helper intentionally resolves
    # Scene.expykit_bind_to, which is the driver in Expy Kit terminology. The
    # armature receiving the baked actions is ``target`` here.
    select_only_constrained(context, target, source)
    schedule_select_only_constrained(target, source)


def remember_bind_pair(scene, source, target):
    scene.expykit_bound_source = source
    scene.expykit_bound_target = target
    scene.expykit_bind_is_active = True
    _invalidate_smash_viewport()
    tag_retargeting_redraw()


def bound_pair(scene):
    source = getattr(scene, 'expykit_bound_source', None)
    target = getattr(scene, 'expykit_bound_target', None)
    if source and target and source.type == 'ARMATURE' and target.type == 'ARMATURE':
        return source, target
    return None, None


def prepare_bind_selection(context, source, target):
    """Match Bind Armatures selection: both selected, target active, pose mode."""
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

    for ob in list(context.selected_objects):
        ob.select_set(False)

    source.select_set(True)
    target.select_set(True)
    context.view_layer.objects.active = target
    try:
        bpy.ops.object.mode_set(mode='POSE')
    except Exception:
        pass


def reapply_bind_from_scene(context):
    """Re-run bind using the last pair so sidebar edits update the pose."""
    global _REBIND_BUSY, _SYNCING_BIND_PROPS
    if _REBIND_BUSY:
        return False

    scene = context.scene
    source, target = bound_pair(scene)
    if not source or not target:
        return False
    scene.expykit_bind_is_active = True

    _REBIND_BUSY = True
    try:
        clear_bound_constraints(source, target)

        def _run():
            prepare_bind_selection(context, source, target)
            result = bpy.ops.armature.expykit_constrain_to_armature(
                'EXEC_DEFAULT',
                force_dialog=False,
                from_scene=True,
            )
            return result

        override = view3d_override(context)
        if override:
            with context.temp_override(**override):
                result = _run()
        else:
            result = _run()
        if result is None or 'CANCELLED' in result:
            return False
        select_only_constrained(context, source, target)
        # Blender can restore the pre-operator multi-object pose selection after
        # this function returns. Reassert the constrained model's selection once
        # the operator and its UI event have both finished.
        schedule_select_only_constrained(source, target)
        return True
    except Exception as exc:
        print(f"Reapply bind failed: {exc}")
        return False
    finally:
        _REBIND_BUSY = False


def schedule_reapply_bind():
    """Debounce live bind-setting changes."""
    global _REBIND_TOKEN
    _REBIND_TOKEN += 1
    token = _REBIND_TOKEN

    def _do():
        if token != _REBIND_TOKEN:
            return None
        try:
            reapply_bind_from_scene(bpy.context)
        except Exception:
            pass
        return None

    bpy.app.timers.register(_do, first_interval=0.2)


def on_bind_setting_update(self, context):
    """Store sidebar edits without changing the current object selection.

    Rebinding requires Expy Kit to select both armatures and enter pose mode.
    Doing that from every RNA update made even a checkbox click in the Bind To
    panel activate the source rig. The panel has an explicit Apply Bind
    Settings button, so edits remain passive until that operator is used.
    """
    if not _SYNCING_BIND_PROPS:
        tag_retargeting_redraw()


def migrate_throw_from_custom(settings):
    """Copy legacy custom.throw into the main throw slot."""
    if not settings:
        return
    if getattr(settings, 'throw', ''):
        return
    custom = getattr(settings, 'custom', None)
    if custom is None:
        return
    throw_bone = getattr(custom, 'throw', '') or ''
    if throw_bone:
        try:
            settings.throw = throw_bone
        except AttributeError:
            pass


COPY_TYPES = frozenset({'COPY_LOCATION', 'COPY_ROTATION', 'COPY_SCALE'})


def bind_constraints(constrained, driver):
    """Copy constraints a bind put on ``constrained`` that follow ``driver``."""
    if constrained is None or driver is None or constrained.pose is None:
        return []
    return [con for pb in constrained.pose.bones for con in pb.constraints
            if con.type in COPY_TYPES and getattr(con, 'target', None) == driver]


def rig_meshes(context, rig):
    return [ob for ob in context.scene.objects if ob.type == 'MESH'
            and (ob in rig.children_recursive or any(
                mod.type == 'ARMATURE' and mod.object == rig for mod in ob.modifiers))]


def bind_preview_off(scene) -> bool:
    constrained, driver = bound_pair(scene)
    return bool(scene.expykit_bind_is_active and constrained and constrained.hide_get())


class SUB_OT_retarget_toggle_bind_preview(bpy.types.Operator):
    bl_idname = "sub.retarget_toggle_bind_preview"
    bl_label = "Before / After"
    bl_description = "Hide or show the target without changing its retargeted pose"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        constrained, driver = bound_pair(context.scene)
        return bool(context.scene.expykit_bind_is_active and constrained and driver)

    def execute(self, context):
        constrained, driver = bound_pair(context.scene)
        hidden = not bind_preview_off(context.scene)
        _select_only_armature(context, driver if hidden else constrained)
        for ob in [constrained, *rig_meshes(context, constrained)]:
            if ob.name in context.view_layer.objects:
                ob.hide_set(hidden)
        _invalidate_smash_viewport()
        tag_retargeting_redraw()
        return {'FINISHED'}


class SUB_OT_retarget_source_meshes(bpy.types.Operator):
    bl_idname = "sub.retarget_source_meshes"
    bl_label = "Toggle Source Model"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = context.scene.expykit_bind_to
        meshes = [ob for ob in rig_meshes(context, rig)
                  if ob.name in context.view_layer.objects] if rig else []
        hidden = not meshes or not all(ob.hide_get() for ob in meshes)
        target = mapping_target(context)
        focus = target if hidden else rig
        if focus is None or focus.name not in context.view_layer.objects:
            self.report({'WARNING'}, "Assign both armatures in the current view layer first")
            return {'CANCELLED'}
        _select_only_armature(context, focus)
        if hidden:
            for ob in rig_meshes(context, target):
                if ob.name in context.view_layer.objects:
                    ob.hide_set(False)
        for ob in meshes:
            ob.hide_set(hidden)
        _invalidate_smash_viewport()
        tag_retargeting_redraw()
        return {'FINISHED'}


def adjustment_channels(bone):
    rotation = ('rotation_quaternion' if bone.rotation_mode == 'QUATERNION' else
                'rotation_axis_angle' if bone.rotation_mode == 'AXIS_ANGLE' else 'rotation_euler')
    return {key: list(getattr(bone, key)) for key in ('location', rotation, 'scale')}


class SUB_OT_retarget_adjustments(bpy.types.Operator):
    bl_idname = "sub.retarget_adjustments"
    bl_label = "Make adjustments"
    bl_description = "Adjust source retarget bones, then key changed bones at the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        from ..blender_compat import is_pose_bone_hidden, set_pose_bone_hidden, set_pose_bone_select
        state = json.loads(scene.get('sub_retarget_adjustments', '{}'))
        source = scene.objects.get(state['source']) if state else scene.expykit_bind_to
        target = scene.objects.get(state['target']) if state else mapping_target(context)
        if not source or not target or source.name not in context.view_layer.objects or target.name not in context.view_layer.objects:
            self.report({'WARNING'}, "Both armatures must be in the current view layer")
            return {'CANCELLED'}
        helpers = [b for b in source.data.bones if b.name.endswith('_RET') and b.collections]
        if not state and not helpers:
            self.report({'WARNING'}, "The source has no _RET bones in Bone Collections; bind first")
            return {'CANCELLED'}
        if state:
            action = source.animation_data.action if source.animation_data else None
            if scene.frame_current != state['frame'] or (action.name if action else '') != state['action']:
                self.report({'WARNING'}, "Return to the animation and frame where adjustments started before confirming")
                return {'CANCELLED'}
            for name, before in state['transforms'].items():
                bone = source.pose.bones.get(name)
                if bone and adjustment_channels(bone) != before:
                    for channel in adjustment_channels(bone):
                        bone.keyframe_insert(channel, frame=scene.frame_current, group=name)
            for bone in source.pose.bones:
                hidden = True if bone.name.endswith('_RET') else state['bones'].get(bone.name, is_pose_bone_hidden(bone))
                set_pose_bone_hidden(bone, hidden)
            for collection in source.data.collections_all:
                saved = state['collections'].get(collection.name)
                if saved is not None:
                    collection.is_visible, collection.is_solo = saved
            source.data.pose_position = state['pose_position']
            del scene['sub_retarget_adjustments']
            selected = target
        else:
            action = source.animation_data.action if source.animation_data else None
            state = {'source': source.name, 'target': target.name, 'frame': scene.frame_current,
                     'action': action.name if action else '', 'pose_position': source.data.pose_position,
                     'bones': {b.name: is_pose_bone_hidden(b) for b in source.pose.bones},
                     'collections': {c.name: [c.is_visible, c.is_solo] for c in source.data.collections_all},
                     'transforms': {b.name: adjustment_channels(source.pose.bones[b.name]) for b in helpers}}
            scene['sub_retarget_adjustments'] = json.dumps(state)
            source.data.pose_position = 'POSE'
            for collection in source.data.collections_all:
                collection.is_solo = False
                collection.is_visible = True
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for ob in context.view_layer.objects:
                ob.select_set(False)
            source.hide_set(False)
            source.select_set(True)
            context.view_layer.objects.active = source
            bpy.ops.object.mode_set(mode='POSE')
            bpy.ops.pose.select_all(action='SELECT')
            bpy.ops.pose.hide(unselected=False)
            helper_names = {bone.name for bone in helpers}
            for bone in source.pose.bones:
                set_pose_bone_hidden(bone, bone.name not in helper_names)
                set_pose_bone_select(bone, False)
            tag_retargeting_redraw()
            return {'FINISHED'}
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.view_layer.objects:
            ob.select_set(False)
        selected.hide_set(False)
        selected.select_set(True)
        context.view_layer.objects.active = selected
        if not state or selected == source:
            bpy.ops.object.mode_set(mode='POSE')
        tag_retargeting_redraw()
        return {'FINISHED'}


def mapping_target(context):
    from . import mapping_ui
    return mapping_ui.apply_to(context)


class SUB_OT_retarget_action(bpy.types.Operator):
    bl_idname = "sub.retarget_action"
    bl_label = "Select Source Animation"
    bl_options = {'REGISTER', 'UNDO'}

    action_name: bpy.props.StringProperty()
    direction: bpy.props.IntProperty(default=0)

    def execute(self, context):
        from ..extras.animation_scroll import get_armature_actions, apply_armature_action
        rig = context.scene.expykit_bind_to
        actions = get_armature_actions(rig)
        if not actions:
            return {'CANCELLED'}
        if self.direction:
            current = rig.animation_data.action if rig.animation_data else None
            index = actions.index(current) if current in actions else (-1 if self.direction > 0 else 0)
            action = actions[(index + self.direction) % len(actions)]
        else:
            action = next((a for a in actions if a.name == self.action_name), None)
        if action is None:
            return {'CANCELLED'}
        apply_armature_action(context, rig, action, autoplay=False)
        tag_retargeting_redraw()
        return {'FINISHED'}


class SUB_MT_retarget_actions(bpy.types.Menu):
    bl_label = "Source Animation"

    def draw(self, context):
        from ..extras.animation_scroll import get_armature_actions
        for action in get_armature_actions(context.scene.expykit_bind_to):
            self.layout.operator(SUB_OT_retarget_action.bl_idname, text=action.name).action_name = action.name


class ULTIMATE_OT_apply_bind_settings(bpy.types.Operator):
    """Re-apply the Bind to Active Armature settings to the last bound pair."""
    bl_description = 'Re-apply the Bind to Active Armature settings to the last bound pair.'
    bl_idname = "object.ultimate_apply_bind_settings"
    bl_label = "Apply Bind Settings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        source, target = bound_pair(context.scene)
        return bool(source and target)

    def execute(self, context):
        if reapply_bind_from_scene(context):
            self.report({'INFO'}, "Bind settings applied")
            return {'FINISHED'}
        self.report({'WARNING'}, "Could not apply bind settings")
        return {'CANCELLED'}


class ULTIMATE_OT_bind_wait_select(bpy.types.Operator):
    """After the bind popup, leave only the constrained armature selected."""
    bl_description = 'After the bind popup, leave only the constrained armature selected.'
    bl_idname = "object.ultimate_bind_wait_select"
    bl_label = "Bind Finish Select"
    bl_options = {'INTERNAL'}

    def modal(self, context, event):
        region = getattr(context, 'region', None)
        rtype = getattr(region, 'type', '') if region else ''
        if rtype in {'HUD', 'UI', 'TOOLS', 'TOOL_HEADER', 'HEADER', 'NAVIGATION_BAR'}:
            return {'PASS_THROUGH'}
        if event.value == 'PRESS' and event.type in {
            'LEFTMOUSE', 'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER', 'ESC',
        }:
            constrained, driver = bound_pair(context.scene)
            select_only_constrained(context, constrained, driver)
            tag_retargeting_redraw()
            return {'FINISHED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


classes = (
    SUB_OT_retarget_adjustments,
    SUB_OT_retarget_action,
    SUB_MT_retarget_actions,
    SUB_OT_retarget_source_meshes,
    SUB_OT_retarget_toggle_bind_preview,
    ULTIMATE_OT_apply_bind_settings,
    ULTIMATE_OT_bind_wait_select,
)
