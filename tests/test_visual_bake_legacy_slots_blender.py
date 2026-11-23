import importlib.util
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_slot_worker', ROOT / 'source/retargeting/bake_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
baker = worker.load_baker()


def check(parallel):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rigs = []
    for name in ('Source', 'Destination'):
        obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bone = obj.data.edit_bones.new('root')
        bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.animation_data_create()
        rigs.append(obj)
    source, dest = rigs
    constraint = dest.pose.bones['root'].constraints.new('COPY_TRANSFORMS')
    constraint.target, constraint.subtarget = source, 'root'
    actions = []
    handles = []
    for index in range(2):
        action = bpy.data.actions.new('Legacy Clip ' + str(index))
        slot = action.slots.new('OBJECT', name='Legacy Slot')
        source.animation_data.action = action
        source.animation_data.action_slot = slot
        for frame in (1, 3):
            source.pose.bones['root'].location.x = (index + 1) * frame
            source.pose.bones['root'].keyframe_insert('location', frame=frame)
        # An earlier assignment may already have created an empty owner-named slot.
        action.slots.new('OBJECT', name=source.name)
        actions.append(action)
        handles.append(slot.handle)
    source.animation_data.action = actions[0]
    source.animation_data.action_slot = next(s for s in actions[0].slots if s.handle == handles[0])
    original_filepath = bpy.data.filepath
    pairs = baker.bake_visual_actions(bpy.context, source, dest, actions, parallel=parallel)
    assert len(pairs) == 2
    assert bpy.data.filepath == original_filepath
    for index, (original, baked) in enumerate(pairs):
        assert len(original.slots) == 2
        baker.load_baked_action(dest, baked)
        for frame in (1, 2, 3):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            assert abs(dest.pose.bones['root'].matrix.translation.x - (index + 1) * frame) < 1e-5
    print('LEGACY SLOT BATCH BAKE PASSED', parallel)


check(False)
check(True)
