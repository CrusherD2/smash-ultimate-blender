from contextvars import ContextVar
from pathlib import Path

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator
from bpy_extras.io_utils import ImportHelper

from ..blender_compat import assign_action, ensure_action_slot

BASE_TRACK = 'SUB Visibility Base'
LAYER_PREFIX = 'SUB Visibility Layer: '
_refreshing = ContextVar('sub_visibility_refreshing', default=False)


def is_refreshing_visibility_layers() -> bool:
    return _refreshing.get()


def is_playing_animation() -> bool:
    return any(window.screen is not None and window.screen.is_animation_playing
               for window in bpy.context.window_manager.windows)


def add_strip(track, action, start: int):
    strip = track.strips.new(action.name, start, action)
    if hasattr(strip, 'action_slot'):
        strip.action_slot = ensure_action_slot(action, track.id_data)
    strip.blend_type = 'REPLACE'
    strip.influence = 1.0
    strip.extrapolation = 'HOLD'
    return strip


def has_layers(animation) -> bool:
    return any(track.name.startswith(LAYER_PREFIX) for track in animation.nla_tracks)


def edit_base_strip(animation) -> None:
    track = animation.nla_tracks.get(BASE_TRACK)
    if track is None or not track.strips:
        assign_action(animation, None)
        return
    obj = next((obj for obj in bpy.context.scene.objects
                if obj.type == 'ARMATURE' and obj.data == animation.id_data), None)
    screen = bpy.context.screen
    area = bpy.context.area or (screen.areas[0] if screen is not None and screen.areas else None)
    if obj is None or area is None:
        raise RuntimeError('A Blender editor and the layer armature are required')
    if animation.use_tweak_mode:
        animation.use_tweak_mode = False
    animation.action_influence = 1.0
    animation.use_nla = True
    assign_action(animation, None)
    selection = []
    for owner in (obj.animation_data, animation):
        if owner is None:
            continue
        for candidate in owner.nla_tracks:
            selection.append((candidate, candidate.select))
            candidate.select = candidate == track
            for strip in candidate.strips:
                selection.append((strip, strip.select))
                strip.select = candidate == track and strip == track.strips[0]
    animation.nla_tracks.active = track
    previous_type = area.type
    try:
        area.type = 'NLA_EDITOR'
        region = next(region for region in area.regions if region.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region, object=obj,
                                       active_object=obj, selected_objects=[obj],
                                       selected_editable_objects=[obj]):
            if bpy.ops.nla.tweakmode_exit.poll():
                bpy.ops.nla.tweakmode_exit()
            result = bpy.ops.nla.tweakmode_enter(use_upper_stack_evaluation=True)
        if result != {'FINISHED'} or not animation.use_tweak_mode:
            raise RuntimeError('Could not enable native base-strip editing')
    finally:
        area.type = previous_type
        for item, selected in selection:
            item.select = selected


def set_base(animation, action) -> None:
    if not has_layers(animation):
        assign_action(animation, action)
        return
    if animation.use_tweak_mode:
        animation.use_tweak_mode = False
    track = animation.nla_tracks.get(BASE_TRACK)
    if track is None:
        raise RuntimeError('Visibility layer base track is missing')
    for strip in list(track.strips):
        track.strips.remove(strip)
    add_strip(track, action, int(action.frame_range[0]))
    edit_base_strip(animation)


def install_layer(animation, base, action, start: int) -> None:
    if animation.use_tweak_mode:
        animation.use_tweak_mode = False
    if animation.nla_tracks.get(BASE_TRACK) is None:
        track = animation.nla_tracks.new()
        track.name = BASE_TRACK
        if base is not None:
            add_strip(track, base, int(base.frame_range[0]))
    track = animation.nla_tracks.new(prev=animation.nla_tracks[-1] if animation.nla_tracks else None)
    track.name = LAYER_PREFIX + action.name
    add_strip(track, action, start)
    edit_base_strip(animation)


