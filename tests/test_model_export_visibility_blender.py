from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
export = importlib.import_module(MODULE + '.source.model.export_model')
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')
scene = bpy.context.scene
arm = bpy.data.objects.new('ExportRig', bpy.data.armatures.new('ExportRig'))
scene.collection.objects.link(arm)
scene.sub_scene_properties.model_export_arma = arm
meshes = []
for index, hidden in enumerate(((False, False), (True, True), (True, False))):
    obj = bpy.data.objects.new(f'Face{index}', bpy.data.meshes.new(f'Face{index}'))
    scene.collection.objects.link(obj)
    obj.parent = arm
    obj.hide_viewport, obj.hide_render = hidden
    meshes.append(obj)
bpy.context.view_layer.update()
initial = [(obj.hide_viewport, obj.hide_render) for obj in meshes]
visible = [viewport._object_visible(obj) for obj in meshes]

for fail in (False, True):
    for pose in ('POSE', 'REST'):
        arm.data.pose_position = pose
        observed = []

        def progress(value):
            if value == 5:
                observed.append(True)
                assert all(not obj.hide_viewport and not obj.hide_render for obj in meshes)
                if fail:
                    raise RuntimeError('Export interrupted')

        context = SimpleNamespace(
            scene=scene, view_layer=bpy.context.view_layer,
            selected_objects=bpy.context.selected_objects,
            window_manager=SimpleNamespace(progress_update=progress),
        )
        try:
            # No file types selected: exercise scene preparation without writing files.
            export.export_model(
                SimpleNamespace(), context, '', False, False, False, False,
                False, False, False, 'NO_LINK', 'DISABLED',
                'REST' if pose == 'POSE' else 'POSE', 'NONE', 'NONE', 'NONE',
            )
        except RuntimeError as exc:
            assert fail and str(exc) == 'Export interrupted'
        else:
            assert not fail
        assert observed == [True]
        assert arm.data.pose_position == pose
        assert [(obj.hide_viewport, obj.hide_render) for obj in meshes] == initial
        bpy.context.view_layer.update()
        assert [viewport._object_visible(obj) for obj in meshes] == visible
print('MODEL_EXPORT_VISIBILITY_RESTORATION_OK')
