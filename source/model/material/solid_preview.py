"""Workbench color previews, separate from the exported textures and shader graph.

Workbench ignores shader nodes: rasterize the second UV set into map1 once,
then resample the layers only when their transforms or color multipliers change.
"""
import logging
import bpy
import numpy as np
from bpy.app.handlers import persistent

NODE = 'SUB_SolidPreview'
PREVIOUS = 'sub_solid_previous_node'
PREVIOUS_UV = 'sub_solid_previous_uv'
_cache = {}
_revisions = {}
_mesh_revisions = {}
_uv_signatures = {}
_dirty = set()
_index = None
_structure_dirty = True
_engaged = False
_needs_restore = True
_message_owner = object()
_busy = False
_log = logging.getLogger(__name__)


def _vector(material, name, default):
    prop = material.sub_matl_data.vectors.get(name)
    value = tuple(prop.value) if prop else default
    # SAP animation drives the value nodes independently of static MATL data.
    nodes = material.node_tree.nodes
    return tuple(float(nodes[name + '_' + axis].outputs[0].default_value)
                 if nodes.get(name + '_' + axis) else float(value[i])
                 for i, axis in enumerate('XYZW'))


def _texture(material, name):
    prop = material.sub_matl_data.textures.get(name)
    node = material.node_tree.nodes.get(prop.node_name if prop else name)
    image = prop.image if prop else getattr(node, 'image', None)
    sampler = material.sub_matl_data.samplers.get(name.replace('Texture', 'Sampler'))
    wrapping = (sampler.wrap_s, sampler.wrap_t) if sampler else getattr(node, 'extension', 'REPEAT')
    return image, wrapping


def _pixels(image):
    width, height = image.size
    buf = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(buf)
    return buf.reshape(height, width, 4)


def _sample(image, uv, extension):
    if image is None or min(image.size) < 1:
        return np.zeros((*uv.shape[:-1], 4), dtype=np.float32)
    pixels = _pixels(image)
    h, w = pixels.shape[:2]
    uv = np.asarray(uv, dtype=np.float32)
    modes = extension if isinstance(extension, tuple) else (extension, extension)
    coords = np.array(uv, copy=True)
    for axis, mode in enumerate(modes):
        if mode in {'REPEAT', 'Repeat'}:
            coords[...,axis] %= 1.0
        elif mode == 'MirroredRepeat':
            coords[...,axis] = 1.0 - np.abs(coords[...,axis] % 2.0 - 1.0)
        else:
            coords[...,axis] = np.clip(coords[...,axis], 0.0, 1.0)
    xy = coords * np.asarray((w,h), dtype=np.float32) - np.float32(.5)
    lower_float = np.floor(xy)
    lower = lower_float.astype(np.int32)
    fraction = xy - lower_float
    x, y = lower[...,0], lower[...,1]
    if modes[0] in {'REPEAT', 'Repeat'}:
        x0, x1 = x % w, (x+1) % w
    else:
        x0, x1 = np.clip(x,0,w-1), np.clip(x+1,0,w-1)
    if modes[1] in {'REPEAT', 'Repeat'}:
        y0, y1 = y % h, (y+1) % h
    else:
        y0, y1 = np.clip(y,0,h-1), np.clip(y+1,0,h-1)
    fx, fy = fraction[...,0:1], fraction[...,1:2]
    inverse_x = 1-fx
    # Blend in place to avoid a chain of full-resolution temporary RGBA arrays.
    result = pixels[y0,x0]
    result *= inverse_x
    scratch = pixels[y0,x1]
    scratch *= fx
    result += scratch
    result *= 1-fy
    row = pixels[y1,x0]
    row *= inverse_x
    scratch = pixels[y1,x1]
    scratch *= fx
    row += scratch
    row *= fy
    result += row
    if extension == 'CLIP':
        result *= np.all((uv >= 0) & (uv <= 1), axis=-1)[..., None]
    return result



def _image_grid(size):
    h, w = size
    y, x = np.indices((h, w), dtype=np.float32)
    return np.stack(((x+.5)/w, (y+.5)/h), axis=-1)

