"""Bone mapping editor drawn inside the Retargeting panel (step 1)."""
import bpy

from ...expy_kit import ui

SIDES = (('right', 'R'), ('left', 'L'))
CORE_SLOTS = (('head', 'Head'), ('neck', 'Neck'), ('spine2', 'Bust'), ('spine1', 'Waist'), ('hips', 'Hips'))
ARM_SLOTS = (('shoulder', 'Clavicle'), ('arm', 'Shoulder'), ('forearm', 'Arm'), ('hand', 'Hand'))
ARM_TWIST_SLOTS = (('shoulder', 'Clavicle'), ('arm', 'Shoulder'), ('arm_twist', 'Shoulder Twist'),
                   ('arm_twist_02', 'Shoulder Twist 2'), ('forearm', 'Arm'), ('forearm_twist', 'Arm Twist'),
                   ('forearm_twist_02', 'Arm Twist 2'), ('hand', 'Hand'))
LEG_SLOTS = (('upleg', 'Leg'), ('leg', 'Knee'), ('foot', 'Foot'), ('toe', 'Toe'))
LEG_TWIST_SLOTS = (('upleg', 'Leg'), ('upleg_twist', 'Leg Twist'), ('upleg_twist_02', 'Leg Twist 2'),
                   ('leg', 'Knee'), ('leg_twist', 'Knee Twist'), ('leg_twist_02', 'Knee Twist 2'),
                   ('foot', 'Foot'), ('toe', 'Toe'))
FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
FINGER_SLOTS = ('a', 'b', 'c')
ROOT_SLOTS = (('root', 'Root'), ('throw', 'Throw'))
# Sections that count toward "mapped"; fingers and custom bones are optional.
REQUIRED_SECTIONS = ('core', 'arms', 'legs', 'root')
SECTION_LABELS = (('core', 'Core'), ('arms', 'Arms'), ('legs', 'Legs'), ('fingers', 'Fingers'),
                  ('root', 'Root & Throw'), ('custom', 'Custom Bones'))


def is_mappable_armature(ob) -> bool:
    return ob is not None and ob.type == 'ARMATURE' and hasattr(ob.data, 'expykit_retarget')


def section_slots(arm_data, section: str) -> list[tuple[object, str]]:
    """(property group, attribute) pairs shown for one section of an armature's mapping."""
    skeleton = arm_data.expykit_retarget
    twist = arm_data.expykit_twist_on
    if section == 'core':
        return [(skeleton.spine, slot) for slot, _ in CORE_SLOTS]
    if section in {'arms', 'legs'}:
        limb = 'arm' if section == 'arms' else 'leg'
        slots = (ARM_TWIST_SLOTS if twist else ARM_SLOTS) if limb == 'arm' else (LEG_TWIST_SLOTS if twist else LEG_SLOTS)
        return [(getattr(skeleton, f'{side}_{limb}'), slot) for side, _ in SIDES for slot, _ in slots]
    if section == 'fingers':
        return [(getattr(getattr(skeleton, f'{side}_fingers'), finger), slot)
                for side, _ in SIDES for finger in FINGERS for slot in FINGER_SLOTS]
    if section == 'root':
        return [(skeleton, slot) for slot, _ in ROOT_SLOTS]
    raise ValueError(section)


def section_count(arm_data, section: str) -> tuple[int, int]:
    if section == 'custom':
        bones = len(arm_data.expykit_retarget.custom.get_bones())
        return bones, bones
    slots = section_slots(arm_data, section)
    return sum(1 for group, slot in slots if getattr(group, slot)), len(slots)


def mapping_count(arm_data) -> tuple[int, int]:
    counts = [section_count(arm_data, section) for section in REQUIRED_SECTIONS]
    return sum(done for done, _ in counts), sum(total for _, total in counts)


def animation_from(scene):
    ob = getattr(scene, 'expykit_bind_to', None)
    return ob if is_mappable_armature(ob) else None


