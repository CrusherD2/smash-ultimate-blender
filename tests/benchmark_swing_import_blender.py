"""Time swing.prc import on a synthetic rig and fingerprint its result.

python tests/run_blender_test.py --blender <blender> tests/benchmark_swing_import_blender.py
Set SUB_PROFILE=1 for a cProfile breakdown.
"""
import cProfile
import json
import os
import pstats
import shutil
import time
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
labels = importlib.import_module(MODULE + '.source.param_labels')
operators = importlib.import_module(MODULE + '.source.swing.operators')

labels_copy = Path(profile.name) / 'ParamLabels.csv'
shutil.copyfile(labels.bundled_labels_path(), labels_copy)
labels.labels_path = lambda: labels_copy
labels.ensure_param_labels = lambda: labels_copy

CHAINS, BONES, SHAPES = 24, 6, 8
arma = bpy.data.armatures.new('Bench')
obj = bpy.data.objects.new('Bench', arma)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
body = []
for i in range(SHAPES + 1):
    bone = arma.edit_bones.new(f'J_Body{i}')
    bone.head, bone.tail = (0, 0, i), (0, 0, i + 1)
    bone.parent = body[-1] if body else None
    body.append(bone)
for c in range(CHAINS):
    parent = body[0]
    for b in range(BONES + 1):
        bone = arma.edit_bones.new(f'S_Hair{c}_{b}' if b < BONES else f'S_Hair{c}_{b}_null')
        bone.head, bone.tail = (c * .3, b * .2, 1), (c * .3, b * .2 + .2, 1)
        bone.parent = parent
        parent = bone
bpy.ops.object.mode_set(mode='OBJECT')

ssd = arma.sub_swing_data
with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_bone_chain_auto_detect() == {'FINISHED'}
    for i in range(SHAPES):
        bpy.ops.sub.swing_data_sphere_add('EXEC_DEFAULT', sphere_name=f'ball{i}', bone_name=f'J_Body{i}', radius=1 + i)
        bpy.ops.sub.swing_data_capsule_add('EXEC_DEFAULT', capsule_name=f'tube{i}', start_bone_name=f'J_Body{i}',
                                           end_bone_name=f'J_Body{i + 1}', start_radius=1, end_radius=2)
        bpy.ops.sub.swing_data_oval_add('EXEC_DEFAULT', oval_name=f'egg{i}', start_bone_name=f'J_Body{i}',
                                        end_bone_name=f'J_Body{i + 1}', radius=.5)
        bpy.ops.sub.swing_data_plane_add('EXEC_DEFAULT', plane_name=f'wall{i}', bone_name=f'J_Body{i}', distance=i)
        bpy.ops.sub.swing_data_ellipsoid_add('EXEC_DEFAULT', ellipsoid_name=f'blob{i}', bone_name=f'J_Body{i}')
for c, chain in enumerate(ssd.swing_bone_chains):
    for b, bone in enumerate(chain.swing_bones):
        operators.add_collision_to_bones([bone], ('SPHERE', 'CAPSULE', 'OVAL', 'PLANE')[(c + b) % 4], (c + b) % SHAPES)
prc = Path(profile.name) / 'swing.prc'
with bpy.context.temp_override(object=obj, active_object=obj):
    operators.swing_prc_export(type('Op', (), {'report': lambda *_a: None})(), bpy.context, str(prc))
assert prc.is_file()


class Importer:
    filepath = str(prc)
    reports = []

    def report(self, kind, message):
        self.reports.append((sorted(kind), message))


profiler = cProfile.Profile() if os.environ.get('SUB_PROFILE') else None
importer = Importer()
start = time.perf_counter()
with bpy.context.temp_override(object=obj, active_object=obj):
    if profiler:
        profiler.enable()
    operators.SUB_OP_swing_import.execute(importer, bpy.context)
    if profiler:
        profiler.disable()
elapsed = time.perf_counter() - start


def shape_rows(collection, fields):
    return [[item.name] + [repr(tuple(getattr(item, f))) if hasattr(getattr(item, f), '__len__') and not isinstance(getattr(item, f), str)
                           else repr(getattr(item, f)) for f in fields] for item in collection]


fingerprint = {
    'chains': [(ch.name, ch.start_bone_name, ch.end_bone_name, [b.name for b in ch.swing_bones],
                [[(c.collision_type, c.collision_index) for c in b.collisions] for b in ch.swing_bones]) for ch in ssd.swing_bone_chains],
    'spheres': shape_rows(ssd.spheres, ('bone', 'offset', 'radius')),
    'capsules': shape_rows(ssd.capsules, ('start_bone_name', 'end_bone_name', 'start_radius', 'end_radius')),
    'ovals': shape_rows(ssd.ovals, ('start_bone_name', 'end_bone_name', 'radius')),
    'planes': shape_rows(ssd.planes, ('bone_name', 'nx', 'ny', 'nz', 'distance')),
    'ellipsoids': shape_rows(ssd.ellipsoids, ('bone_name', 'offset', 'scale')),
    'objects': sorted((o.name, len(o.data.vertices), round(sum(v.co.length for v in o.data.vertices), 3),
                       o.parent.name if o.parent else None) for o in bpy.data.objects if o.type == 'MESH'),
    'collections': sorted(c.name for c in bpy.data.collections),
    'bone_links': sorted((b.name, b.sub_swing_blender_bone_data.swing_bone_chain_index,
                          b.sub_swing_blender_bone_data.swing_bone_index) for b in arma.bones),
    'label_rows': sorted(labels_copy.read_text(encoding='utf-8').splitlines()),
    'reports': importer.reports,
}
assert len(fingerprint['chains']) == CHAINS and len(fingerprint['spheres']) == SHAPES, fingerprint['chains'][:2]
print(f'IMPORT_SECONDS {elapsed:.3f}')
print('IMPORT_FINGERPRINT ' + json.dumps(fingerprint, sort_keys=True))
if profiler:
    pstats.Stats(profiler).sort_stats('cumulative').print_stats(16)
