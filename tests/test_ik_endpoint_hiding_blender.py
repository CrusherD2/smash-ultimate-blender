from pathlib import Path

from types import SimpleNamespace
from mathutils import Vector

def pose_hidden(pb):
    return pb.hide if hasattr(pb, 'hide') else pb.bone.hide

fixture = Path(__file__).with_name('test_ik_control_orientation_blender.py')
exec(compile(fixture.read_text().split('assert ikc.create_controls')[0], str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
bpy.ops.object.mode_set(mode='EDIT')
parent = data.edit_bones['FootL']
for name in ('Toe1L', 'Toe2L'):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = parent.tail, parent.tail + Vector((0, -0.4, 0))
    bone.parent = parent
    parent = bone
finger = data.edit_bones.new('FingerL')
finger.head, finger.tail = (8, .2, 15), (9, .2, 15)
finger.parent = data.edit_bones['HandL']
bpy.ops.object.mode_set(mode='POSE')
assert ikc.create_controls(bpy.context, arm, 'BOTH') == 2
endpoints = {'ARMS': ('HandL',), 'LEGS': ('FootL', 'Toe1L', 'Toe2L')}
operators = {'ARMS': bpy.ops.sub.create_arm_ik, 'LEGS': bpy.ops.sub.create_foot_ik, 'BOTH': bpy.ops.sub.create_ik_bones}
for limbs, operator in operators.items():
    assert operator.get_rna_type().properties['hide_affected_bones'].name == rig.ik_endpoint_hide_label(limbs)
    for hidden in (False, True):
        rig.set_ik_endpoint_hiding(arm, not hidden)
        rig._set_ik_enabled(bpy.context, arm, True)
        assert operator(match_position=False, hide_affected_bones=hidden) == {'FINISHED'}
        for kind, names in endpoints.items():
            expected = hidden if limbs in (kind, 'BOTH') else not hidden
            preference = data.sub_hide_ik_hand if kind == 'ARMS' else data.sub_hide_ik_foot_toe
            assert preference == expected
            assert all(pose_hidden(arm.pose.bones[n]) == expected for n in names), (limbs, hidden, kind)
        assert not pose_hidden(arm.pose.bones['FingerL'])
        assert not any(pose_hidden(arm.pose.bones[n]) for n in ('HandIKL', 'FootIKL', 'ToeIKL'))

rig.set_ik_endpoint_hiding(arm, True)
for frame, enabled in ((1, True), (5, False), (9, True)):
    scene.frame_set(frame)
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH', set_enabled=True, enable_ik=enabled) == {'FINISHED'}
for frame, hidden in ((1, True), (5, False), (9, True), (5, False), (1, True)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    rig._sync_ik_fk_visibility(scene)
    assert all(pose_hidden(arm.pose.bones[n]) == hidden for names in endpoints.values() for n in names), frame
    assert not pose_hidden(arm.pose.bones['FingerL'])
assert not data.bl_rna.properties['sub_hide_ik_hand'].is_animatable
assert not data.bl_rna.properties['sub_hide_ik_foot_toe'].is_animatable

class Layout:
    def __init__(self):
        self.properties = []
    def row(self, **kwargs): return self
    def column(self, **kwargs): return self
    def label(self, **kwargs): pass
    def prop(self, owner, name, **kwargs): self.properties.append((name, kwargs.get('text')))
    def operator(self, *args, **kwargs): return SimpleNamespace()

for module_name, class_name in (
        ('create_ik_arms', 'SUB_OP_create_arm_ik_operator'),
        ('create_ik_legs', 'SUB_OP_create_foot_ik_operator'),
        ('create_ik_armsandlegs', 'SUB_OP_create_ik_bones_operator')):
    module = importlib.import_module(MODULE + '.source.extras.' + module_name)
    layout = Layout()
    getattr(module, class_name).draw(SimpleNamespace(layout=layout), bpy.context)
    assert [name for name, _ in layout.properties] == ['match_position', 'hide_affected_bones']
for limbs in ('ARMS', 'LEGS', 'BOTH'):
    layout = Layout()
    op = SimpleNamespace(layout=layout, stage='IK', ik_limbs=limbs, match_position=False,
                         ik_entire_animation=True, ik_auto_keyframe=True)
    rig.SUB_OP_create_animation_rig.draw(op, bpy.context)
    assert ('hide_affected_bones', rig.ik_endpoint_hide_label(limbs)) in layout.properties
extras = importlib.import_module(MODULE + '.source.extras.anim_rig_extras')
layout = Layout()
extras._draw_ik_fk_switch_rows(layout, arm)
assert not any(name.startswith('sub_hide_ik_') for name, _ in layout.properties)
print('CREATION DIALOGS, PER-LIMB PREFERENCES, ENDPOINTS AND ANIMATED IK/FK VISIBILITY PASSED')
