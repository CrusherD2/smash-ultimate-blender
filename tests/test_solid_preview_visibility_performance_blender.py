from pathlib import Path
from time import perf_counter
from unittest.mock import patch

fixture = Path(__file__).with_name('test_solid_material_preview_blender.py')
exec(compile(fixture.read_text().split('links = [')[0], str(fixture), 'exec'))
scene = bpy.context.scene
other = obj.copy()
other.data = mesh.copy()
other.name = 'Alternate expression'
scene.collection.objects.link(other)
alternate = mat.copy()
alternate.name = 'Alternate expression material'
other.data.materials[0] = alternate
body = obj.copy()
body.data = mesh.copy()
body.name = 'Unrelated body'
scene.collection.objects.link(body)
body_material = mat.copy()
body_material.name = 'Unrelated body material'
body.data.materials[0] = body_material

with patch.object(eye, '_solid_texture_viewport_open', return_value=True):
    preview._load(None)
    for _ in range(4):
        bpy.context.view_layer.update()
        preview.sync(scene)
    other.hide_set(True)
    preview.sync(scene)
    with patch.object(preview, '_entry', wraps=preview._entry) as indexed, \
         patch.object(preview, '_classify', wraps=preview._classify) as classified, \
         patch.object(preview, '_publish', wraps=preview._publish) as published, \
         patch.object(preview, 'update_material', wraps=preview.update_material) as updated:
        started = perf_counter()
        for frame in range(20):
            obj.hide_set(frame % 2 == 0)
            other.hide_set(frame % 2 != 0)
            bpy.context.view_layer.update()
            preview.sync(scene, frame_changed=True)
        elapsed = perf_counter() - started
        assert indexed.call_count == 0, indexed.call_count
        assert classified.call_count == 0, classified.call_count
        assert published.call_count == 0, published.call_count
        assert all(call.args[0] != body_material for call in updated.call_args_list)
        assert updated.call_count == 20, updated.call_count
        print(f'VISIBILITY PERFORMANCE: 20 switches, {elapsed:.4f}s; '
              '0 material reindexes, 0 classifications, 0 texture uploads, 0 unrelated updates')
    # A shared material must still refresh when its visible mesh membership changes.
    other.data.materials[0] = mat
    other.data.update()
    obj.hide_set(False)
    other.hide_set(False)
    bpy.context.view_layer.update()
    preview.sync(scene)
    assert len(preview._index['visible_meshes'][mat.as_pointer()]) == 2
    other.hide_set(True)
    preview.sync(scene)
    assert preview._index['visible_meshes'][mat.as_pointer()] == [obj]
    # Shared materials must read the rig of the visible mesh, not a hidden rig.
    for target in (obj, other):
        data = bpy.data.armatures.new(target.name + ' rig')
        rig = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(rig)
        target.modifiers.new('Source rig', 'ARMATURE').object = rig
    bpy.context.view_layer.update()
    preview.sync(scene)
    assert preview._index['entries'][mat.as_pointer()]['arma'] == obj.modifiers['Source rig'].object
    obj.hide_set(True)
    other.hide_set(False)
    preview.sync(scene)
    assert preview._index['entries'][mat.as_pointer()]['arma'] == other.modifiers['Source rig'].object
    # Loading/undo invalidation must discard the persistent index.
    preview._load(None)
    preview.sync(scene)
    assert mat.as_pointer() in preview._index['entries']
    print('SOLID_VISIBILITY_PERFORMANCE_OK')