def ensure_pose_position(ob) -> bool:
    """Show the pose, not the rest pose. Returns True if it had to switch.

    Rest Position ignores pose transforms, including the helper bones' scale that cancels a
    Create Transforms Offset scale, so a bound model would stretch while it's on.
    """
    if ob is None or ob.data.pose_position != 'REST':
        return False
    ob.data.pose_position = 'POSE'
    return True


def apply_to(context):
    """The explicitly chosen armature that receives the animation."""
    scene = context.scene
    driver = animation_from(scene)
    chosen = getattr(scene, 'sub_retarget_apply_to', None)
    if is_mappable_armature(chosen) and chosen != driver:
        return chosen
    return None


def _section_icon(section: str, done: int, total: int) -> str:
    if section == 'custom':
        return 'BONE_DATA'
    if total and done == total:
        return 'CHECKMARK'
    if done == 0 and section == 'fingers':
        return 'RADIOBUT_OFF'
    return 'ERROR'


def _pick_button(layout, attr_name: str, slot_name: str, sub_attr_name: str = ''):
    op = layout.operator(ui.SetToActiveBone.bl_idname, text='', icon='EYEDROPPER')
    op.attr_name = attr_name
    op.sub_attr_name = sub_attr_name
    op.slot_name = slot_name


def _slot_field(layout, ob, group, slot: str, attr_name: str, sub_attr_name: str = '', required: bool = True):
    row = layout.row(align=True)
    row.alert = required and not getattr(group, slot)
    row.prop_search(group, slot, ob.data, 'bones', text='')
    _pick_button(row, attr_name, slot, sub_attr_name)


def _sided_row(layout, ob, label: str, slot: str, groups, attr_names, sub_attr_name: str = '', required: bool = True):
    split = layout.split(factor=0.4, align=True)
    _slot_field(split, ob, groups[0], slot, attr_names[0], sub_attr_name, required)
    rest = split.split(factor=1 / 3, align=True)
    middle = rest.row()
    middle.alignment = 'CENTER'
    middle.label(text=label)
    _slot_field(rest, ob, groups[1], slot, attr_names[1], sub_attr_name, required)


# Below this sidebar width (at 1x UI scale) Right/Left columns get too narrow for bone names.
SIDE_BY_SIDE_MIN_WIDTH = 400


def wide_enough(context) -> bool:
    region = getattr(context, 'region', None)
    if region is None:
        return True
    return region.width >= SIDE_BY_SIDE_MIN_WIDTH * context.preferences.system.ui_scale


def _stacked_rows(layout, ob, rows, groups, attr_names, required: bool = True):
    """rows: (label, slot, sub_attr_name). One full-width block per side."""
    for (side, _), group_for_side, attr_name in zip(SIDES, zip(*groups), attr_names):
        layout.label(text=side.title())
        col = layout.column(align=True)
        for (label, slot, sub_attr_name), group in zip(rows, group_for_side):
            row = col.row(align=True)
            row.alert = required and not getattr(group, slot)
            row.prop_search(group, slot, ob.data, 'bones', text=label)
            _pick_button(row, attr_name, slot, sub_attr_name)


def _side_headers(layout):
    split = layout.split(factor=0.4)
    split.label(text='Right')
    rest = split.split(factor=1 / 3)
    rest.label(text='')
    rest.label(text='Left')


def _mirror_row(layout, right_attr: str, left_attr: str, ob=None):
    row = layout.row(align=True)
    op = row.operator(ui.MirrorSettings.bl_idname, text='Copy R \u2192 L')
    op.src_setting, op.trg_setting = right_attr, left_attr
    op = row.operator(ui.MirrorSettings.bl_idname, text='Copy L \u2192 R')
    op.src_setting, op.trg_setting = left_attr, right_attr
    if ob is not None:
        row.prop(ob.data, 'expykit_twist_on', text='Twist Bones', toggle=True)


def draw_core(layout, ob):
    spine = ob.data.expykit_retarget.spine
    for slot, label in CORE_SLOTS:
        row = layout.row(align=True)
        row.alert = not getattr(spine, slot)
        row.prop_search(spine, slot, ob.data, 'bones', text=label)
        _pick_button(row, 'spine', slot)


