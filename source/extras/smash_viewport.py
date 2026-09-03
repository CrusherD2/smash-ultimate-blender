"""Smash Viewport: ssbh_wgpu preview over the 3D View.

A normal Blender render engine. Set the scene engine to Smash Viewport and use
Rendered shading. Overlays, selection, and object visibility stay under Blender.
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import sys
import time
from ctypes import POINTER, c_char_p, c_float, c_int, c_uint, c_ubyte, c_void_p, c_size_t

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Vector

ENGINE_ID = "SMASH_VIEWPORT"
_DRAW_HANDLER_ATTR = "_sub_smash_vp_draw_handler"
_ANIM_RIG_FLAG = "sub_animation_rig"
_EXTRA_BONE_PREFIX = "BL_"
_TIMER_INTERVAL = 1.0 / 60.0
_IK_BONE = re.compile(r"^(Foot|Hand|Knee|Arm)IK([LR])(\d*)$")

_Y_UP_TO_Z_UP = Matrix.Rotation(math.radians(90.0), 4, "X")
_Z_UP_TO_Y_UP = _Y_UP_TO_Z_UP.inverted()
_X_MAJOR_TO_Y_MAJOR = Matrix.Rotation(math.radians(-90.0), 4, "Z")
_Y_MAJOR_TO_X_MAJOR = _X_MAJOR_TO_Y_MAJOR.inverted()
# Blender window_matrix is OpenGL clip Z [-1, 1]. wgpu/DX12 is [0, 1].
_GL_TO_WGPU_CLIP = Matrix((
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.5, 0.5),
    (0.0, 0.0, 0.0, 1.0),
))
# Smash shaders are perspective-only. Locked ortho views use a long-lens
# stand-in at this distance so lighting works; larger = closer to true ortho.
_ORTHO_EYE_MIN = 400.0

_lib = None
_lib_error = ""
_preview = None
_loaded_folder = ""
_pixels = bytearray()
_float_pixels = None
_pixel_size = (0, 0)
_last_status = ""
_last_error = ""
_name_keep = []
_vis_name_keep = []
_cv_name_keep = []
_timer_running = False
_ignore_update = False
_in_tick = False
_saved_engines = {}
_saved_color = {}
_saved_grids = {}
_last_tick_key = None
_last_pose_fp = None
_last_vis_state = None
_last_cv31_state = None
_last_cam_key = None
_last_frame = None
_last_draw_mono = 0.0
_pixel_version = 0
_blit_tex = None
_blit_tex_key = None
_gpu_failed = False
_blit_ubyte_ok = True
_saved_mesh_filter = {}
_applied_bg = None
_applied_light = None
_applied_light_frame = None
_MSGBUS_OWNER = object()
_resume_attempts = 0


def last_shader_error():
    return _last_error


def last_draw_status():
    return _last_status


def _first_scene():
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        return scene
    try:
        return bpy.data.scenes[0]
    except Exception:
        return None


def _scene_wants_smash(scene):
    if scene is None:
        return False
    ssp = getattr(scene, "sub_scene_properties", None)
    if ssp is not None and bool(getattr(ssp, "smash_viewport", False)):
        return True
    return _engine_is_smash(scene)


def _has_rendered_3d_view():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            shading = getattr(space, "shading", None) if space is not None else None
            if shading is not None and getattr(shading, "type", "") == "RENDERED":
                return True
    return False


def _id_key(ob):
    try:
        return int(ob.as_pointer())
    except Exception:
        return id(ob)


def native_plugin_path():
    addon_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    native = os.path.join(addon_dir, "native")
    names = []
    if sys.platform == "win32":
        names = ["ssbh_blender_preview.dll", "ssbh_blender_preview.reload.dll"]
    elif sys.platform == "darwin":
        names = ["libssbh_blender_preview.dylib", "ssbh_blender_preview.dylib"]
    else:
        names = ["libssbh_blender_preview.so"]
    search = [
        os.path.join(native, "bin"),
        os.path.join(native, "ssbh_blender_preview", "target", "release"),
        os.path.join(native, "ssbh_blender_preview", "target", "debug"),
    ]
    found = []
    for folder in search:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                found.append(path)
    if not found:
        return ""
    found.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return found[0]


def _bind_lib(lib):
    lib.ssbh_preview_create.restype = c_void_p
    lib.ssbh_preview_create.argtypes = []
    lib.ssbh_preview_destroy.restype = None
    lib.ssbh_preview_destroy.argtypes = [c_void_p]
    lib.ssbh_preview_load_folder.restype = c_int
    lib.ssbh_preview_load_folder.argtypes = [c_void_p, c_char_p]
    lib.ssbh_preview_resize.restype = c_int
    lib.ssbh_preview_resize.argtypes = [c_void_p, c_uint, c_uint, c_float]
    lib.ssbh_preview_set_camera.restype = c_int
    lib.ssbh_preview_set_camera.argtypes = [
        c_void_p,
        POINTER(c_float),
        POINTER(c_float),
        POINTER(c_float),
        c_float,
        c_float,
        c_float,
    ]
    lib.ssbh_preview_set_world_transforms.restype = c_int
    lib.ssbh_preview_set_world_transforms.argtypes = [
        c_void_p,
        POINTER(c_char_p),
        POINTER(c_float),
        c_uint,
    ]
    lib.ssbh_preview_set_mesh_visibility.restype = c_int
    lib.ssbh_preview_set_mesh_visibility.argtypes = [
        c_void_p,
        POINTER(c_char_p),
        POINTER(c_uint),
        POINTER(c_ubyte),
        c_uint,
    ]
    if hasattr(lib, "ssbh_preview_set_custom_vector"):
        lib.ssbh_preview_set_custom_vector.restype = c_int
        lib.ssbh_preview_set_custom_vector.argtypes = [
            c_void_p,
            POINTER(c_char_p),
            c_char_p,
            POINTER(c_float),
            c_uint,
        ]
    lib.ssbh_preview_render.restype = c_int
    lib.ssbh_preview_render.argtypes = [
        c_void_p,
        ctypes.c_void_p,
        c_size_t,
        POINTER(c_uint),
        POINTER(c_uint),
    ]
    lib.ssbh_preview_poll.restype = c_int
    lib.ssbh_preview_poll.argtypes = [
        c_void_p,
        ctypes.c_void_p,
        c_size_t,
        POINTER(c_uint),
        POINTER(c_uint),
    ]
    lib.ssbh_preview_using_gpu.restype = c_int
    lib.ssbh_preview_using_gpu.argtypes = [c_void_p]
    lib.ssbh_preview_present_gl.restype = c_int
    lib.ssbh_preview_present_gl.argtypes = [c_void_p, c_uint, c_uint, c_int]
    lib.ssbh_preview_last_error.restype = c_char_p
    lib.ssbh_preview_last_error.argtypes = []
    optional = (
        ("ssbh_preview_set_clear_color", c_int, [c_void_p, c_float, c_float, c_float, c_float]),
        ("ssbh_preview_load_lighting", c_int, [c_void_p, c_char_p]),
        ("ssbh_preview_clear_lighting", c_int, [c_void_p]),
        ("ssbh_preview_set_lighting_frame", c_int, [c_void_p, c_float]),
        ("ssbh_preview_render_wait", c_int, [
            c_void_p,
            ctypes.c_void_p,
            c_size_t,
            POINTER(c_uint),
            POINTER(c_uint),
        ]),
        ("ssbh_preview_gif_begin", c_int, [c_char_p, c_uint, c_int]),
        ("ssbh_preview_gif_add_frame", c_int, [ctypes.c_void_p, c_size_t, c_uint, c_uint]),
        ("ssbh_preview_gif_finish", c_int, []),
        ("ssbh_preview_gif_cancel", c_int, []),
    )
    for name, restype, argtypes in optional:
        if hasattr(lib, name):
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = argtypes
    return lib


def _native_error(lib=None):
    handle = lib or _lib
    if handle is None:
        return _lib_error or "Native plugin not loaded"
    try:
        raw = handle.ssbh_preview_last_error()
    except Exception:
        return "Native plugin error"
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def load_native_library():
    global _lib, _lib_error
    if _lib is not None:
        return _lib
    path = native_plugin_path()
    if not path:
        _lib_error = (
            "Smash Viewport plugin not found. Windows ships "
            "native/bin/ssbh_blender_preview.dll; Linux and macOS plugins are "
            "native/bin/libssbh_blender_preview.so and "
            "native/bin/libssbh_blender_preview.dylib. See native/README.md."
        )
        return None
    if sys.platform == "win32":
        os.environ.setdefault("WGPU_BACKEND", "dx12")
    elif sys.platform == "darwin":
        os.environ.setdefault("WGPU_BACKEND", "metal")
    else:
        os.environ.setdefault("WGPU_BACKEND", "vulkan")
    try:
        _lib = _bind_lib(ctypes.CDLL(path))
        _lib_error = ""
        return _lib
    except OSError as exc:
        _lib_error = f"Failed to load {path}: {exc}"
        _lib = None
        return None


def _ensure_preview():
    global _preview, _last_error
    lib = load_native_library()
    if lib is None:
        _last_error = _lib_error
        return None
    if _preview:
        return _preview
    handle = lib.ssbh_preview_create()
    if not handle:
        _last_error = _native_error(lib) or "ssbh_preview_create failed"
        return None
    _preview = handle
    return _preview


def shutdown_preview():
    global _preview, _loaded_folder, _pixels, _float_pixels, _pixel_size
    global _last_tick_key, _last_pose_fp, _last_vis_state, _last_cv31_state
    global _last_cam_key, _last_frame, _last_status, _last_error
    global _blit_tex, _blit_tex_key, _gpu_failed
    global _applied_bg, _applied_light, _applied_light_frame
    if _lib is not None and _preview:
        try:
            _lib.ssbh_preview_destroy(_preview)
        except Exception:
            pass
    _preview = None
    _loaded_folder = ""
    _pixels = bytearray()
    _float_pixels = None
    _pixel_size = (0, 0)
    _last_tick_key = None
    _last_pose_fp = None
    _last_vis_state = None
    _last_cv31_state = None
    _last_cam_key = None
    _last_frame = None
    _last_status = ""
    _blit_tex = None
    _blit_tex_key = None
    _gpu_failed = False
    _applied_bg = None
    _applied_light = None
    _applied_light_frame = None


def _model_folder(scene):
    ssp = getattr(scene, "sub_scene_properties", None)
    if ssp is None:
        return ""
    return (getattr(ssp, "last_imported_model_path", "") or "").strip()


def _is_smash_armature(obj):
    if obj is None or getattr(obj, "type", "") != "ARMATURE":
        return False
    pose = getattr(obj, "pose", None)
    bones = getattr(pose, "bones", None) if pose is not None else None
    if not bones:
        data = getattr(obj, "data", None)
        bones = getattr(data, "bones", None)
    if not bones:
        return False
    for bone in bones:
        name = getattr(bone, "name", "") or ""
        if name.startswith(_EXTRA_BONE_PREFIX):
            continue
        base = name.split(".")[0]
        if base in ("Trans", "Hip"):
            return True
    return False


def _scene_has_smash_model(scene):
    objects = getattr(scene, "objects", None)
    if not objects:
        return False
    for obj in objects:
        if _is_smash_armature(obj):
            return True
    return False


def _engine_is_smash(scene=None):
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return False
    try:
        return scene.render.engine == ENGINE_ID
    except Exception:
        return False


def _viewport_enabled(scene=None):
    return _engine_is_smash(scene)


def _ensure_model(scene):
    global _loaded_folder, _last_error, _last_pose_fp, _last_vis_state, _last_cv31_state
    global _last_cam_key, _last_frame
    if not _scene_has_smash_model(scene):
        if _preview is not None or _loaded_folder:
            shutdown_preview()
        return False
    folder = _model_folder(scene)
    if not folder:
        _last_error = "Import a Smash model first (Ultimate > Import Model)."
        return False
    if folder == _loaded_folder:
        return True
    preview = _ensure_preview()
    if not preview:
        return False
    rc = _lib.ssbh_preview_load_folder(preview, folder.encode("utf-8"))
    if rc != 0:
        _last_error = _native_error() or f"Failed to load {folder}"
        _loaded_folder = ""
        return False
    _loaded_folder = folder
    _last_pose_fp = None
    _last_vis_state = None
    _last_cv31_state = None
    _last_cam_key = None
    _last_frame = None
    _last_error = ""
    return True


def _mat4_col_major(matrix):
    return [
        matrix[row][col]
        for col in range(4)
        for row in range(4)
    ]


def _perspective_rh(fov_y, aspect, z_near, z_far):
    # Same matrix as glam::Mat4::perspective_rh used by SSBH Editor.
    f = 1.0 / math.tan(fov_y * 0.5)
    r = z_far / (z_near - z_far)
    return Matrix((
        (f / max(aspect, 1e-8), 0.0, 0.0, 0.0),
        (0.0, f, 0.0, 0.0),
        (0.0, 0.0, r, r * z_near),
        (0.0, 0.0, -1.0, 0.0),
    ))


def _is_persp_proj(rv3d):
    try:
        return abs(float(rv3d.window_matrix[3][2])) > 0.5
    except Exception:
        return True


def _ortho_half_height(rv3d):
    try:
        b = abs(float(rv3d.window_matrix[1][1]))
        if b > 1e-8:
            return 1.0 / b
    except Exception:
        pass
    return max(float(getattr(rv3d, "view_distance", 1.0)), 1.0)


def _ortho_half_extents(rv3d, aspect):
    half_h = max(_ortho_half_height(rv3d), 1e-6)
    try:
        a = abs(float(rv3d.window_matrix[0][0]))
        if a > 1e-8:
            return 1.0 / a, half_h
    except Exception:
        pass
    return half_h * max(aspect, 1e-8), half_h


def _smash_view(rv3d):
    return rv3d.view_matrix @ _Y_UP_TO_Z_UP


def _view_eye(matrix):
    try:
        return matrix.inverted().translation.copy()
    except ValueError:
        return matrix.translation.copy()


def _view_at_distance(rv3d, cam_dist):
    """Same look as Blender, camera pulled back along the view axis."""
    blender_view = rv3d.view_matrix.copy()
    pivot = rv3d.view_location.copy()
    try:
        offset = blender_view.inverted().translation - pivot
    except Exception:
        offset = Vector((0.0, 0.0, 0.0))
    if offset.length > 1e-6:
        direction = offset.normalized()
    else:
        try:
            direction = blender_view.inverted().to_3x3() @ Vector((0.0, 0.0, 1.0))
        except Exception:
            direction = Vector((0.0, 1.0, 0.0))
        if direction.length < 1e-6:
            direction = Vector((0.0, 1.0, 0.0))
        else:
            direction.normalize()
    new_cam = pivot + direction * cam_dist
    rot = blender_view.to_3x3()
    new_view = rot.to_4x4()
    new_view.translation = -(rot @ new_cam)
    return new_view


def _camera_to_smash(rv3d, region, width, height, space=None):
    """Orbit uses Blender's matrices. Locked ortho uses a long-lens perspective
    that matches the ortho frame at the look-at plane (Smash cannot light ortho).
    Blender's view_distance / overlays are not written.
    """
    aspect = float(width) / float(max(height, 1))
    if _is_persp_proj(rv3d):
        smash_view = _smash_view(rv3d)
        smash_proj = _GL_TO_WGPU_CLIP @ rv3d.window_matrix
        cam = _view_eye(smash_view)
        pos = (float(cam.x), float(cam.y), float(cam.z), 1.0)
    else:
        z_near = 1.0
        z_far = 400000.0
        if space is not None:
            try:
                z_far = max(float(space.clip_end), z_near + 100.0)
            except Exception:
                pass
        half_w, half_h = _ortho_half_extents(rv3d, aspect)
        cam_dist = max(float(getattr(rv3d, "view_distance", 1.0)), _ORTHO_EYE_MIN)
        fov_y = 2.0 * math.atan(half_h / cam_dist)
        fov_y = min(max(fov_y, math.radians(0.05)), math.radians(120.0))
        smash_view = _view_at_distance(rv3d, cam_dist) @ _Y_UP_TO_Z_UP
        smash_proj = _perspective_rh(fov_y, half_w / half_h, z_near, z_far)
        cam = _view_eye(smash_view)
        pos = (float(cam.x), float(cam.y), float(cam.z), 1.0)
    return _mat4_col_major(smash_view), _mat4_col_major(smash_proj), pos


def _restore_floor_overlay():
    _restore_overlay_grids()


def _restore_overlay_grids():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        _saved_grids.clear()
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is None:
                continue
            saved = _saved_grids.pop(_id_key(space), None)
            if saved is None:
                continue
            overlay = getattr(space, "overlay", None)
            if overlay is None:
                continue
            ortho, floor = saved
            try:
                overlay.show_ortho_grid = ortho
                overlay.show_floor = floor
            except Exception:
                pass
    _saved_grids.clear()


def _skip_smash_bone(name):
    if not name:
        return True
    if name.startswith(_EXTRA_BONE_PREFIX) or name.startswith("SUB_"):
        return True
    return bool(_IK_BONE.match(name.split(".")[0]))


def _is_anim_rig(obj):
    if obj is None:
        return False
    if bool(obj.get(_ANIM_RIG_FLAG)):
        return True
    data = getattr(obj, "data", None)
    return bool(data is not None and data.get(_ANIM_RIG_FLAG))


def _iter_pose_armatures(depsgraph, context):
    try:
        from .create_animation_rig import find_target_armature
        preferred = find_target_armature(context)
    except Exception:
        preferred = None
    candidates = []
    if preferred is not None and _is_smash_armature(preferred):
        candidates.append(preferred)
    else:
        for obj in getattr(context.scene, "objects", []) or []:
            if _is_smash_armature(obj):
                candidates.append(obj)
                break
    for obj in candidates:
        try:
            yield obj.evaluated_get(depsgraph)
        except Exception:
            yield obj


def _collect_smash_bones(depsgraph, context):
    names = []
    matrices = []
    for arma in _iter_pose_armatures(depsgraph, context):
        pose = getattr(arma, "pose", None)
        if pose is None:
            continue
        world = arma.matrix_world
        for pbone in pose.bones:
            name = pbone.name
            if _skip_smash_bone(name):
                continue
            smash = _Z_UP_TO_Y_UP @ (world @ pbone.matrix) @ _Y_MAJOR_TO_X_MAJOR
            names.append(name)
            matrices.extend(_mat4_col_major(smash))
    return names, matrices


def _pose_fingerprint(depsgraph, context):
    parts = []
    for arma in _iter_pose_armatures(depsgraph, context):
        pose = getattr(arma, "pose", None)
        if pose is None:
            continue
        for pbone in pose.bones:
            if _skip_smash_bone(pbone.name):
                continue
            t = pbone.matrix.translation
            parts.append((round(t.x, 4), round(t.y, 4), round(t.z, 4)))
            if len(parts) >= 24:
                return tuple(parts)
    return tuple(parts)


def _set_camera(preview, rv3d, region, width, height, scale, space=None):
    view, proj, pos = _camera_to_smash(rv3d, region, width, height, space)
    view_arr = (c_float * 16)(*view)
    proj_arr = (c_float * 16)(*proj)
    pos_arr = (c_float * 4)(*pos)
    return _lib.ssbh_preview_set_camera(
        preview,
        view_arr,
        proj_arr,
        pos_arr,
        float(width),
        float(height),
        float(scale),
    )


def _set_bones(preview, depsgraph, context):
    global _name_keep
    names, matrices = _collect_smash_bones(depsgraph, context)
    if not names:
        return 0
    encoded = [n.encode("utf-8") for n in names]
    _name_keep = encoded
    name_arr = (c_char_p * len(encoded))(*encoded)
    mat_arr = (c_float * len(matrices))(*matrices)
    return _lib.ssbh_preview_set_world_transforms(
        preview,
        name_arr,
        mat_arr,
        len(encoded),
    )


def _smash_mesh_keys(obj):
    raw = obj.name or ""
    match = re.match(r"^(.*)\.(\d{3})$", raw)
    if match:
        full, sub = match.group(1), int(match.group(2))
    else:
        full, sub = raw, 0
    keys = [(full, sub)]
    trimmed = re.split(r"Shape|_VIS_|_O_", full)[0]
    if trimmed and trimmed != full:
        keys.append((trimmed, sub))
    return keys


def _mesh_hidden(obj, view_layer, space=None):
    try:
        if obj.hide_get():
            return True
    except Exception:
        pass
    if bool(getattr(obj, "hide_viewport", False)):
        return True
    try:
        if view_layer is not None:
            if not obj.visible_get(view_layer=view_layer):
                return True
        elif not obj.visible_get():
            return True
    except Exception:
        pass
    if space is not None:
        try:
            if not obj.visible_in_viewport_get(space):
                return True
        except Exception:
            pass
    return False


def _collect_mesh_visibility(context, space=None):
    names = []
    subindices = []
    visibles = []
    view_layer = getattr(context, "view_layer", None)
    scene = getattr(context, "scene", None)
    objects = getattr(scene, "objects", None) if scene is not None else None
    if objects is None:
        return names, subindices, visibles
    for obj in objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        name = obj.name or ""
        if name.startswith("SUB_WGT_"):
            continue
        hidden = _mesh_hidden(obj, view_layer, space)
        for name, sub in _smash_mesh_keys(obj):
            if not name:
                continue
            names.append(name)
            subindices.append(sub)
            visibles.append(0 if hidden else 1)
    return names, subindices, visibles


def _set_mesh_visibility_data(preview, names, subindices, visibles):
    global _vis_name_keep
    encoded = [n.encode("utf-8") for n in names]
    _vis_name_keep = encoded
    if not encoded:
        return _lib.ssbh_preview_set_mesh_visibility(
            preview, None, None, None, 0
        )
    name_arr = (c_char_p * len(encoded))(*encoded)
    sub_arr = (c_uint * len(subindices))(*subindices)
    vis_arr = (c_ubyte * len(visibles))(*visibles)
    return _lib.ssbh_preview_set_mesh_visibility(
        preview,
        name_arr,
        sub_arr,
        vis_arr,
        len(encoded),
    )


def _set_mesh_visibility(preview, context):
    names, subindices, visibles = _collect_mesh_visibility(context)
    return _set_mesh_visibility_data(preview, names, subindices, visibles)


def _cv31_from_sap(sap, name):
    if sap is None:
        return None
    tracks = getattr(sap, "mat_tracks", None)
    if tracks is None:
        return None
    track = tracks.get(name)
    prop = track.properties.get("CustomVector31") if track else None
    if prop is None:
        return None
    cv = prop.custom_vector
    return (float(cv[0]), float(cv[1]), float(cv[2]), float(cv[3]))


def _collect_custom_vector31(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return [], []
    try:
        from .eye_rig import EYE_CTRL_BONE, EYE_TRACKS, compute_cv31
    except Exception:
        return [], []
    ssp = getattr(scene, "sub_scene_properties", None)
    live = bool(ssp is not None and getattr(ssp, "eye_look_live_preview", False))
    try:
        from .create_animation_rig import find_target_armature
        preferred = find_target_armature(context)
    except Exception:
        preferred = None
    candidates = []
    if preferred is not None and _is_smash_armature(preferred):
        candidates.append(preferred)
    for obj in getattr(scene, "objects", []) or []:
        if not _is_smash_armature(obj):
            continue
        if obj not in candidates:
            candidates.append(obj)
    arma = None
    for obj in candidates:
        pose = getattr(obj, "pose", None)
        has_look = pose is not None and EYE_CTRL_BONE in pose.bones
        sap = getattr(obj.data, "sub_anim_properties", None) if obj.data else None
        has_tracks = (
            _cv31_from_sap(sap, "EyeL") is not None
            or _cv31_from_sap(sap, "EyeR") is not None
        )
        if has_look or has_tracks:
            arma = obj
            break
    if arma is None:
        return [], []
    sap = getattr(arma.data, "sub_anim_properties", None) if arma.data else None
    pbone = arma.pose.bones.get(EYE_CTRL_BONE) if arma.pose else None
    live_vals = None
    if live and pbone is not None and ssp is not None:
        try:
            live_vals = compute_cv31(arma, pbone, ssp)
        except Exception:
            live_vals = None
    names = []
    values = []
    for side in EYE_TRACKS:
        stored = _cv31_from_sap(sap, side)
        if live_vals is not None:
            left_u, right_u, v, scale = live_vals
            u = left_u if side == "EyeL" else right_u
            sx, sy = (stored[0], stored[1]) if stored is not None else (1.0, 1.0)
            if scale is not None:
                sx = sy = float(scale)
            names.append(side)
            values.extend((float(sx), float(sy), float(u), float(v)))
        elif stored is not None:
            names.append(side)
            values.extend(stored)
    return names, values


def _set_custom_vector31(preview, names, values):
    global _cv_name_keep
    setter = getattr(_lib, "ssbh_preview_set_custom_vector", None)
    if setter is None:
        return 0
    if not names:
        return setter(preview, None, b"CustomVector31", None, 0)
    encoded = [n.encode("utf-8") for n in names]
    _cv_name_keep = encoded
    name_arr = (c_char_p * len(encoded))(*encoded)
    val_arr = (c_float * len(values))(*values)
    return setter(
        preview,
        name_arr,
        b"CustomVector31",
        val_arr,
        len(encoded),
    )


def _find_preview_view():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return None
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is None or space.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            rv3d = getattr(space, "region_3d", None)
            if region is None or rv3d is None:
                continue
            return window, area, space, region, rv3d
    return None


def _apply_smash_color(scene):
    """Smash lighting is display-referred. AgX/Filmic wash it out."""
    if scene is None:
        return
    view = scene.view_settings
    key = _id_key(scene)
    if key not in _saved_color:
        _saved_color[key] = (
            str(view.view_transform),
            str(getattr(view, "look", "None")),
        )
    current = str(view.view_transform)
    if current not in {"Standard", "sRGB"}:
        for name in ("Standard", "sRGB"):
            try:
                view.view_transform = name
                break
            except Exception:
                continue
    if str(getattr(view, "look", "None")) != "None":
        try:
            view.look = "None"
        except Exception:
            pass


def _restore_smash_color(scene):
    if scene is None:
        return
    saved = _saved_color.pop(_id_key(scene), None)
    if saved is None:
        return
    transform, look = saved
    view = scene.view_settings
    try:
        view.view_transform = transform
    except Exception:
        pass
    try:
        view.look = look
    except Exception:
        pass


def _restore_engine(scene):
    if scene is None:
        return
    _restore_smash_color(scene)
    _set_viewport_meshes_visible(True)
    _restore_overlay_grids()
    if scene.render.engine != ENGINE_ID:
        return
    prev = _saved_engines.pop(_id_key(scene), "BLENDER_EEVEE")
    if prev == ENGINE_ID:
        prev = "BLENDER_EEVEE"
    try:
        scene.render.engine = prev
        return
    except Exception:
        pass
    for fallback in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = fallback
            return
        except Exception:
            continue


def _apply_engine(scene):
    if scene is None:
        return False
    key = _id_key(scene)
    current = scene.render.engine
    if key not in _saved_engines and current != ENGINE_ID:
        _saved_engines[key] = current
    try:
        scene.render.engine = ENGINE_ID
        return scene.render.engine == ENGINE_ID
    except Exception:
        return False


def _sync_checkbox(scene):
    global _ignore_update
    if scene is None:
        return
    ssp = getattr(scene, "sub_scene_properties", None)
    if ssp is None:
        return
    want = _engine_is_smash(scene)
    if bool(getattr(ssp, "smash_viewport", False)) == want:
        return
    _ignore_update = True
    try:
        ssp.smash_viewport = want
    except Exception:
        pass
    _ignore_update = False


def _on_engine_changed():
    scene = getattr(bpy.context, "scene", None)
    _sync_checkbox(scene)
    if _engine_is_smash(scene):
        _apply_smash_color(scene)
        _set_viewport_meshes_visible(True)
        _heal_hidden_floor()
        _use_rendered_shading()
        _ensure_timer()
        _tag_preview_redraw()
    else:
        _restore_smash_color(scene)
        _set_viewport_meshes_visible(True)
        _restore_overlay_grids()
        _stop_timer()
        shutdown_preview()


def _subscribe_engine():
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except Exception:
        pass
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.RenderSettings, "engine"),
            owner=_MSGBUS_OWNER,
            args=(),
            notify=_on_engine_changed,
        )
    except Exception:
        pass


def _use_rendered_shading():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is None or getattr(space, "type", "") != "VIEW_3D":
                continue
            shading = getattr(space, "shading", None)
            if shading is None:
                continue
            if getattr(shading, "type", "") == "RENDERED":
                continue
            try:
                shading.type = "RENDERED"
            except Exception:
                pass


def _undo_old_mesh_filter():
    _set_viewport_meshes_visible(True)


def _set_viewport_meshes_visible(visible):
    """Do not lock mesh filters. After a previous Smash hide, turn meshes back on."""
    global _saved_mesh_filter
    if not visible:
        return
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            if space is None or getattr(space, "type", "") != "VIEW_3D":
                continue
            _saved_mesh_filter.pop(_id_key(space), None)
            try:
                if not bool(getattr(space, "show_object_viewport_mesh", True)):
                    space.show_object_viewport_mesh = True
            except Exception:
                pass


def _heal_hidden_floor():
    """Do not touch Floor / Ortho Grid. Viewport Overlays owns those."""
    _restore_overlay_grids()


def _enable_smash_viewport(scene):
    _apply_engine(scene)
    _apply_smash_color(scene)
    _set_viewport_meshes_visible(True)
    _heal_hidden_floor()
    _use_rendered_shading()
    _ensure_timer()
    _tag_preview_redraw()


def _tag_preview_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            shading = getattr(space, "shading", None) if space is not None else None
            if shading is None or getattr(shading, "type", "") != "RENDERED":
                continue
            tagged = False
            for region in area.regions:
                if region.type == "WINDOW":
                    region.tag_redraw()
                    tagged = True
            if not tagged:
                area.tag_redraw()


def _using_gpu():
    if _lib is None or _preview is None:
        return False
    try:
        return int(_lib.ssbh_preview_using_gpu(_preview)) == 1
    except Exception:
        return False


def _apply_viewport_look(preview, scene):
    global _applied_bg, _applied_light, _applied_light_frame, _last_error
    if preview is None or _lib is None or scene is None:
        return
    ssp = getattr(scene, "sub_scene_properties", None)
    setter = getattr(_lib, "ssbh_preview_set_clear_color", None)
    if setter is not None and ssp is not None:
        color = getattr(ssp, "smash_vp_bg_color", (0.0, 0.0, 0.0))
        bg = (float(color[0]), float(color[1]), float(color[2]))
        if _applied_bg != bg:
            setter(preview, bg[0], bg[1], bg[2], 1.0)
            _applied_bg = bg
    frame = 0.0
    try:
        frame = float(scene.frame_current_final)
    except Exception:
        frame = float(getattr(scene, "frame_current", 0))
    frame_fn = getattr(_lib, "ssbh_preview_set_lighting_frame", None)
    if frame_fn is not None:
        if _applied_light_frame is None or abs(frame - _applied_light_frame) > 1e-4:
            frame_fn(preview, float(frame))
            _applied_light_frame = frame
    path = ""
    if ssp is not None:
        path = (getattr(ssp, "smash_vp_light_path", "") or "").strip()
    load_fn = getattr(_lib, "ssbh_preview_load_lighting", None)
    clear_fn = getattr(_lib, "ssbh_preview_clear_lighting", None)
    if path == (_applied_light or ""):
        return
    if path and os.path.isfile(path) and load_fn is not None:
        if load_fn(preview, path.encode("utf-8")) == 0:
            _applied_light = path
        else:
            _last_error = _native_error() or "Failed to load stage lights"
    elif not path and clear_fn is not None:
        clear_fn(preview)
        _applied_light = ""


def _preview_view_from_context(context=None):
    context = context or bpy.context
    space = getattr(context, "space_data", None)
    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if (
        space is not None
        and getattr(space, "type", "") == "VIEW_3D"
        and region is not None
        and getattr(region, "type", "") == "WINDOW"
        and rv3d is not None
    ):
        return space, region, rv3d
    found = _find_preview_view()
    if found is None:
        return None
    return found[2], found[3], found[4]


def _camera_key(rv3d, width, height, scale):
    vm = rv3d.view_matrix
    return (
        int(width),
        int(height),
        round(scale, 4),
        str(getattr(rv3d, "view_perspective", "")),
        round(vm[0][0], 5),
        round(vm[0][3], 4),
        round(vm[1][3], 4),
        round(vm[2][3], 4),
        round(float(getattr(rv3d, "view_distance", 0.0)), 4),
        round(float(getattr(rv3d, "view_camera_zoom", 0.0)), 4),
    )


def _prepare_preview(context=None, depsgraph=None):
    global _last_status, _last_error, _pixel_size, _last_tick_key
    global _last_pose_fp, _last_vis_state, _last_cv31_state
    global _last_cam_key, _last_frame
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not _viewport_enabled(scene):
        return None
    if not _scene_has_smash_model(scene):
        if _preview is not None or _loaded_folder:
            shutdown_preview()
        return None
    preview = _ensure_preview()
    if not preview:
        return None
    if not _ensure_model(scene):
        return None
    found = _preview_view_from_context(context)
    if found is None:
        return None
    space, region, rv3d = found
    dest_w = max(int(region.width), 1)
    dest_h = max(int(region.height), 1)
    scale = 1.0
    try:
        scale = float(context.preferences.system.ui_scale)
    except Exception:
        pass
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    vis_names, vis_subs, vis_vals = _collect_mesh_visibility(context, space)
    vis_state = tuple(vis_vals)
    pose_fp = _pose_fingerprint(depsgraph, context)
    width = dest_w
    height = dest_h
    size_changed = _pixel_size != (width, height) or _last_tick_key is None
    needs_gpu = size_changed
    if size_changed:
        if _lib.ssbh_preview_resize(preview, width, height, scale) != 0:
            _last_error = _native_error() or "resize failed"
            return None
        _last_cam_key = None
    if _set_camera(preview, rv3d, region, width, height, scale, space) != 0:
        _last_error = _native_error() or "camera failed"
        return None
    _last_cam_key = _camera_key(rv3d, width, height, scale)
    needs_gpu = True
    if _set_bones(preview, depsgraph, context) != 0:
        _last_error = _native_error() or "bones failed"
        return None
    _last_pose_fp = pose_fp
    _apply_viewport_look(preview, scene)
    if vis_state != _last_vis_state:
        if _set_mesh_visibility_data(preview, vis_names, vis_subs, vis_vals) != 0:
            _last_error = _native_error() or "visibility failed"
            return None
        _last_vis_state = vis_state
        needs_gpu = True
    cv_names, cv_vals = _collect_custom_vector31(context)
    cv_state = (tuple(cv_names), tuple(round(v, 5) for v in cv_vals))
    if cv_state != _last_cv31_state:
        if cv_names or _last_cv31_state is not None:
            if _set_custom_vector31(preview, cv_names, cv_vals) != 0:
                _last_error = _native_error() or "eye materials failed"
                return None
        _last_cv31_state = cv_state
        needs_gpu = True
    try:
        frame = float(scene.frame_current_final)
    except Exception:
        frame = float(getattr(scene, "frame_current", 0))
    if _last_frame is None or abs(frame - _last_frame) > 1e-4:
        _last_frame = frame
        needs_gpu = True
    _last_tick_key = (width, height)
    _pixel_size = (width, height)
    return preview, width, height, size_changed, region, rv3d, needs_gpu


def _cpu_render(preview, width, height, force=False, wait=False):
    global _last_status, _last_error, _pixels, _pixel_size, _pixel_version
    needed = width * height * 4
    if needed < 4:
        return False
    if len(_pixels) != needed:
        _pixels = bytearray(needed)
        force = True
    out_w = c_uint(0)
    out_h = c_uint(0)
    buf = (ctypes.c_uint8 * needed).from_buffer(_pixels)
    if wait and hasattr(_lib, "ssbh_preview_render_wait"):
        native_fn = _lib.ssbh_preview_render_wait
    else:
        native_fn = _lib.ssbh_preview_render if force else _lib.ssbh_preview_poll
    rc = native_fn(
        preview,
        ctypes.addressof(buf),
        needed,
        ctypes.byref(out_w),
        ctypes.byref(out_h),
    )
    if rc < 0:
        _last_error = _native_error() or "render failed"
        return False
    _pixel_size = (int(out_w.value or width), int(out_h.value or height))
    if rc == 0:
        _pixel_version += 1
    status = f"{_pixel_size[0]}x{_pixel_size[1]} ssbh_wgpu CPU"
    if _last_status != status:
        _last_status = status
    return True


def capture_rgba_frame(
    context=None,
    transparent=True,
    restore_background=True,
    flush=True,
    wait=False,
):
    """RGBA screenshot of Smash Viewport. Transparent pixels have alpha 0.

    Returns (width, height, bytes) or None if Smash Viewport is not drawing.
    """
    global _applied_bg, _pixels, _pixel_size
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not _viewport_enabled(scene):
        return None
    prepared = _prepare_preview(context)
    if prepared is None:
        return None
    preview, width, height = prepared[0], prepared[1], prepared[2]
    setter = getattr(_lib, "ssbh_preview_set_clear_color", None) if _lib else None
    ssp = getattr(scene, "sub_scene_properties", None)
    color = (0.0, 0.0, 0.0)
    if ssp is not None:
        bg = getattr(ssp, "smash_vp_bg_color", None)
        if bg is not None and len(bg) >= 3:
            color = (float(bg[0]), float(bg[1]), float(bg[2]))
    if transparent and setter is not None:
        setter(preview, 0.0, 0.0, 0.0, 0.0)
        # Stop _apply_viewport_look from putting the opaque clear back.
        _applied_bg = color
    if not _cpu_render(preview, width, height, force=True, wait=wait):
        if restore_background:
            restore_opaque_background(context)
        return None
    if flush and not wait:
        _cpu_render(preview, width, height, force=True)
    w, h = int(_pixel_size[0] or width), int(_pixel_size[1] or height)
    needed = max(0, w * h * 4)
    data = bytes(_pixels[:needed]) if needed else b""
    if restore_background:
        restore_opaque_background(context)
    if not data:
        return None
    return w, h, data


def restore_opaque_background(context=None):
    global _applied_bg
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    if _lib is None or _preview is None or scene is None:
        return
    setter = getattr(_lib, "ssbh_preview_set_clear_color", None)
    if setter is None:
        return
    color = (0.0, 0.0, 0.0)
    ssp = getattr(scene, "sub_scene_properties", None)
    if ssp is not None:
        bg = getattr(ssp, "smash_vp_bg_color", None)
        if bg is not None and len(bg) >= 3:
            color = (float(bg[0]), float(bg[1]), float(bg[2]))
    setter(_preview, color[0], color[1], color[2], 1.0)
    _applied_bg = color


def _tick():
    prepared = _prepare_preview()
    if prepared is None:
        return
    preview, width, height, size_changed, _region, _rv3d, _needs_gpu = prepared
    _cpu_render(preview, width, height, force=size_changed)
    _tag_preview_redraw()


def _preview_timer():
    global _timer_running
    if not _viewport_enabled():
        shutdown_preview()
        _timer_running = False
        return None
    return None


@persistent
def _on_scene_redraw(*_args):
    return


@persistent
def _on_frame_change(*_args):
    if not _viewport_enabled():
        return
    _tag_preview_redraw()


def _ensure_timer():
    global _timer_running
    if _timer_running:
        return
    if _on_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_on_frame_change)
    _timer_running = True


def _stop_timer():
    global _timer_running
    _timer_running = False
    for coll in (
        bpy.app.handlers.depsgraph_update_post,
        bpy.app.handlers.frame_change_post,
    ):
        for fn in (_on_scene_redraw, _on_frame_change):
            try:
                coll.remove(fn)
            except Exception:
                pass
    try:
        if bpy.app.timers.is_registered(_preview_timer):
            bpy.app.timers.unregister(_preview_timer)
    except Exception:
        pass


def _blit_rgba(width, height, pixels, dest_w=None, dest_h=None):
    import gpu
    import numpy as np
    from gpu_extras.presets import draw_texture_2d

    global _float_pixels, _blit_tex, _blit_tex_key, _blit_ubyte_ok
    needed = width * height * 4
    if width < 1 or height < 1 or len(pixels) < needed:
        return
    dest_w = max(int(dest_w or width), 1)
    dest_h = max(int(dest_h or height), 1)
    tex_key = (_pixel_version, width, height)
    texture = _blit_tex
    if texture is None or _blit_tex_key != tex_key:
        src = np.frombuffer(pixels, dtype=np.uint8, count=needed)
        alpha = src[3::4]
        src = src.copy()
        src[3::4] = np.where(alpha < 10, 0, 255)
        texture = None
        if _blit_ubyte_ok:
            try:
                ubyte = gpu.types.Buffer("UBYTE", needed, src)
                texture = gpu.types.GPUTexture((width, height), format="RGBA8", data=ubyte)
            except Exception:
                _blit_ubyte_ok = False
                texture = None
        if texture is None:
            if _float_pixels is None or _float_pixels.size != needed:
                _float_pixels = np.empty(needed, dtype=np.float32)
            np.multiply(src, np.float32(1.0 / 255.0), out=_float_pixels)
            buf = gpu.types.Buffer("FLOAT", needed, _float_pixels)
            texture = gpu.types.GPUTexture((width, height), format="RGBA8", data=buf)
        _blit_tex = texture
        _blit_tex_key = tex_key
    prev_blend = "NONE"
    try:
        prev_blend = gpu.state.blend_get()
    except Exception:
        pass
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("ALPHA")
    identity = Matrix.Identity(4)
    proj = Matrix.Identity(4)
    proj[0][0] = 2.0 / float(dest_w)
    proj[1][1] = -2.0 / float(dest_h)
    proj[0][3] = -1.0
    proj[1][3] = 1.0
    try:
        with gpu.matrix.push_pop():
            gpu.matrix.load_projection_matrix(proj)
            try:
                gpu.matrix.load_matrix(identity)
            except Exception:
                gpu.matrix.load_identity()
            draw_texture_2d(texture, (0, 0), dest_w, dest_h)
    finally:
        try:
            gpu.state.blend_set(prev_blend or "NONE")
        except Exception:
            gpu.state.blend_set("NONE")


def update_smash_viewport(self, context):
    if _ignore_update:
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    enabled = bool(getattr(self, "smash_viewport", False))
    if enabled:
        if not native_plugin_path():
            global _last_error
            _last_error = (
                "Smash Viewport plugin not found. See native/README.md."
            )
        _enable_smash_viewport(scene)
        return
    if scene.render.engine == ENGINE_ID:
        _restore_engine(scene)
    _stop_timer()
    shutdown_preview()


def update_smash_vp_background(_self, _context):
    global _applied_bg
    _applied_bg = None
    _tag_preview_redraw()


def update_smash_vp_lighting(_self, _context):
    global _applied_light
    _applied_light = None
    _tag_preview_redraw()


def draw_smash_viewport_ui(layout, context):
    ssp = getattr(context.scene, "sub_scene_properties", None)
    if ssp is None:
        return
    box = layout.box()
    box.label(text="Smash Viewport (ssbh_wgpu)", icon="SHADING_RENDERED")
    box.prop(ssp, "smash_viewport", text="Smash Viewport Engine")
    path = native_plugin_path()
    if path:
        box.label(text="Plugin: " + os.path.basename(path), icon="CHECKMARK")
    else:
        box.label(text="Plugin not built. See native/README.md", icon="ERROR")
    folder = _model_folder(context.scene)
    if not _scene_has_smash_model(context.scene):
        box.label(text="No Smash model in the scene", icon="INFO")
    elif folder:
        box.label(text=os.path.basename(folder.rstrip("\\/")))
    else:
        box.label(text="No imported model folder", icon="INFO")
    box.label(text="Turns on Rendered shading so Smash is visible.")
    box.label(text="Uses Standard view transform (AgX washes Smash).")
    if _last_status:
        box.label(text=_last_status)
    if _last_error:
        box.label(text=_last_error, icon="ERROR")


def _unregister_old_classes():
    for name in (
        "SUB_OP_close_smash_viewport",
        "SUB_OP_open_smash_viewport",
        "SUB_OP_smash_vp_load_lighting",
        "SUB_OP_smash_vp_reset_lighting",
        "RENDER_PT_smash_viewport",
        "SUB_RenderEngine_smash_viewport",
    ):
        cls = getattr(bpy.types, name, None)
        if cls is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


def _bg_rgba(scene=None):
    color = (0.0, 0.0, 0.0, 1.0)
    scene = scene or getattr(bpy.context, "scene", None)
    ssp = getattr(scene, "sub_scene_properties", None) if scene is not None else None
    if ssp is not None:
        bg = getattr(ssp, "smash_vp_bg_color", None)
        if bg is not None and len(bg) >= 3:
            color = (float(bg[0]), float(bg[1]), float(bg[2]), 1.0)
    return color


def _viewport_pixel_size(context=None):
    region = getattr(context, "region", None) if context is not None else None
    if region is None:
        region = getattr(bpy.context, "region", None)
    if region is not None:
        try:
            return max(int(region.width), 1), max(int(region.height), 1)
        except Exception:
            pass
    try:
        import gpu
        _x, _y, w, h = gpu.state.viewport_get()
        return max(int(w), 1), max(int(h), 1)
    except Exception:
        return 1, 1


def _fill_viewport_color(dest_w=None, dest_h=None, color=None):
    """Paint the 3D region with the Smash background. No framebuffer clear."""
    import gpu
    from gpu_extras.batch import batch_for_shader

    if dest_w is None or dest_h is None:
        dest_w, dest_h = _viewport_pixel_size()
    dest_w = max(int(dest_w), 1)
    dest_h = max(int(dest_h), 1)
    if color is None:
        color = _bg_rgba()
    try:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    except Exception:
        shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {
            "pos": (
                (0.0, 0.0),
                (float(dest_w), 0.0),
                (float(dest_w), float(dest_h)),
                (0.0, float(dest_h)),
            )
        },
    )
    prev_blend = "NONE"
    prev_depth = "NONE"
    try:
        prev_blend = gpu.state.blend_get()
    except Exception:
        pass
    try:
        prev_depth = gpu.state.depth_test_get()
    except Exception:
        pass
    identity = Matrix.Identity(4)
    proj = Matrix.Identity(4)
    proj[0][0] = 2.0 / float(dest_w)
    proj[1][1] = -2.0 / float(dest_h)
    proj[0][3] = -1.0
    proj[1][3] = 1.0
    try:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
        with gpu.matrix.push_pop():
            gpu.matrix.load_projection_matrix(proj)
            try:
                gpu.matrix.load_matrix(identity)
            except Exception:
                gpu.matrix.load_identity()
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
    except Exception:
        pass
    finally:
        try:
            gpu.state.blend_set(prev_blend or "NONE")
        except Exception:
            pass
        try:
            gpu.state.depth_test_set(prev_depth or "NONE")
        except Exception:
            pass


def _draw_smash_overlay(context=None, depsgraph=None):
    global _last_error, _last_status, _last_draw_mono
    if not _viewport_enabled():
        return
    context = context or bpy.context
    _last_draw_mono = time.monotonic()
    prepared = _prepare_preview(context, depsgraph)
    if prepared is None:
        dest_w, dest_h = _viewport_pixel_size(context)
        _fill_viewport_color(dest_w, dest_h)
        return
    preview, width, height, size_changed, region, rv3d, needs_gpu = prepared
    dest_w = width
    dest_h = height
    if region is not None:
        dest_w = max(int(region.width), 1)
        dest_h = max(int(region.height), 1)
    global _gpu_failed
    if size_changed:
        _gpu_failed = False
    gpu_rc = -2
    flags = 1 if needs_gpu else 0
    if not _gpu_failed:
        try:
            gpu_rc = int(
                _lib.ssbh_preview_present_gl(
                    preview, dest_w, dest_h, flags
                )
            )
        except Exception as exc:
            _last_error = str(exc)
            gpu_rc = -1
        if gpu_rc == 0:
            _last_error = ""
            status = f"{width}x{height} ssbh_wgpu GPU"
            if _last_status != status:
                _last_status = status
            return
        _gpu_failed = True
        gpu_note = _native_error()
        if gpu_note:
            _last_error = gpu_note
    _cpu_render(preview, width, height, force=True)
    tex_w, tex_h = _pixel_size
    if tex_w < 1 or tex_h < 1 or not _pixels:
        _fill_viewport_color(dest_w, dest_h)
        return
    try:
        _blit_rgba(tex_w, tex_h, _pixels, dest_w, dest_h)
    except Exception as exc:
        _last_error = f"Blit failed: {exc}"
        _fill_viewport_color(dest_w, dest_h)


def _ensure_draw_handler():
    handler = getattr(bpy.types.SpaceView3D, _DRAW_HANDLER_ATTR, None)
    if handler is not None:
        return
    try:
        handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_smash_overlay, (), "WINDOW", "POST_VIEW"
        )
    except Exception:
        return
    setattr(bpy.types.SpaceView3D, _DRAW_HANDLER_ATTR, handler)


def _remove_draw_handler():
    handler = getattr(bpy.types.SpaceView3D, _DRAW_HANDLER_ATTR, None)
    if handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except Exception:
            pass
        try:
            delattr(bpy.types.SpaceView3D, _DRAW_HANDLER_ATTR)
        except Exception:
            pass


def _restore_engines_safe():
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        return
    for scene in scenes:
        try:
            _restore_engine(scene)
        except Exception:
            continue


class SUB_OP_smash_vp_load_lighting(bpy.types.Operator, ImportHelper):
    bl_idname = "sub.smash_vp_load_lighting"
    bl_label = "Load Stage Lights"
    bl_description = (
        "Load a stage light.nuanmb the same way SSBH Editor does "
        "(often stage/light/light00.nuanmb or light.nuanmb)"
    )
    bl_options = {"REGISTER"}

    filename_ext = ".nuanmb"
    filter_glob: StringProperty(default="*.nuanmb", options={"HIDDEN"})

    def invoke(self, context, event):
        ssp = getattr(context.scene, "sub_scene_properties", None)
        last = ""
        if ssp is not None:
            last = (
                getattr(ssp, "smash_vp_light_path", "")
                or getattr(ssp, "last_stage_light_dir", "")
            )
        if last:
            if os.path.isfile(last):
                self.filepath = last
            elif os.path.isdir(last):
                for name in (
                    "light.nuanmb",
                    "light00.nuanmb",
                    os.path.join("light", "light00.nuanmb"),
                    os.path.join("light", "light.nuanmb"),
                ):
                    cand = os.path.join(last, name)
                    if os.path.isfile(cand):
                        self.filepath = cand
                        break
                else:
                    self.filepath = os.path.join(last, "light.nuanmb")
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        global _applied_light
        ssp = getattr(context.scene, "sub_scene_properties", None)
        path = self.filepath
        if ssp is not None:
            ssp.smash_vp_light_path = path
            ssp.last_stage_light_dir = os.path.dirname(path)
        _applied_light = None
        preview = _preview
        load_fn = getattr(_lib, "ssbh_preview_load_lighting", None) if _lib else None
        if preview and load_fn:
            if load_fn(preview, path.encode("utf-8")) != 0:
                self.report({"ERROR"}, _native_error() or "Failed to load lighting")
                return {"CANCELLED"}
            _applied_light = path
        _tag_preview_redraw()
        self.report({"INFO"}, "Loaded " + os.path.basename(path))
        return {"FINISHED"}


class SUB_OP_smash_vp_reset_lighting(bpy.types.Operator):
    bl_idname = "sub.smash_vp_reset_lighting"
    bl_label = "Training Lights"
    bl_description = "Reset Smash Viewport lighting to the default training-stage lights"
    bl_options = {"REGISTER"}

    def execute(self, context):
        global _applied_light
        ssp = getattr(context.scene, "sub_scene_properties", None)
        if ssp is not None:
            ssp.smash_vp_light_path = ""
        _applied_light = None
        clear_fn = getattr(_lib, "ssbh_preview_clear_lighting", None) if _lib else None
        if _preview and clear_fn:
            clear_fn(_preview)
            _applied_light = ""
        _tag_preview_redraw()
        return {"FINISHED"}


class RENDER_PT_smash_viewport(bpy.types.Panel):
    bl_label = "Smash Viewport"
    bl_idname = "RENDER_PT_smash_viewport"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"
    COMPAT_ENGINES = {ENGINE_ID}

    @classmethod
    def poll(cls, context):
        return getattr(context, "engine", "") in cls.COMPAT_ENGINES

    def draw(self, context):
        layout = self.layout
        ssp = getattr(context.scene, "sub_scene_properties", None)
        if ssp is None:
            return
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(ssp, "smash_vp_bg_color", text="Background")
        col = layout.column(align=True)
        col.prop(ssp, "smash_vp_light_path", text="Stage Lights")
        row = layout.row(align=True)
        row.operator(
            SUB_OP_smash_vp_load_lighting.bl_idname,
            text="Load Stage Lights",
            icon="IMPORT",
        )
        row.operator(
            SUB_OP_smash_vp_reset_lighting.bl_idname,
            text="Training Lights",
            icon="LOOP_BACK",
        )
        path = (getattr(ssp, "smash_vp_light_path", "") or "").strip()
        if path:
            layout.label(text=os.path.basename(path))
        else:
            layout.label(text="Using training-stage lights")


class SUB_RenderEngine_smash_viewport(bpy.types.RenderEngine):
    bl_idname = ENGINE_ID
    bl_label = "Smash Viewport"
    bl_use_preview = False
    bl_use_gpu_context = True
    bl_use_postprocess = False
    bl_use_eevee_viewport = False

    def render(self, depsgraph):
        return

    def view_update(self, context, depsgraph):
        return

    def view_draw(self, context, depsgraph):
        _draw_smash_overlay(context, depsgraph)


def _resume_if_enabled():
    global _resume_attempts, _ignore_update
    scene = _first_scene()
    if scene is None:
        _resume_attempts += 1
        return 0.2 if _resume_attempts < 25 else None
    if _scene_wants_smash(scene):
        _enable_smash_viewport(scene)
        ssp = getattr(scene, "sub_scene_properties", None)
        if ssp is not None and not bool(getattr(ssp, "smash_viewport", False)):
            _ignore_update = True
            try:
                ssp.smash_viewport = True
            except Exception:
                pass
            _ignore_update = False
        if not _has_rendered_3d_view() and _resume_attempts < 25:
            _resume_attempts += 1
            return 0.2
        _resume_attempts = 0
        return None
    _sync_checkbox(scene)
    _resume_attempts = 0
    return None


@persistent
def _load_post(_dummy):
    _subscribe_engine()
    _resume_if_enabled()


_SMASH_VP_CLASSES = (
    SUB_OP_smash_vp_load_lighting,
    SUB_OP_smash_vp_reset_lighting,
    RENDER_PT_smash_viewport,
    SUB_RenderEngine_smash_viewport,
)


def register():
    _unregister_old_classes()
    _remove_draw_handler()
    for cls in _SMASH_VP_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)
    _subscribe_engine()
    bpy.app.timers.register(_resume_if_enabled, first_interval=0.15)


def unregister():
    _stop_timer()
    shutdown_preview()
    _set_viewport_meshes_visible(True)
    _remove_draw_handler()
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except Exception:
        pass
    try:
        bpy.app.handlers.load_post.remove(_load_post)
    except Exception:
        pass
    _restore_engines_safe()
    for cls in reversed(_SMASH_VP_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _unregister_old_classes()