def _uv_grid(meshes, material, size):
    """Map preview pixels in map1 to the mesh's independent uvSet coordinates."""
    h, w = size
    grid = _image_grid(size)
    second = grid.copy()
    for obj in meshes:
        mesh = obj.data
        base, overlay = mesh.uv_layers.get('map1'), mesh.uv_layers.get('uvSet')
        if base is None or overlay is None:
            continue
        mesh.calc_loop_triangles()
        for triangle in mesh.loop_triangles:
            if mesh.materials[triangle.material_index] != material:
                continue
            a = np.array([base.data[i].uv[:] for i in triangle.loops])
            b = np.array([overlay.data[i].uv[:] for i in triangle.loops])
            lo = np.maximum(np.floor(a.min(axis=0)*(w,h)-1).astype(int), 0)
            hi = np.minimum(np.ceil(a.max(axis=0)*(w,h)+1).astype(int), (w,h))
            if np.any(hi <= lo):
                continue
            matrix = np.stack((a[1]-a[0], a[2]-a[0]), axis=1)
            if abs(np.linalg.det(matrix)) < 1e-12:
                continue
            region = grid[lo[1]:hi[1], lo[0]:hi[0]]
            weights = (region-a[0]) @ np.linalg.inv(matrix).T
            inside = (weights[..., 0] >= -1e-5) & (weights[..., 1] >= -1e-5) & (weights.sum(axis=-1) <= 1.00001)
            mapped = b[0] + weights[..., 0:1]*(b[1]-b[0]) + weights[..., 1:2]*(b[2]-b[0])
            second[lo[1]:hi[1], lo[0]:hi[0]][inside] = mapped[inside]
    return grid, second



def _uv_signature(mesh):
    parts = []
    for name in ('map1', 'uvSet'):
        layer = mesh.uv_layers.get(name)
        if layer is not None:
            buf = np.empty(len(mesh.loops)*2, dtype=np.float32)
            layer.data.foreach_get('uv', buf)
            parts.append(hash(buf.tobytes()))
    indices = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get('material_index', indices)
    return (*parts, hash(indices.tobytes()))


def _mesh_uv_signature(mesh, check):
    token = mesh.as_pointer()
    revision = _mesh_revisions.get(token, 0)
    cached = _uv_signatures.get(token)
    if check or cached is None or cached[0] != revision:
        cached = (revision, _uv_signature(mesh))
        _uv_signatures[token] = cached
    return cached[1]

def _eye_transform(material, arma, scene):
    from ...extras import eye_rig
    if arma is not None:
        ssp = getattr(scene, 'sub_scene_properties', None)
        control = arma.pose.bones.get(eye_rig.EYE_CTRL_BONE)
        if control is not None and ssp and ssp.eye_look_live_preview:
            left, right, v, scale = eye_rig.compute_cv31(arma, control, ssp)
            scale = 1.0 if scale is None else float(scale)
            side = 'EyeL' if material.name.startswith('EyeL') else 'EyeR'
            return (scale, scale, left if side == 'EyeL' else right, v)
        value = eye_rig._cv31_for_eye_mesh(arma, material)
        if value is not None:
            return tuple(value)
    return _vector(material, 'CustomVector31', (1,1,0,0))


def _publish(material, pixels):
    nodes = material.node_tree.nodes
    node = nodes.get(NODE)
    if node is None:
        node = nodes.new('ShaderNodeTexImage')
        node.name, node.label = NODE, 'Solid View Preview (not exported)'
        node.location = (-2200, -2300)
    h, w = pixels.shape[:2]
    image = node.image
    if image is None:
        image = bpy.data.images.new('SUB_SolidPreview::' + material.name, w, h,
                                    alpha=True, float_buffer=True)
        node.image = image
    elif tuple(image.size) != (w, h):
        image.scale(w, h)
    if image.colorspace_settings.name != 'Linear Rec.709':
        image.colorspace_settings.name = 'Linear Rec.709'
    if image.alpha_mode != 'STRAIGHT':
        image.alpha_mode = 'STRAIGHT'
    image.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).reshape(-1))
    image.update()
    if node.extension != 'EXTEND':
        node.extension = 'EXTEND'
    return node