def draw_limb(layout, ob, limb: str, wide: bool = True):
    skeleton = ob.data.expykit_retarget
    twist = ob.data.expykit_twist_on
    if limb == 'arm':
        slots = ARM_TWIST_SLOTS if twist else ARM_SLOTS
    else:
        slots = LEG_TWIST_SLOTS if twist else LEG_SLOTS
    attr_names = (f'right_{limb}', f'left_{limb}')
    groups = tuple(getattr(skeleton, name) for name in attr_names)
    if wide:
        _side_headers(layout)
        for slot, label in slots:
            _sided_row(layout, ob, label, slot, groups, attr_names)
    else:
        rows = [(label, slot, '') for slot, label in slots]
        _stacked_rows(layout, ob, rows, [groups] * len(rows), attr_names)
    _mirror_row(layout, *attr_names, ob=ob)


def draw_fingers(layout, ob, wide: bool = True):
    skeleton = ob.data.expykit_retarget
    attr_names = ('right_fingers', 'left_fingers')
    sides = tuple(getattr(skeleton, name) for name in attr_names)
    rows, groups = [], []
    for finger in FINGERS:
        for number, slot in enumerate(FINGER_SLOTS, start=1):
            rows.append((f'{finger.title()} {number}', slot, finger))
            groups.append(tuple(getattr(side, finger) for side in sides))
    if wide:
        _side_headers(layout)
        for (label, slot, finger), pair in zip(rows, groups):
            _sided_row(layout, ob, label, slot, pair, attr_names, sub_attr_name=finger, required=False)
    else:
        _stacked_rows(layout, ob, rows, groups, attr_names, required=False)
    _mirror_row(layout, *attr_names)


def draw_root(layout, ob):
    skeleton = ob.data.expykit_retarget
    for slot, label in ROOT_SLOTS:
        row = layout.row(align=True)
        row.alert = not getattr(skeleton, slot)
        row.prop_search(skeleton, slot, ob.data, 'bones', text=label)
        _pick_button(row, slot, '')
    layout.separator()
    layout.prop(skeleton, 'deform_preset')
    layout.operator(ui.ClearArmatureRetarget.bl_idname, text='Clear All', icon='TRASH')


class _CustomBonesLayout(ui.RetargetBasePanel):
    """Reuse Expy's Custom Bones drawing without registering another panel."""
    def __init__(self, layout):
        self.layout = layout


def draw_sections(layout, context, ob):
    wide = wide_enough(context)
    for section, label in SECTION_LABELS:
        done, total = section_count(ob.data, section)
        header, body = layout.panel('sub_retarget_mapping_' + section, default_closed=section != 'core')
        header.label(text=label, icon=_section_icon(section, done, total))
        count = header.row()
        count.alignment = 'RIGHT'
        if section == 'custom':
            count.label(text=str(total))
        elif section == 'fingers' and done == 0:
            count.label(text='optional')
        else:
            count.label(text=f'{done} / {total}')
        if body is None:
            continue
        if section == 'core':
            draw_core(body, ob)
        elif section == 'arms':
            draw_limb(body, ob, 'arm', wide)
        elif section == 'legs':
            draw_limb(body, ob, 'leg', wide)
        elif section == 'fingers':
            draw_fingers(body, ob, wide)
        elif section == 'root':
            draw_root(body, ob)
        else:
            ui.VIEW3D_PT_expy_retarget_custom.draw(_CustomBonesLayout(body), context)


def draw_armature_switch(layout, context):
    """One button per armature; the pressed one is the armature being edited."""
    driver, receiver = animation_from(context.scene), apply_to(context)
    if driver is None or receiver is None:
        if is_mappable_armature(context.object):
            layout.label(text=f'Editing: {context.object.name}', icon='ARMATURE_DATA')
        return
    labels = layout.split(factor=0.5)
    labels.label(text='Animation From')
    labels.label(text='Apply To')
    row = layout.row(align=True)
    for role, ob in (('FROM', driver), ('TO', receiver)):
        done, total = mapping_count(ob.data)
        op = row.operator('sub.retarget_edit_armature', text=f'{ob.name}  {done}/{total}',
                          icon='ARMATURE_DATA', depress=context.object == ob)
        op.role = role


