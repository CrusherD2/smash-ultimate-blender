from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import bmesh
import numpy as np
from mathutils import Matrix

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
vp = importlib.import_module(MODULE + '.source.extras.smash_viewport')
extra = importlib.import_module(MODULE + '.source.extras.smash_vp_extra')
for old in list(bpy.data.objects):
    bpy.data.objects.remove(old, do_unlink=True)
scene = bpy.context.scene
arm = bpy.data.objects.new('Edit rig', bpy.data.armatures.new('Edit rig'))
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone = arm.data.edit_bones.new('Hip')
bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
bpy.ops.object.mode_set(mode='OBJECT')
data = bpy.data.meshes.new('Body')
data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
uv = data.uv_layers.new(name='map1')
for index, loop in enumerate(uv.data):
    loop.uv = ((0, 0), (1, 0), (0, 1))[index]
obj = bpy.data.objects.new('Body', data)
scene.collection.objects.link(obj)
obj.parent = arm
obj['numshb order'] = 0
mod = obj.modifiers.new('Deform', 'ARMATURE')
mod.object = arm
obj.vertex_groups.new(name='Hip').add([0, 1, 2], 1.0, 'REPLACE')
arm.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.context.view_layer.update()
assert not vp._mesh_live_preview(obj, arm)

def update_mesh():
    update = SimpleNamespace(id=data, is_updated_geometry=True)
    graph = SimpleNamespace(updates=[update])
    with patch.object(vp, '_viewport_enabled', return_value=True), patch.object(vp, '_in_mod_sync', False):
        vp._on_scene_redraw(scene, graph)

def native_visibility():
    with patch.object(vp, '_iter_folder_smash_armatures', return_value=[arm]), patch.object(vp, '_smash_mesh_keys', return_value=[('Body', 0)]), patch.object(vp, '_loaded_folder', ''):
        return vp._collect_mesh_visibility_now(bpy.context)

def extra_fingerprint():
    with patch.object(extra, 'iter_extra_armatures', return_value=[arm]), patch.object(vp, '_smash_folder_extra', return_value=True), patch.object(vp, '_folder_from_armature', return_value='C:/model'):
        return vp._extra_fingerprint(scene)

bpy.ops.object.mode_set(mode='EDIT')
editing_extra = extra_fingerprint()
assert not vp._gpu_model_visible(scene, arm, bpy.context.view_layer, None)
assert vp._gpu_model_visible(scene, arm, bpy.context.view_layer, None, include_edit=True)
bm = bmesh.from_edit_mesh(data)
bm.verts.ensure_lookup_table()
bm.verts[1].co.x = 2.0
bmesh.update_edit_mesh(data)
update_mesh()
assert 'sub_smash_live_edit_preview' not in data
assert vp._mesh_live_preview(obj, arm)
assert not vp._gpu_covers_mesh(obj, arm)
assert native_visibility() == (['Body'], [0], [0])
assert obj in list(vp._iter_blender_shade_meshes_now(bpy.context, True))
first = vp._shade_cache_entry(obj, bpy.context, None, False)
assert np.max(first[1][0][0][:, 0]) == 2.0
assert np.max(first[1][0][2][:, 0]) == 1.0
bm.verts[1].co.x = 3.0
bmesh.update_edit_mesh(data)
update_mesh()
second = vp._shade_cache_entry(obj, bpy.context, None, False)
assert second is not first
assert np.max(second[1][0][0][:, 0]) == 3.0
# Newly created topology and hidden faces use the live BMesh, not stale Mesh arrays.
first_vert, second_vert = bm.verts[0], bm.verts[1]
new_vert = bm.verts.new((4, 1, 0))
bm.faces.new((first_vert, second_vert, new_vert))
bmesh.update_edit_mesh(data, destructive=True)
update_mesh()
assert sum(len(part[0]) for part in vp._shade_extract_edit_parts(obj)) == 6
bm.faces.ensure_lookup_table()
bm.faces[-1].hide_set(True)
assert sum(len(part[0]) for part in vp._shade_extract_edit_parts(obj)) == 3
bpy.ops.object.mode_set(mode='OBJECT')
assert extra_fingerprint() == editing_extra
# Old blend files must not keep the entire character in simplified shading.
data['sub_smash_live_edit_preview'] = True
assert not vp._mesh_live_preview(obj, arm)
assert native_visibility() == (['Body'], [0], [1])
assert obj not in list(vp._iter_blender_shade_meshes_now(bpy.context, True))
assert len(data.vertices) == 4 and max(vertex.co.x for vertex in data.vertices) == 4.0
# A second copy sharing GPU mesh ids stays native while the edited character is hidden.
other_arm = bpy.data.objects.new('Other rig', arm.data.copy())
scene.collection.objects.link(other_arm)
other = obj.copy()
other.data = data.copy()
other.parent = other_arm
scene.collection.objects.link(other)
bpy.context.view_layer.update()
vp._vis_cache.clear()
other.select_set(False)
other_arm.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
setter = Mock()
with patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_set_model_visible=setter)), patch.object(vp, '_preview', 1), patch.object(vp, '_loaded_folder', 'C:/model'), patch.object(vp, '_primary_smash_armature', return_value=arm), patch.object(vp, '_extra_gpu_order', [other_arm.as_pointer()]), patch.object(vp, '_schedule_mesh_draw_sync'):
    vp._sync_gpu_model_visibility(bpy.context, force=True)
    assert [call.args for call in setter.call_args_list] == [(1, 0, 0), (1, 1, 1)]
assert not vp._mesh_live_preview(other, other_arm)
bpy.ops.object.mode_set(mode='OBJECT')
assert not vp._mesh_live_preview(obj, arm)
assert data['sub_smash_live_edit_preview']
# Bone Edit Mode shows rest geometry, then returns to the native model on exit.
obj.select_set(False)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
arm.data.edit_bones['Hip'].head.x += 0.4
assert vp._mesh_live_preview(obj, arm)
assert native_visibility() == (['Body'], [0], [0])
assert obj in list(vp._iter_blender_shade_meshes_now(bpy.context, True))
bpy.ops.object.mode_set(mode='OBJECT')
assert not vp._mesh_live_preview(obj, arm)
assert native_visibility() == (['Body'], [0], [1])
# Shared GPU presentation must still draw the live edit layer at full resolution.
prepared = (1, 1920, 1080, False, None, None, False)
with patch.object(vp, '_viewport_enabled', return_value=True), patch.object(vp, '_prepare_preview', return_value=prepared), patch.object(vp, '_viewport_pixel_size', return_value=(1920, 1080)), patch.object(vp, '_fill_viewport_color'), patch.object(vp, '_gpu_covers_scene', return_value=True), patch.object(vp, '_has_live_edit_preview', return_value=True), patch.object(vp, 'gl_present_supported', return_value=True), patch.object(vp, '_gpu_failed', False), patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_present_gl=Mock(return_value=0))), patch.object(vp, '_draw_blender_meshes') as draw:
    vp._draw_smash_overlay_inner(bpy.context)
    draw.assert_called_once_with(bpy.context, None, skip_smash=True)
print('LIVE MESH EDITS, TOPOLOGY, UVS, BONE EDIT MODE AND FULL-RESOLUTION GPU COMPOSITING PASSED')