def update_material(material, meshes, arma=None, scene=None, *, check_uv=True):
    if not material.use_nodes or not material.node_tree:
        return False
    data = material.sub_matl_data
    if not data.shader_label:
        return False
    scene = scene or bpy.context.scene
    diffuse = _vector(material, 'CustomVector13', (1,1,1,1))
    emission = _vector(material, 'CustomVector3', (1,1,1,1))
    final = _vector(material, 'CustomVector8', (1,1,1,1))
    texture_names = ('Texture0', 'Texture1', 'Texture5', 'Texture14')
    textures = [_texture(material, n) for n in texture_names]
    if not any(image and min(image.size) > 0 for image, _ in textures):
        return False
    eye = any(n.param_id_name == 'CustomVector31' for n in data.vectors) and any(
        textures[i][0] is not None for i in (1,3))
    transform = _eye_transform(material, arma, scene) if eye else _vector(material, 'CustomVector31', (1,1,0,0))
    first_transform = _vector(material, 'CustomVector6', (1,1,0,0))
    # A single untinted layer is already a valid Workbench image. Avoid
    # allocating a full-size duplicate for materials that need no shader math.
    if not eye and not any(textures[i][0] for i in (1,3)) and first_transform == (1,1,0,0):
        index = 0 if textures[0][0] is not None and textures[2][0] is None else 2
        if ((index == 0 and textures[2][0] is None and diffuse[:3] == (1,1,1))
                or (index == 2 and textures[0][0] is None and emission[:3] == (1,1,1))):
            prop = data.textures.get(texture_names[index])
            node = material.node_tree.nodes.get(prop.node_name if prop else texture_names[index])
            if node and textures[index][0] is not None and final[:3] == (1,1,1):
                return _activate(material, node, meshes)
    geometry = tuple((o.data.as_pointer(), len(o.data.loops), len(o.data.polygons),
                      _mesh_uv_signature(o.data, check_uv) if any(textures[i][0] for i in (1,3)) else ()) for o in meshes)
    image_state = tuple((im.as_pointer(), tuple(im.size), im.is_dirty, ext,
                         _revisions.get(im.as_pointer(), 0)) if im else None for im, ext in textures)
    key = (geometry, image_state, diffuse, emission, final, transform, first_transform)
    pointer = material.as_pointer()
    cached = _cache.get(pointer)
    nodes = material.node_tree.nodes
    node = nodes.get(NODE)
    if cached is None or cached['key'] != key or node is None or node.image is None:
        # Eyes need independent UV sets; ordinary tinted textures keep their resolution.
        width = max(im.size[0] for im, _ in textures if im)
        height = max(im.size[1] for im, _ in textures if im)
        limit = 512 if eye else 2048
        factor = min(1.0, limit/max(width, height))
        w, h = max(8, int(width*factor)), max(8, int(height*factor))
        geometry_key = (geometry, h, w)
        layered = any(textures[i][0] for i in (1,3))
        # Only layered materials need a persistent UV correspondence map.
        # Ordinary tints multiply pixels directly and retain no UV arrays.
        uv = second = uv1 = uv2 = None
        if layered:
            if cached is not None and cached['geometry'] == geometry_key and cached['uv'] is not None:
                uv, second = cached['uv']
            else:
                uv, second = _uv_grid(meshes, material, (h,w))
            first_values = np.asarray(first_transform, dtype=np.float32)
            second_values = np.asarray(transform, dtype=np.float32)
            uv1 = (uv - first_values[2:])*first_values[:2]
            uv2 = (second - second_values[2:])*second_values[:2]
        elif first_transform != (1,1,0,0):
            uv1 = (_image_grid((h,w)) - np.asarray(first_transform[2:],dtype=np.float32))*np.asarray(first_transform[:2],dtype=np.float32)
        base_key = (geometry_key, image_state[0], image_state[2], first_transform)
        bases = None
        if layered:
            if cached is not None and cached.get('base_key') == base_key:
                bases = cached['bases']
            else:
                bases = (_sample(textures[0][0], uv1, textures[0][1]),
                         _sample(textures[2][0], uv1, textures[2][1]))
        def layer(base, overlay):
            # The stationary layer does not need resampling when only the eye
            # offset changes. Copy before tinting; cached source colors stay raw.
            result = base.copy()
            if overlay[0] is not None:
                b = _sample(overlay[0], uv2, overlay[1])
                alpha = b[...,3:4]
                result[...,:3] = base[...,:3]*(1-alpha) + b[...,:3]*alpha
            return result
        direct = not layered and first_transform == (1,1,0,0)
        def first_layer(texture):
            nonlocal uv1
            image = texture[0]
            if image is None:
                return np.zeros((h,w,4), dtype=np.float32)
            if direct and tuple(image.size) == (w,h):
                return _pixels(image)
            if uv1 is None:
                uv1 = _image_grid((h,w))
            return _sample(image, uv1, texture[1])
        color = (layer(bases[0], textures[1]) if any(diffuse[:3]) or not eye
                 else np.zeros((h,w,4), dtype=np.float32)) if layered else first_layer(textures[0])
        emissive = (layer(bases[1], textures[3]) if any(emission[:3]) or not eye
                    else np.zeros((h,w,4), dtype=np.float32)) if layered else first_layer(textures[2])
        color[...,:3] = (color[...,:3]*diffuse[:3] + emissive[...,:3]*emission[:3])*final[:3]
        if eye:
            color[...,3] = 1.0
        elif textures[0][0] is None:
            color[...,3] = emissive[...,3]
        node = _publish(material, color)
        _cache[pointer] = {'key': key, 'geometry': geometry_key, 'uv': (uv,second) if layered else None,
                           'base_key': base_key if layered else None, 'bases': bases}
    if not eye:
        # A tinted copy still uses the original map1 coordinates, including
        # negative/tiled islands. Clamping the preview stretches its edge over
        # mirrored boots and other meshes that deliberately leave the 0-1 tile.
        wrapping = textures[0 if textures[0][0] is not None else 2][1]
        modes = wrapping if isinstance(wrapping, tuple) else (wrapping, wrapping)
        extension = ('REPEAT' if all(m in {'Repeat', 'REPEAT'} for m in modes)
                     else 'MIRROR' if all(m in {'MirroredRepeat', 'MIRROR'} for m in modes)
                     else 'EXTEND')
        if node.extension != extension:
            node.extension = extension
    return _activate(material, node, meshes)


