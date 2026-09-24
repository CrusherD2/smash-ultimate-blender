"""Drag and drop Smash files into the 3D Viewport or Outliner.

One drop may mix file types. Each file goes to the importer the sidebar would
use, in an order that lets later files build on earlier ones:

1. Model files (.numdlb/.numshb/.nusktb/.numatb/.nuhlpb) import their folder once.
2. swing.prc and animations (.nuanmb/.rawanim) land on the model just imported,
   otherwise on the active armature (or camera), otherwise the scene's only armature.
3. Stage lighting (light*.nuanmb) and .shpcanim import on their own.

The same operator is also on File > Import for picking the files in a browser.
"""
import os

import bpy
from bpy.props import CollectionProperty, StringProperty
from bpy.types import FileHandler, Operator, OperatorFileListElement

from .drop_plan import DROP_EXTENSIONS, RAW_ANIM_SUFFIX, plan_drop

_MODEL_FILE_NAME_PROPS = (
    'model_import_numdlb_file_name', 'model_import_numshb_file_name',
    'model_import_nusktb_file_name', 'model_import_numatb_file_name',
    'model_import_nuhlpb_file_name',
)


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _make_active(context, obj):
    context.view_layer.objects.active = obj
    try:
        obj.select_set(True)
    except RuntimeError:
        pass  # Hidden objects cannot be selected but can still be animated.


def _ensure_object_mode(context):
    if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass


def _drop_target(context, imported_armatures):
    """The object dropped animations belong to, or None when it is ambiguous."""
    if imported_armatures:
        return imported_armatures[-1]
    obj = context.view_layer.objects.active
    if obj is not None:
        if obj.type in {'ARMATURE', 'CAMERA'}:
            return obj
        if obj.type == 'MESH':
            armature = obj.find_armature()
            if armature is not None:
                return armature
    armatures = [o for o in context.view_layer.objects if o.type == 'ARMATURE']
    return armatures[0] if len(armatures) == 1 else None


def _import_model_folder(operator, context, folder):
    from .model.import_model import (
        _assign_model_file_names, _is_importable_model_folder, _is_model_file, import_model)

    if not _is_importable_model_folder(folder):
        operator.report({'WARNING'}, f"Skipped '{folder}': a model needs .numdlb, .numshb, .nusktb and .numatb files")
        return None
    ssp = context.scene.sub_scene_properties
    # Stale names from the previous model would otherwise be looked up here.
    for prop in _MODEL_FILE_NAME_PROPS:
        setattr(ssp, prop, '')
    ssp.model_import_folder_path = folder
    ssp['sub_model_import_fallback'] = folder
    _assign_model_file_names(ssp, [name for name in os.listdir(folder) if _is_model_file(name)])
    if import_model(operator, context) == {'CANCELLED'}:
        return None
    obj = context.view_layer.objects.active
    return obj if obj is not None and obj.type == 'ARMATURE' else None


def _show_animation_folders(context, armature, paths):
    """Point the Animation browser at the dropped folders, as browsing there would."""
    from .anim.import_anim import (
        bind_anim_folder_to_armature, fill_animation_import_list,
        remember_animation_folder, sync_anim_importer_to_active)
    from .anim.raw_anim import refresh_raw_animation_import_list

    ssp = context.scene.sub_scene_properties
    folders = list(dict.fromkeys(os.path.dirname(p) for p in paths if not p.lower().endswith(RAW_ANIM_SUFFIX)))
    raw_folders = list(dict.fromkeys(os.path.dirname(p) for p in paths if p.lower().endswith(RAW_ANIM_SUFFIX)))
    if folders:
        sync_anim_importer_to_active(context, armature=armature)
        for folder in folders:
            remember_animation_folder(ssp, folder)
        fill_animation_import_list(ssp, folders[-1])
        bind_anim_folder_to_armature(armature, folders[-1], ssp)
    if raw_folders:
        refresh_raw_animation_import_list(ssp, raw_folders[-1])


def _import_swing(operator, context, armature, path):
    from .swing.operators import get_swing_mesh_master_collection, setup_bone_meshes, swing_prc_import

    context.scene.sub_scene_properties.last_swing_directory = os.path.dirname(path)
    swing_prc_import(operator, context, path)
    setup_bone_meshes(operator, context, get_swing_mesh_master_collection(context, armature))