def keyframe_base_property(data, **kwargs):
    animation = data.animation_data
    if animation is None or not animation.use_tweak_mode or not has_layers(animation):
        return data.keyframe_insert(**kwargs)
    use_nla = animation.use_nla
    try:
        # Upper REPLACE strips otherwise make Blender's key-value remapping singular.
        animation.use_nla = False
        return data.keyframe_insert(**kwargs)
    finally:
        animation.use_nla = use_nla
        schedule_visibility_layers(data)


def refresh_visibility_layers():
    if is_playing_animation():
        return None
    token = _refreshing.set(True)
    try:
        for scene in bpy.data.scenes:
            if any(obj.type == 'ARMATURE' and obj.data.animation_data is not None
                   and has_layers(obj.data.animation_data) for obj in scene.objects):
                scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
    finally:
        _refreshing.reset(token)
    return None


def schedule_visibility_layers(data) -> None:
    if is_refreshing_visibility_layers() or is_playing_animation():
        return
    animation = getattr(data, 'animation_data', None)
    if animation is not None and has_layers(animation):
        if not bpy.app.timers.is_registered(refresh_visibility_layers):
            bpy.app.timers.register(refresh_visibility_layers, first_interval=0.0)


def restore_native_layers():
    token = _refreshing.set(True)
    try:
        for obj in bpy.context.scene.objects:
            if obj.type == 'ARMATURE':
                animation = obj.data.animation_data
                if animation is not None and has_layers(animation):
                    edit_base_strip(animation)
    finally:
        _refreshing.reset(token)
    return None


@bpy.app.handlers.persistent
def load_native_layers(_filepath):
    if not bpy.app.timers.is_registered(restore_native_layers):
        bpy.app.timers.register(restore_native_layers, first_interval=0.0)


class SUB_OP_import_visibility_layer(Operator, ImportHelper):
    bl_idname = 'sub.import_visibility_layer'
    bl_label = 'Import Visibility Layer'
    bl_description = 'Layer only material and visibility animation over the regular animation'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.nuanmb'
    filter_glob: StringProperty(default='*.nuanmb', options={'HIDDEN'})
    start_frame: IntProperty(name='Start Frame', default=1)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def execute(self, context):
        from ..anim.import_anim import _import_model_anim
        arma = context.object
        animation = arma.data.animation_data_create()
        base = animation.action
        try:
            _import_model_anim(context, self.filepath, False, True, True,
                               self.start_frame, arma, visibility_layer=True)
        except Exception as exc:
            assign_action(animation, base)
            self.report({'ERROR'}, f'Could not import visibility layer: {exc}')
            return {'CANCELLED'}
        context.scene.frame_set(context.scene.frame_current)
        self.report({'INFO'}, f'Added visibility layer: {Path(self.filepath).stem}')
        return {'FINISHED'}


class SUB_MT_visibility_animation_folders(Menu):
    bl_label = 'Animation Folders'

    def draw(self, context):
        ssp = context.scene.sub_scene_properties.visibility_animation_browser
        paths = {item.path for item in ssp.animation_import_folders}
        if ssp.animation_import_folder_path:
            paths.add(ssp.animation_import_folder_path)
        for path in sorted(paths, key=lambda value: (value.casefold(), value)):
            op = self.layout.operator(
                'sub.switch_animation_folder', text=path,
                icon='CHECKMARK' if path == ssp.animation_import_folder_path else 'FILE_FOLDER')
            op.folder = path
            op.visibility = True