def _activate(material, node, meshes):
    nodes = material.node_tree.nodes
    if PREVIOUS not in material:
        material[PREVIOUS] = nodes.active.name if nodes.active else ''
    if nodes.active != node:
        node.select = True
        nodes.active = node
    for obj in meshes:
        mesh = obj.data
        base = mesh.uv_layers.get('map1')
        if base is not None and mesh.uv_layers.active != base:
            if PREVIOUS_UV not in mesh:
                mesh[PREVIOUS_UV] = mesh.uv_layers.active.name if mesh.uv_layers.active else ''
            mesh.uv_layers.active = base
        # Replace legacy eye warps: only the second layer is transformed in the image.
        mod = obj.modifiers.get('SUB_EyeSolidWarp')
        if mod is not None and mod.show_viewport:
            mod.show_viewport = False
    return True


def update_eye(obj, arma):
    if not obj.visible_get():
        return True
    material = obj.material_slots[0].material if obj.material_slots else None
    return bool(material and update_material(material, [obj], arma))


def restore(scene):
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        if PREVIOUS_UV in mesh:
            previous = mesh.uv_layers.get(mesh[PREVIOUS_UV])
            if previous:
                mesh.uv_layers.active = previous
            del mesh[PREVIOUS_UV]
        for slot in obj.material_slots:
            mat = slot.material
            if mat and PREVIOUS in mat:
                if mat.node_tree:
                    mat.node_tree.nodes.active = mat.node_tree.nodes.get(mat[PREVIOUS])
                del mat[PREVIOUS]



def _entry(material, meshes):
    nodes = material.node_tree.nodes
    prefixes = tuple(node.path_from_id() + '.outputs['
                     for name in ('CustomVector3','CustomVector6','CustomVector8','CustomVector13','CustomVector31')
                     for axis in 'XYZW' if (node := nodes.get(name + '_' + axis)))
    tree = material.node_tree
    readers = [(material, None), (tree, None)]
    live = False
    animation = tree.animation_data
    for curve in animation.drivers if animation else ():
        if not curve.data_path.startswith(prefixes):
            continue
        driver = curve.driver
        if not driver.variables or 'frame' in driver.expression:
            live = True
        for variable in driver.variables:
            if variable.type != 'SINGLE_PROP':
                live = True
            for target in variable.targets:
                if target.id is not None:
                    readers.append((target.id, target.data_path if variable.type == 'SINGLE_PROP' else None))
    arma = next((mod.object for obj in meshes for mod in obj.modifiers
                 if mod.type == 'ARMATURE' and mod.object), None)
    eye = material.sub_matl_data.vectors.get('CustomVector31') is not None and any(
        _texture(material, name)[0] is not None for name in ('Texture1','Texture14'))
    if eye and arma:
        from ...extras import eye_rig
        indices = eye_rig._cv31_indices_for_mat(arma, material)
        if indices is not None:
            track, prop = indices
            base = f'sub_anim_properties.mat_tracks[{track}].properties[{prop}].custom_vector'
            readers.extend((arma.data, base + '[' + str(axis) + ']') for axis in range(4))
    return {'material': material, 'meshes': meshes, 'arma': arma, 'eye': eye,
            'readers': readers, 'live': live, 'dynamic': False}


