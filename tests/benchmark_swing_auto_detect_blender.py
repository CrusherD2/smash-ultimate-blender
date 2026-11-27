"""Time swing chain auto-detect on a synthetic rig and fingerprint its result.

python tests/run_blender_test.py --blender <blender> tests/benchmark_swing_auto_detect_blender.py
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

# Work on a copy of the full-size bundled labels so the real file is never written.
labels_copy = Path(profile.name) / 'ParamLabels.csv'
shutil.copyfile(labels.bundled_labels_path(), labels_copy)
labels.labels_path = lambda: labels_copy
labels.ensure_param_labels = lambda: labels_copy

CHAINS, BONES = 24, 6
arma = bpy.data.armatures.new('Bench')
obj = bpy.data.objects.new('Bench', arma)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
root = arma.edit_bones.new('J_Head')
root.head, root.tail = (0, 0, 0), (0, 0, 1)
for c in range(CHAINS):
    parent = root
    for b in range(BONES + 1):
        name = f'S_Hair{c}_{b}' if b < BONES else f'S_Hair{c}_{b}_null'
        bone = arma.edit_bones.new(name)
        bone.head = (c * .3, b * .2, 1)
        bone.tail = (c * .3, b * .2 + .2, 1)
        bone.parent = parent
        parent = bone
# A branching chain and a lone bone must stay undetected.
fork = arma.edit_bones.new('S_Fork')
fork.head, fork.tail = (9, 0, 0), (9, 0, 1)
for i in range(2):
    child = arma.edit_bones.new(f'S_Fork_{i}')
    child.head, child.tail = (9, i, 1), (9, i, 2)
    child.parent = fork
bpy.ops.object.mode_set(mode='OBJECT')

profiler = cProfile.Profile() if os.environ.get('SUB_PROFILE') else None
start = time.perf_counter()
with bpy.context.temp_override(object=obj, active_object=obj):
    if profiler:
        profiler.enable()
    result = bpy.ops.sub.swing_bone_chain_auto_detect()
    if profiler:
        profiler.disable()
elapsed = time.perf_counter() - start
assert result == {'FINISHED'}, result

ssd = arma.sub_swing_data
fingerprint = {
    'chains': [(ch.name, ch.start_bone_name, ch.end_bone_name, [b.name for b in ch.swing_bones]) for ch in ssd.swing_bone_chains],
    'bone_links': sorted((b.name, b.sub_swing_blender_bone_data.swing_bone_chain_index,
                          b.sub_swing_blender_bone_data.swing_bone_index) for b in arma.bones),
    'meshes': sorted((b.blender_object.name, len(b.blender_object.data.vertices),
                      round(sum(v.co.length for v in b.blender_object.data.vertices), 4),
                      b.blender_object.parent.name, [m.type for m in b.blender_object.modifiers])
                     for ch in ssd.swing_bone_chains for b in ch.swing_bones),
    'collections': sorted(c.name for c in bpy.data.collections),
    'labels': labels_copy.read_text(encoding='utf-8').splitlines()[-5:],
    'label_rows': len(labels_copy.read_text(encoding='utf-8').splitlines()),
}
assert len(fingerprint['chains']) == CHAINS, fingerprint['chains']
print(f'AUTO_DETECT_SECONDS {elapsed:.3f}')
print('AUTO_DETECT_FINGERPRINT ' + json.dumps(fingerprint, sort_keys=True))
if profiler:
    pstats.Stats(profiler).sort_stats('cumulative').print_stats(18)
