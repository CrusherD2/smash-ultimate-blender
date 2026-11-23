from pathlib import Path
from math import pi

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
from mathutils import Matrix, Vector

ops = importlib.import_module(MODULE + '.expy_kit.operators')
retarget_presets.get_retarget_dir = lambda: str(ROOT / 'expy_kit/rig_mapping/presets')
source_data = bpy.data.armatures.new('Offset Source')
source = bpy.data.objects.new('Offset Source', source_data)
bpy.context.collection.objects.link(source)
bpy.context.view_layer.objects.active = source
source.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone = source_data.edit_bones.new('root')
bone.head, bone.tail = (0, 1, 0), (0, 2, 0)
bpy.ops.object.mode_set(mode='OBJECT')
source.pose.bones['root'].location = (1, 0, 0)
source.pose.bones['root'].keyframe_insert('location', frame=1)
source.pose.bones['root'].location = (2, 0, 0)
source.pose.bones['root'].keyframe_insert('location', frame=3)
action = source.animation_data.action
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat').get_fcurves
keys = [[tuple(key.co) for key in fc.keyframe_points] for fc in curves(action)]
rest = source_data.bones['root'].matrix_local.copy()
mesh = bpy.data.objects.new('Offset Mesh', bpy.data.meshes.new('Offset Mesh'))
bpy.context.collection.objects.link(mesh)
mesh.modifiers.new('Armature', 'ARMATURE').object = source
assert bpy.ops.object.expykit_create_offset() == {'FINISHED'}
settings = bpy.context.scene.expykit_offset
class OffsetLayout:
    def __init__(self):
        self.buttons = []
        self.fields = []

    def column(self):
        return self

    def box(self):
        return self

    def label(self, **kwargs):
        pass

    def prop(self, data, name, **kwargs):
        self.fields.append(name)

    def operator(self, name, **kwargs):
        self.buttons.append((name, kwargs.get('text')))


from types import SimpleNamespace
retargeting = importlib.import_module(MODULE + '.source.retargeting')
for kind, field in (('SCALE', 'scale'), ('ROTATION', 'rotation')):
    settings.kind = kind
    layout = OffsetLayout()
    retargeting.ULTIMATE_PT_ActionsConversion.draw(SimpleNamespace(layout=layout), bpy.context)
    assert ('object.expykit_create_rotation_offset', None) in layout.buttons
    assert ('object.expykit_apply_offset', 'Apply') in layout.buttons
    assert field in layout.fields
assert not hasattr(bpy.types, 'VIEW3D_PT_expy_offset')
settings.kind = 'SCALE'
settings.scale = 5
assert mesh.parent == source.parent == settings.container
assert bpy.ops.object.expykit_apply_offset() == {'FINISHED'}
assert bpy.ops.object.expykit_create_rotation_offset() == {'FINISHED'}
settings.rotation = (pi / 2, 0, 0)
assert bpy.ops.object.expykit_apply_offset() == {'FINISHED'}
bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
assert (source.matrix_world @ Vector((0, 1, 0)) - Vector((0, 0, 5))).length < 1e-5
assert (mesh.matrix_world @ Vector((0, 1, 0)) - Vector((0, 0, 5))).length < 1e-5
assert source_data.bones['root'].matrix_local == rest
assert [[tuple(key.co) for key in fc.keyframe_points] for fc in curves(action)] == keys
# Bind through Expy itself, with the aligned source driving the unchanged target.
target_data = source_data.copy()
target = bpy.data.objects.new('Offset Target', target_data)
bpy.context.collection.objects.link(target)
for obj in bpy.context.selected_objects:
    obj.select_set(False)
source.select_set(True)
target.select_set(True)
bpy.context.view_layer.objects.active = source
for obj in (source, target):
    obj.data.expykit_retarget.spine.hips = 'root'
bpy.ops.object.mode_set(mode='POSE')
assert bpy.ops.armature.expykit_constrain_to_armature(
    src_preset='--Current--', trg_preset='--Current--', constrain_root='None',
    match_transform='None', match_object_transform=True, fit_target_scale='--',
    loc_constraints=True, rot_constraints=True, scale_constraints=True,
) == {'FINISHED'}
assert target.pose.bones['root'].constraints
helper_head = source.matrix_world @ source.data.bones['root_RET'].head_local
assert (helper_head - target.matrix_world @ target_data.bones['root'].head_local).length < 1e-5
bpy.context.view_layer.objects.active = target
bpy.context.view_layer.update()
assert max(abs(v - 1) for v in target.pose.bones['root'].matrix.to_scale()) < 1e-5
expected = {}
for frame in range(1, 4):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    expected[frame] = target.pose.bones['root'].matrix.copy()
    assert max(abs(v - 1) for v in expected[frame].to_scale()) < 1e-5
assert bpy.ops.nla.bake(frame_start=1, frame_end=3, only_selected=False,
                       visual_keying=True, clear_constraints=False,
                       use_current_action=False, bake_types={'POSE'}) == {'FINISHED'}
for constraint in list(target.pose.bones['root'].constraints):
    target.pose.bones['root'].constraints.remove(constraint)
for frame in range(1, 4):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert max(abs(a-b) for row,want in zip(target.pose.bones['root'].matrix, expected[frame]) for a,b in zip(row,want)) < 1e-5
assert target.scale == Vector((1, 1, 1))
assert (expected[3].translation - expected[1].translation).length > 1
assert [[tuple(key.co) for key in fc.keyframe_points] for fc in curves(action)] == keys
assert source_data.bones['root'].matrix_local == rest
print('EXPY OFFSETS PASSED')
