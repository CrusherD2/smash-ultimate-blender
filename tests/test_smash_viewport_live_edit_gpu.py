from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import bmesh
import gpu
from mathutils import Matrix

fixture = Path(__file__).with_name('test_smash_viewport_live_edit_blender.py')
exec(compile(fixture.read_text(), str(fixture), 'exec'))
arm.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(data)
bm.verts.ensure_lookup_table()
for vertex, position in zip(list(bm.verts)[:3], ((-.75, -.75, 0), (.75, -.75, 0), (0, .75, 0))):
    vertex.co = position
bmesh.update_edit_mesh(data)
update_mesh()
rv3d = SimpleNamespace(view_matrix=Matrix.Identity(4), window_matrix=Matrix.Identity(4))
view = (None, SimpleNamespace(width=16, height=16), rv3d)
offscreen = gpu.types.GPUOffScreen(16, 16, format='RGBA32F')

def draw_center():
    framebuffer = gpu.state.active_framebuffer_get()
    framebuffer.clear(color=(0, 0, 0, 0), depth=1)
    with patch.object(vp, '_preview_view_from_context', return_value=view), patch.object(vp, '_iter_blender_shade_meshes', return_value=iter([obj])):
        vp._draw_blender_meshes(bpy.context, bpy.context.evaluated_depsgraph_get(), True)
    return np.array(framebuffer.read_color(8, 8, 1, 1, 4, 0, 'FLOAT').to_list()).reshape(4)

with offscreen.bind():
    first = draw_center()
    assert first[:3].min() > .05 and first[3] > .99, (gpu.platform.backend_type_get(), first)
    for vertex in bm.verts:
        vertex.co.x += 3
    bmesh.update_edit_mesh(data)
    update_mesh()
    second = draw_center()
    assert second.max() < .001, (gpu.platform.backend_type_get(), second)
vp._clear_shade_caches()
offscreen.free()
bpy.ops.object.mode_set(mode='OBJECT')
print('LIVE EDIT PIXELS UPDATE:', gpu.platform.backend_type_get())
bpy.context.preferences.view.use_save_prompt = False

def finish():
    bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(finish, first_interval=0.1)