def _animation_key(entries, scene):
    ids = {data.as_pointer(): data for entry in entries.values() for data, _ in entry['readers']}
    ids.update((entry['arma'].data.as_pointer(), entry['arma'].data)
               for entry in entries.values() if entry['eye'] and entry['arma'])
    key = []
    for token, data in ids.items():
        animation = getattr(data, 'animation_data', None)
        action = animation.action if animation else None
        slot = getattr(animation, 'action_slot', None)
        key.append((token, action.as_pointer() if action else 0, getattr(slot, 'handle', 0),
                    len(animation.nla_tracks) if animation else 0,
                    len(animation.drivers) if animation else 0))
    from ...extras import eye_rig
    key.append(bool(getattr(getattr(scene, 'sub_scene_properties', None), 'eye_look_live_preview', False)))
    key.extend((entry['arma'].as_pointer(), eye_rig.EYE_CTRL_BONE in entry['arma'].pose.bones,
                eye_rig._cv31_indices_for_mat(entry['arma'], entry['material']))
               for entry in entries.values() if entry['eye'] and entry['arma'])
    return tuple(key)


def _classify(entries, scene):
    from ...extras import eye_rig
    from ...anim.fcurve_compat import get_fcurves_for_assigned_slot
    paths = {}
    def animated(data, path):
        animation = getattr(data, 'animation_data', None)
        if animation is None:
            return False
        if animation.use_nla and any(not track.mute for track in animation.nla_tracks):
            return True
        if path is None:
            return animation.action is not None
        token = data.as_pointer()
        if token not in paths:
            paths[token] = {value for fc in get_fcurves_for_assigned_slot(data) if not fc.mute
                            for value in (fc.data_path, fc.data_path + '[' + str(fc.array_index) + ']')}
        return path in paths[token] or bool(animation.drivers)
    live = bool(getattr(getattr(scene, 'sub_scene_properties', None), 'eye_look_live_preview', False))
    for entry in entries.values():
        arma = entry['arma']
        entry['poll'] = entry['live'] or bool(entry['eye'] and live and arma
                                               and eye_rig.EYE_CTRL_BONE in arma.pose.bones)
        entry['dynamic'] = entry['poll'] or any(animated(data, path) for data, path in entry['readers'])


def _visible_entries(scene):
    global _index, _structure_dirty
    view = bpy.context.view_layer if bpy.context.scene == scene else scene.view_layers[0]
    key = (scene.as_pointer(), view.as_pointer(), len(scene.objects))
    if _structure_dirty or _index is None or _index['key'] != key:
        _index = {'key': key, 'objects': [obj for obj in scene.objects if obj.type == 'MESH'],
                  'visible': None, 'entries': {}, 'animation': None}
        _structure_dirty = False
    objects = [obj for obj in _index['objects'] if obj.mode != 'EDIT' and obj.visible_get(view_layer=view)]
    visible = tuple(obj.as_pointer() for obj in objects)
    if visible != _index['visible']:
        groups = {}
        for obj in objects:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat.use_nodes and mat.node_tree and mat.sub_matl_data.shader_label:
                    group = groups.setdefault(mat, [])
                    if obj not in group:
                        group.append(obj)
        _index['entries'] = {mat.as_pointer(): _entry(mat, meshes) for mat, meshes in groups.items()}
        _index['visible'] = visible
        _index['animation'] = None
        _dirty.update(_index['entries'])
    return _index['entries']