class SUB_OP_drop_import(Operator):
    bl_idname = 'sub.drop_import'
    bl_label = 'Import Smash Files'
    bl_description = (
        'Import Smash models, animations, swing.prc and stage lighting, '
        'sending each file to the matching importer'
    )
    bl_options = {'UNDO'}

    filter_glob: StringProperty(default=';'.join('*' + ext for ext in DROP_EXTENSIONS), options={'HIDDEN'})
    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE', 'HIDDEN'})
    files: CollectionProperty(type=OperatorFileListElement, options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, _event):
        # A drop fills directory/files before invoking; the menu entry does not.
        if self.directory and self.files:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        paths = [os.path.join(self.directory, entry.name) for entry in self.files if entry.name]
        plan = plan_drop(paths)
        if plan.is_empty():
            self.report({'ERROR'}, 'No Smash files to import (models, .nuanmb, .rawanim, swing.prc, .shpcanim)')
            return {'CANCELLED'}

        done = []
        failed = 0
        ssp = context.scene.sub_scene_properties

        if plan.model_folders or plan.swing_files or plan.stage_lights or plan.shpc_files:
            _ensure_object_mode(context)

        armatures = []
        for folder in plan.model_folders:
            try:
                armature = _import_model_folder(self, context, folder)
            except Exception as error:
                armature = None
                self.report({'ERROR'}, f"Model import failed for '{folder}': {error}")
            if armature is None:
                failed += 1
            else:
                armatures.append(armature)
        if armatures:
            done.append(_plural(len(armatures), 'model'))

        target = _drop_target(context, armatures) if plan.needs_armature else None
        if plan.needs_armature and target is None:
            count = len(plan.animations) + len(plan.swing_files)
            self.report({'ERROR'}, f'Select an armature to receive the dropped {_plural(count, "file")}')
            failed += count
        elif target is not None:
            _make_active(context, target)

            if plan.swing_files and target.type != 'ARMATURE':
                self.report({'ERROR'}, 'swing.prc needs an armature, not a camera')
                failed += len(plan.swing_files)
            elif plan.swing_files:
                # A second swing.prc would just replace the first one.
                if len(plan.swing_files) > 1:
                    self.report({'WARNING'}, f'Several swing.prc files dropped; using {plan.swing_files[-1]}')
                try:
                    _import_swing(self, context, target, plan.swing_files[-1])
                    done.append(f"swing.prc on '{target.name}'")
                except Exception as error:
                    failed += 1
                    self.report({'ERROR'}, f'swing.prc import failed: {error}')
                _make_active(context, target)

            if plan.animations:
                from .anim.import_anim import import_animation_paths
                imported, anim_failed = import_animation_paths(context, self, plan.animations)
                failed += anim_failed
                if imported:
                    done.append(f"{_plural(imported, 'animation')} on '{target.name}'")
                if target.type == 'ARMATURE':
                    try:
                        _show_animation_folders(context, target, plan.animations)
                    except Exception as error:
                        print(f'Drag and drop: could not update the animation browser: {error}')

        for path in plan.stage_lights:
            from .extras.stage_tools.light_nuanmb import import_stage_light
            try:
                import_stage_light(context, path, context.scene.frame_start)
                ssp.last_stage_light_dir = os.path.dirname(path)
                done.append(f"stage light '{os.path.basename(path)}'")
            except Exception as error:
                failed += 1
                self.report({'ERROR'}, f"Stage light import failed for '{os.path.basename(path)}': {error}")

        for path in plan.shpc_files:
            from .extras.stage_tools.shpcanim import import_shpcanim
            try:
                import_shpcanim(context, path)
                ssp.last_stage_shpc_dir = os.path.dirname(path)
                done.append(f"SHPC '{os.path.basename(path)}'")
            except Exception as error:
                failed += 1
                self.report({'ERROR'}, f"SHPC import failed for '{os.path.basename(path)}': {error}")

        notes = []
        if failed:
            notes.append(f'{failed} failed')
        if plan.skipped:
            names = ', '.join(os.path.basename(p) for p in plan.skipped[:3])
            notes.append(f"skipped {names}{'…' if len(plan.skipped) > 3 else ''}")
        message = 'Imported ' + ', '.join(done) if done else 'Nothing imported'
        if notes:
            message += ' (' + '; '.join(notes) + ')'
        self.report({'WARNING'} if failed or plan.skipped or not done else {'INFO'}, message)
        return {'FINISHED'} if done else {'CANCELLED'}


class SUB_FH_smash_files(FileHandler):
    bl_idname = 'SUB_FH_smash_files'
    bl_label = 'Smash Ultimate Files'
    bl_import_operator = SUB_OP_drop_import.bl_idname
    bl_file_extensions = ';'.join(DROP_EXTENSIONS)

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type in {'VIEW_3D', 'OUTLINER'}


def menu_func_import(self, _context):
    self.layout.operator(SUB_OP_drop_import.bl_idname,
                         text='Smash Ultimate (.numdlb, .nuanmb, swing.prc, ...)')


classes = (SUB_OP_drop_import, SUB_FH_smash_files)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