class SUB_OP_import_visibility_folder(Operator):
    bl_idname = 'sub.import_visibility_folder'
    bl_label = 'Import Folder Animations as Visibility Layers'
    bl_description = 'Import the checked folder animations as independent material and visibility layers'
    bl_options = {'REGISTER', 'UNDO'}

    import_all: BoolProperty(default=False, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return (SUB_OP_import_visibility_layer.poll(context)
                and len(context.scene.sub_scene_properties.visibility_animation_browser.animation_import_files) > 0)

    def execute(self, context):
        items = context.scene.sub_scene_properties.visibility_animation_browser.animation_import_files
        paths = sorted({item.path for item in items if self.import_all or item.selected},
                       key=lambda path: (path.casefold(), path))
        if not paths:
            self.report({'WARNING'}, 'Select at least one animation')
            return {'CANCELLED'}
        imported = 0
        for path in paths:
            try:
                result = bpy.ops.sub.import_visibility_layer(filepath=path)
            except RuntimeError as exc:
                self.report({'WARNING'}, f'Could not import {Path(path).name}: {exc}')
                continue
            if result == {'FINISHED'}:
                imported += 1
        if not imported:
            return {'CANCELLED'}
        failed = len(paths) - imported
        self.report({'WARNING'} if failed else {'INFO'},
                    f'Added {imported} visibility layer(s); {failed} failed')
        return {'FINISHED'}


def draw_visibility_folder(layout, context) -> None:
    ssp = context.scene.sub_scene_properties.visibility_animation_browser
    layout.operator('sub.ssbh_animation_folder_selector', icon='ZOOM_ALL', text='Add Animation Folder').visibility = True
    if not (ssp.animation_import_folder_path or len(ssp.animation_import_folders)):
        return
    box = layout.box()
    header = box.row()
    header.prop(ssp, 'related_animations_expanded',
                icon='TRIA_DOWN' if ssp.related_animations_expanded else 'TRIA_RIGHT',
                icon_only=True, emboss=False)
    header.label(text='Related Animations:')
    if not ssp.related_animations_expanded:
        return
    if ssp.animation_import_folder_path:
        box.menu('SUB_MT_visibility_animation_folders', text=f'Folder: {ssp.animation_import_folder_path}')
    box.template_list('SUB_UL_animation_import_list', 'visibility_layers', ssp,
                      'animation_import_files', ssp, 'animation_import_files_index', rows=5)
    box.label(text='Drag checkboxes to include or exclude')
    box.label(text='Click a name to select it; tick boxes to pick several', icon='INFO')
    row = box.row(align=True)
    for label, select in (('Select All', True), ('Deselect All', False)):
        op = row.operator('sub.select_all_animation_imports', text=label)
        op.select = select
        op.visibility = True
    selected = sum(1 for item in ssp.animation_import_files if item.selected)
    row = box.row()
    row.enabled = selected > 0
    row.operator(SUB_OP_import_visibility_folder.bl_idname, icon='IMPORT',
                 text=f'Import Selected as Visibility Layers ({selected})')
    box.operator(SUB_OP_import_visibility_folder.bl_idname,
                 text='Import All as Visibility Layers').import_all = True


def draw_visibility_layers(layout, context) -> None:
    box = layout.box()
    box.label(text='Visibility Layer', icon='RENDERLAYERS')
    box.operator(SUB_OP_import_visibility_layer.bl_idname, icon='IMPORT')
    draw_visibility_folder(box, context)
    arma = context.object
    animation = arma.data.animation_data if arma is not None and arma.type == 'ARMATURE' else None
    if animation is not None:
        for track in animation.nla_tracks:
            if track.name.startswith(LAYER_PREFIX):
                row = box.row(align=True)
                row.prop(track, 'mute', text='', icon='HIDE_ON' if track.mute else 'HIDE_OFF')
                row.label(text=track.name[len(LAYER_PREFIX):])


def register() -> None:
    bpy.utils.register_class(SUB_MT_visibility_animation_folders)
    bpy.utils.register_class(SUB_OP_import_visibility_layer)
    bpy.utils.register_class(SUB_OP_import_visibility_folder)
    if load_native_layers not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_native_layers)
    if not bpy.app.timers.is_registered(restore_native_layers):
        bpy.app.timers.register(restore_native_layers, first_interval=0.0)


def unregister() -> None:
    if load_native_layers in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_native_layers)
    for callback in (refresh_visibility_layers, restore_native_layers):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    bpy.utils.unregister_class(SUB_MT_visibility_animation_folders)
    bpy.utils.unregister_class(SUB_OP_import_visibility_folder)
    bpy.utils.unregister_class(SUB_OP_import_visibility_layer)