def sync(scene, *, frame_changed=False):
    global _busy, _engaged, _needs_restore
    if _busy or bpy.app.is_job_running('RENDER'):
        return
    from ...extras import eye_rig
    if not eye_rig._solid_texture_viewport_open():
        if _engaged or _needs_restore:
            restore(scene)
            _engaged = _needs_restore = False
        return
    _busy = True
    try:
        entries = _visible_entries(scene)
        if not _engaged:
            _dirty.update(entries)
        changed = _dirty.intersection(entries)
        _dirty.difference_update(changed)
        for token in changed:
            previous = entries[token]
            entries[token] = _entry(previous['material'], previous['meshes'])
        animation = _animation_key(entries, scene)
        animation_changed = animation != _index['animation']
        if changed or animation_changed:
            if animation_changed:
                # New SAP tracks or control bones can introduce inputs that did
                # not exist when this material was first indexed.
                for token, entry in list(entries.items()):
                    entries[token] = _entry(entry['material'], entry['meshes'])
                animation = _animation_key(entries, scene)
            _classify(entries, scene)
            _index['animation'] = animation
            # New action bindings can replace previously animated channels.
            if animation_changed:
                changed.update(entries)
        pending = changed | {token for token, entry in entries.items()
                             if entry['dynamic'] and (frame_changed or entry['poll'])}
        for token in pending:
            entry = entries[token]
            update_material(entry['material'], entry['meshes'], entry['arma'], scene, check_uv=False)
        _engaged = True
    finally:
        _busy = False


@persistent
def _frame(scene, _depsgraph=None):
    sync(scene, frame_changed=True)


@persistent
def _load(_dummy):
    global _index, _structure_dirty, _engaged, _needs_restore
    _cache.clear()
    _revisions.clear()
    _mesh_revisions.clear()
    _uv_signatures.clear()
    _dirty.clear()
    _index = None
    _structure_dirty = True
    _engaged = False
    _needs_restore = True
    _subscribe_edits()


@persistent
def _changed(_scene, depsgraph):
    global _structure_dirty
    if _busy:
        return
    entries = _index['entries'] if _index else {}
    trees = {entry['material'].node_tree.as_pointer(): token for token, entry in entries.items()}
    for update in depsgraph.updates:
        data = update.id.original
        token = data.as_pointer()
        if isinstance(data, bpy.types.Image) and not data.name.startswith(('SUB_SolidPreview::', 'SUB_EyeSolid::')):
            _revisions[token] = _revisions.get(token, 0) + 1
            _dirty.update(entries)
        elif isinstance(data, bpy.types.Material):
            _dirty.add(token)
        elif isinstance(data, bpy.types.NodeTree) and token in trees:
            _dirty.add(trees[token])
        elif isinstance(data, bpy.types.Mesh):
            _structure_dirty = True
            _mesh_revisions[token] = _mesh_revisions.get(token, 0) + 1
            _dirty.update(key for key, entry in entries.items() if any(obj.data == data for obj in entry['meshes']))
        elif isinstance(data, bpy.types.Object) and update.is_updated_shading:
            _structure_dirty = True
        elif isinstance(data, bpy.types.Action) and _index:
            _index['animation'] = None


def _edited():
    # RNA notifications cover user edits, not animation evaluation. They are
    # coalesced until the next timer tick rather than rescanning on every frame.
    if _index:
        _dirty.update(_index['entries'])


def _subscribe_edits():
    from . import sub_matl_data
    bpy.msgbus.clear_by_owner(_message_owner)
    for cls, prop in ((sub_matl_data.SUB_PG_matl_vector, 'value'),
                      (sub_matl_data.SUB_PG_matl_texture, 'image'),
                      (sub_matl_data.SUB_PG_matl_sampler, 'wrap_s'),
                      (sub_matl_data.SUB_PG_matl_sampler, 'wrap_t')):
        bpy.msgbus.subscribe_rna(key=(cls, prop), owner=_message_owner, args=(), notify=_edited,
                                options={'PERSISTENT'})


def _timer():
    scene = getattr(bpy.context, 'scene', None)
    if scene:
        try:
            sync(scene)
        except (ReferenceError, RuntimeError):
            _load(None)
            _log.exception('Solid material preview update failed')
    return .1


def register():
    if _frame not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_frame)
    if _changed not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_changed)
    if _load not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_load)
    if _load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load)
    _subscribe_edits()
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=.2, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    bpy.msgbus.clear_by_owner(_message_owner)
    for handlers, handler in ((bpy.app.handlers.frame_change_post, _frame),
                              (bpy.app.handlers.load_post, _load),
                              (bpy.app.handlers.undo_post, _load),
                              (bpy.app.handlers.depsgraph_update_post, _changed)):
        if handler in handlers:
            handlers.remove(handler)
    for scene in bpy.data.scenes:
        restore(scene)
    _cache.clear()
    _revisions.clear()
    _mesh_revisions.clear()
    _uv_signatures.clear()