class SUB_OT_retarget_edit_armature(bpy.types.Operator):
    bl_idname = 'sub.retarget_edit_armature'
    bl_label = 'Edit Armature Mapping'
    bl_description = 'Make this armature active so its bone mapping shows below'
    bl_options = {'REGISTER', 'UNDO'}

    role: bpy.props.EnumProperty(items=(('FROM', 'Animation From', ''), ('TO', 'Apply To', '')))

    def execute(self, context):
        scene = context.scene
        receiver = apply_to(context)
        target = animation_from(scene) if self.role == 'FROM' else receiver
        if target is None:
            self.report({'WARNING'}, 'Set "Animation from" and "Apply to" first')
            return {'CANCELLED'}
        if not target.visible_get():
            self.report({'WARNING'}, f'{target.name} is hidden; unhide it to edit its mapping')
            return {'CANCELLED'}
        # Remember the receiver before it stops being the selected armature.
        if receiver is not None and not is_mappable_armature(getattr(scene, 'sub_retarget_apply_to', None)):
            scene.sub_retarget_apply_to = receiver
        was_pose = context.mode == 'POSE'
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.selected_objects:
            ob.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        if was_pose:
            bpy.ops.object.mode_set(mode='POSE')
        return {'FINISHED'}


def poll_apply_to(scene, ob):
    return ob.type == 'ARMATURE' and ob != getattr(scene, 'expykit_bind_to', None)


def poll_animation_from(scene, ob):
    # Unlike Expy Kit's own picker, the selected armature is offered too.
    return ob.type == 'ARMATURE' and ob != getattr(scene, 'sub_retarget_apply_to', None)


def scene_armatures(scene):
    return sorted((ob for ob in scene.objects if is_mappable_armature(ob)), key=lambda ob: ob.name)


class SUB_OT_retarget_set_role(bpy.types.Operator):
    bl_idname = 'sub.retarget_set_role'
    bl_label = 'Set Armature Role'
    bl_description = 'Use this armature as "Animation From" or "Apply To"; click again to clear it'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})
    role: bpy.props.EnumProperty(items=(('FROM', 'Animation From', ''), ('TO', 'Apply To', '')),
                                 options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        ob = scene.objects.get(self.name)
        if not is_mappable_armature(ob):
            self.report({'ERROR'}, f'{self.name} is not an armature in this scene')
            return {'CANCELLED'}
        mine, other = (('expykit_bind_to', 'sub_retarget_apply_to') if self.role == 'FROM'
                       else ('sub_retarget_apply_to', 'expykit_bind_to'))
        if getattr(scene, mine) == ob:
            setattr(scene, mine, None)
            return {'FINISHED'}
        # One armature can't be both; picking it for this role swaps the roles.
        if getattr(scene, other) == ob:
            setattr(scene, other, getattr(scene, mine))
        setattr(scene, mine, ob)
        return {'FINISHED'}


def draw_armature_list(layout, context):
    """Every armature in the scene with From / To buttons, whatever is selected."""
    scene = context.scene
    driver, receiver = animation_from(scene), apply_to(context)
    armatures = scene_armatures(scene)
    if not armatures:
        layout.label(text='No armatures in this scene', icon='ERROR')
        return
    box = layout.box()
    col = box.column(align=True)
    for ob in armatures:
        row = col.split(factor=0.62, align=True)
        icon = 'ARMATURE_DATA' if ob.visible_get() else 'HIDE_ON'
        row.label(text=ob.name, icon=icon)
        buttons = row.row(align=True)
        for role, text, current in (('FROM', 'From', driver), ('TO', 'To', receiver)):
            op = buttons.operator(SUB_OT_retarget_set_role.bl_idname, text=text, depress=current == ob)
            op.name, op.role = ob.name, role
