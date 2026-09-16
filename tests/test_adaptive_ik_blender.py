"""Blender integration coverage for adaptive chains, custom IK, and model folders."""
import importlib
import json
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
ik = importlib.import_module(ROOT.name + '.source.extras.ik_channels')
folders = importlib.import_module(ROOT.name + '.source.anim.import_anim')
custom_ik = importlib.import_module(ROOT.name + '.source.extras.custom_ik')


def rig(chains):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    data = bpy.data.armatures.new('AdaptiveTest')
    obj = bpy.data.objects.new('AdaptiveTest', data)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for chain_index, names in enumerate(chains):
        previous = None
        x = chain_index * 4.0
        for index, name in enumerate(names):
            bone = data.edit_bones.new(name)
            bone.head = (x, index, 0)
            bone.tail = (x, index + 1, 0)
            if previous:
                bone.parent = previous
                bone.use_connect = True
            previous = bone
    bpy.ops.object.mode_set(mode='POSE')
    return obj


# Standard left/right arms get distinct, keyframable pull channels.
obj = rig((('ShoulderL', 'ArmL', 'HandL'), ('ShoulderR', 'ArmR', 'HandR')))
assert ik.create_controls(bpy.context, obj, 'ARMS') == 2
poles = [obj.pose.bones[pole] for _, _, _, pole in ik.chains(obj, 'ARMS')]
assert len(poles) == 2
poles[0].bone.sub_ik_arm_pull = 0.25
poles[1].bone.sub_ik_arm_pull = 0.75
poles[0].bone.keyframe_insert('sub_ik_arm_pull', frame=1)
poles[1].bone.keyframe_insert('sub_ik_arm_pull', frame=1)
assert poles[0].bone.sub_ik_arm_pull != poles[1].bone.sub_ik_arm_pull
driver_paths = set()
for pole in poles:
    driver_paths.add(pole.bone.path_from_id() + '.sub_ik_arm_pull')
for _, names, _, _ in ik.chains(obj, 'ARMS'):
    for name in ik.limb_path(obj, names):
        assert ik.PULL_PREFIX + name in obj.pose.bones
        assert not obj.data.bones[name].use_connect
assert len(driver_paths) == 2
obj.data.sub_ik_stretch_arms = True
obj.data.sub_ik_stretch_chain_arms = True
for _kind, _names, target, _pole in ik.chains(obj, 'ARMS'):
    obj.pose.bones[target].location.y += 2.0
bpy.context.view_layer.update()
assert obj.animation_data is not None
pull_driver_paths = set()
for fcurve in obj.animation_data.drivers:
    if 'SUB IK Arm Pull' not in fcurve.data_path:
        continue
    assert fcurve.driver.is_valid, fcurve.data_path
    variable = next(variable for variable in fcurve.driver.variables if variable.name == 'pull')
    pull_driver_paths.add(variable.targets[0].data_path)
assert pull_driver_paths == driver_paths
for pole in poles:
    pole.bone.sub_ik_arm_pull = 0.0
bpy.context.view_layer.update()
evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
for _kind, names, target, _pole in ik.chains(obj, 'ARMS'):
    path = ik.limb_path(obj, names)
    offsets = []
    for name in path:
        offsets.append((evaluated.pose.bones[name].head
                        - evaluated.pose.bones[ik.PREFIX + name].head).length)
        assert (evaluated.pose.bones[name].matrix.to_scale()
                - evaluated.pose.bones[ik.PREFIX + name].matrix.to_scale()).length < 1e-4
    assert offsets[0] < 1e-4
    assert offsets[1] > offsets[0]
    assert offsets[-1] > offsets[0]

# A user-defined chain creates, participates in removal, and leaves no record.
custom_obj = rig((('A', 'B', 'C', 'D'),))
settings = bpy.context.scene.sub_custom_ik
settings.name = 'Tail'
settings.root, settings.middle, settings.end = 'A', 'B', 'D'
settings.kind = 'ARMS'
assert bpy.ops.sub.custom_ik_create() == {'FINISHED'}
job = next(ik.custom_jobs(custom_obj))
assert job[1] == ('A', 'B', 'C', 'D')
assert hasattr(custom_obj.pose.bones[job[3]].bone, 'sub_ik_arm_pull')
ik.remove(bpy.context, custom_obj, 'ARMS')
assert json.loads(custom_obj['sub_custom_ik_chains']) == []
with tempfile.TemporaryDirectory() as temporary:
    custom_ik.preset_dir = lambda: Path(temporary)
    settings.name = 'Round Trip'
    settings.root, settings.middle, settings.end = 'A', 'B', 'D'
    assert bpy.ops.sub.custom_ik_save() == {'FINISHED'}
    settings.root = ''
    filename = next(Path(temporary).glob('*.json')).name
    assert bpy.ops.sub.custom_ik_load(filename=filename) == {'FINISHED'}
    assert settings.root == 'A'

# Folder lists are stored on each model and exact costume paths do not fall back.
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    paths = [root / name for name in ('Werehog', 'Extras', 'Hulk')]
    for path in paths:
        path.mkdir()
        (path / 'idle.nuanmb').touch()
    a = obj
    b = rig((('X', 'Y', 'Z'),))
    ssp = bpy.context.scene.sub_scene_properties
    for path in paths[:2]:
        folders.remember_animation_folder(ssp, str(path))
    folders.bind_anim_folder_to_armature(a, str(paths[1]), ssp)
    folders.bind_anim_folder_to_armature(b, str(paths[2]))
    bpy.context.view_layer.objects.active = a
    folders.sync_anim_importer_to_active(bpy.context, force=True)
    assert [item.path for item in ssp.animation_import_folders] == [str(path) for path in paths[:2]]
    bpy.context.view_layer.objects.active = b
    folders.sync_anim_importer_to_active(bpy.context, force=True)
    assert [item.path for item in ssp.animation_import_folders] == [str(paths[2])]
    model = root / 'fighter' / 'donkey' / 'model' / 'body' / 'c80'
    motion = root / 'fighter' / 'donkey' / 'motion' / 'body' / 'c80'
    model.mkdir(parents=True)
    motion.mkdir(parents=True)
    assert folders.related_motion_folder(str(model)) == str(motion)
    assert folders.related_motion_folder(str(model.with_name('c00'))) == ''

print('ADAPTIVE IK AND MODEL FOLDER TESTS PASSED')
