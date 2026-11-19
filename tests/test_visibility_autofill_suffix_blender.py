from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
groups = importlib.import_module(MODULE + '.source.model.vis_shape_groups')
arm = bpy.data.objects.new('VisibilityAutofill', bpy.data.armatures.new('VisibilityAutofill'))
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
for name in ('BodyShape', 'Hair', 'Invalid_VIS_O_OBJShape_extra', 'Wrong_VIS_0_OBJShape',
             'Face_VIS_O_OBJShape', 'Face_VIS_O_OBJShape.001', 'face_vis_o_objshape.002',
             'Hat_VIS_O_OBJShape', 'New_VIS_O_OBJShape'):
    mesh = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    bpy.context.scene.collection.objects.link(mesh)
    mesh.parent = arm
    if name.startswith('New_'):
        group = bpy.data.objects.new('New', None)
        bpy.context.scene.collection.objects.link(group)
        group.parent = arm
        group[groups.VIS_GROUP_ID] = True
        mesh.parent = group
other = bpy.data.objects.new('Unrelated_VIS_O_OBJShape', bpy.data.meshes.new('Unrelated'))
bpy.context.scene.collection.objects.link(other)
sap = arm.data.sub_anim_properties
existing = sap.vis_track_entries.add()
existing.name, existing.value = 'hat', False
legacy = sap.vis_track_entries.add()
legacy.name, legacy.value = 'ExistingManualTrack', False
for _ in range(2):
    assert bpy.ops.sub.auto_fill_vis_entries() == {'FINISHED'}
    names = [entry.name for entry in sap.vis_track_entries]
    assert names == ['hat', 'ExistingManualTrack', 'Face', 'New'], names
    assert not sap.vis_track_entries[0].value
    assert not sap.vis_track_entries[1].value
print('VIS AUTOFILL FILTERS SUFFIX, DEDUPLICATES, FINDS GROUPED MESHES AND PRESERVES EXISTING TRACKS PASSED')
