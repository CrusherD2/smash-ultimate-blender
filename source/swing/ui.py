# BPY Imports
from typing import NamedTuple

import bpy
from bpy.types import (
    Panel, UIList, Menu, UILayout)
# Standard Library Imports
# 3rd Party Imports
# Local Project Imports
from .sub_swing_data import *
from .operators import *
from ..blender_property_extensions import SubSceneProperties

class SUB_PT_active_bone_swing_info(Panel):
    bl_label = 'Ultimate Swing Data'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'bone'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.active_bone

    def draw(self, context):
        active_bone: bpy.types.Bone = context.active_object.data.bones.get(context.active_bone.name) 
        sub_swing_data: SUB_PG_sub_swing_data = context.object.data.sub_swing_data
        sub_swing_blender_bone_data: SUB_PG_blender_bone_data = active_bone.sub_swing_blender_bone_data
        layout = self.layout
        col = layout.column()
        chain_index = sub_swing_blender_bone_data.swing_bone_chain_index
        if not active_bone.name.startswith('S_'):
            col.label(text='This bone does not start with "S_",')
            col.label(text='so it cannot be part of a swing bone chain')
            return
        if active_bone.name.endswith('_null'):
            col.label(text='This is a "null" swing bone,') 
            col.label(text='so it contains no swing info,')
            col.label(text='but it is needed for the swing chain to properly function.')
            return
        if chain_index == -1:
            col.label(text='This swing bone is not part of a swing bone chain')
            return
        swing_bone_chain: SUB_PG_swing_bone_chain = sub_swing_data.swing_bone_chains[chain_index]
        col.label(text=f'Swing Bone Chain Name: {swing_bone_chain.name}')
        swing_bone: SUB_PG_swing_bone = swing_bone_chain.swing_bones[sub_swing_blender_bone_data.swing_bone_index]
        col.label(text=f'Swing Bone Collisions')
        col.template_list(
                        'SUB_UL_swing_bone_collisions',
                        '',
                        swing_bone,
                        'collisions',
                        swing_bone,
                        'active_collision_index',
                        rows=5,
                        maxrows=5,
                    )
        col.label(text='Swing Bone Props:')
        col.prop(swing_bone, 'air_resistance')
        col.prop(swing_bone, 'water_resistance')
        col.prop(swing_bone, 'angle_z')
        col.prop(swing_bone, 'angle_y')
        col.prop(swing_bone, 'collision_size')
        col.prop(swing_bone, 'friction_rate')
        col.prop(swing_bone, 'goal_strength')
        col.prop(swing_bone, 'inertial_mass')
        col.prop(swing_bone, 'local_gravity')
        col.prop(swing_bone, 'fall_speed_scale')
        col.prop(swing_bone, 'ground_hit')
        col.prop(swing_bone, 'wind_affect')


class SUB_PT_active_mesh_swing_info(Panel):
    bl_label = 'Ultimate Swing Data'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        try:
            type = bpy.context.active_object.type
        except:
            return False
        else:
            return type == 'MESH'

    def draw(self, context):
        layout = self.layout
        mesh_obj: bpy.types.Object = bpy.context.active_object
        mesh_data: bpy.types.Mesh = mesh_obj.data
        sub_swing_data_linked_mesh: SUB_PG_sub_swing_data_linked_mesh = mesh_data.sub_swing_data_linked_mesh

        if not sub_swing_data_linked_mesh.is_swing_mesh:
            layout.row().label(text="This is not a swing collision mesh.")
            return
        sub_swing_data: SUB_PG_sub_swing_data = mesh_obj.parent.data.sub_swing_data

        if sub_swing_data_linked_mesh.is_swing_bone_shape:
            swing_bone_chain: SUB_PG_swing_bone_chain = sub_swing_data.swing_bone_chains[sub_swing_data_linked_mesh.swing_chain_index]
            swing_bone: SUB_PG_swing_bone = swing_bone_chain.swing_bones[sub_swing_data_linked_mesh.swing_bone_index]
            col = layout.column()
            col.label(text=f'Swing Bone Chain Name: {swing_bone_chain.name}')
            col.label(text=f'Swing Bone Name: {swing_bone.name}')
            col.label(text=f'Swing Bone Collisions')
            col.template_list(
                            'SUB_UL_swing_bone_collisions',
                            '',
                            swing_bone,
                            'collisions',
                            swing_bone,
                            'active_collision_index',
                            rows=5,
                            maxrows=5,
                        )
            col.label(text='Swing Bone Props:')
            col.prop(swing_bone, 'air_resistance')
            col.prop(swing_bone, 'water_resistance')
            col.prop(swing_bone, 'angle_z')
            col.prop(swing_bone, 'angle_y')
            col.prop(swing_bone, 'collision_size')
            col.prop(swing_bone, 'friction_rate')
            col.prop(swing_bone, 'goal_strength')
            col.prop(swing_bone, 'inertial_mass')
            col.prop(swing_bone, 'local_gravity')
            col.prop(swing_bone, 'fall_speed_scale')
            col.prop(swing_bone, 'ground_hit')
            col.prop(swing_bone, 'wind_affect')
            return

        
        if sub_swing_data_linked_mesh.collision_collection_type == 'SPHERE':
            swing_sphere: SUB_PG_swing_sphere = sub_swing_data.spheres[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_sphere, "bone")
            layout.row().prop(swing_sphere, "offset")
            layout.row().prop(swing_sphere, "radius")
        
        if sub_swing_data_linked_mesh.collision_collection_type == 'OVAL':
            swing_oval = sub_swing_data.ovals[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_oval, "start_bone_name")
            layout.row().prop(swing_oval, "end_bone_name")
            layout.row().prop(swing_oval, "radius")
            layout.row().prop(swing_oval, "start_offset")
            layout.row().prop(swing_oval, "end_offset")

        if sub_swing_data_linked_mesh.collision_collection_type == 'ELLIPSOID':
            swing_ellipsoid = sub_swing_data.ellipsoids[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_ellipsoid, "bone_name")
            layout.row().prop(swing_ellipsoid, "offset")
            layout.row().prop(swing_ellipsoid, "rotation")
            layout.row().prop(swing_ellipsoid, "scale")

        if sub_swing_data_linked_mesh.collision_collection_type == 'CAPSULE':
            swing_capsule = sub_swing_data.capsules[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_capsule, "start_bone_name")
            layout.row().prop(swing_capsule, "end_bone_name")
            layout.row().prop(swing_capsule, "start_offset")
            layout.row().prop(swing_capsule, "end_offset")
            layout.row().prop(swing_capsule, "start_radius")
            layout.row().prop(swing_capsule, "end_radius")
        
        if sub_swing_data_linked_mesh.collision_collection_type == 'PLANE':
            swing_plane = sub_swing_data.planes[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_plane, "bone_name")
            layout.row().prop(swing_plane, "nx")
            layout.row().prop(swing_plane, "ny")
            layout.row().prop(swing_plane, "nz")
            layout.row().prop(swing_plane, "distance")

        if sub_swing_data_linked_mesh.collision_collection_type == 'CONNECTION':
            swing_connection = sub_swing_data.connections[sub_swing_data_linked_mesh.collision_collection_index]
            layout.row().prop(swing_connection, "start_bone_name")
            layout.row().prop(swing_connection, "end_bone_name")
            layout.row().prop(swing_connection, "radius")
            layout.row().prop(swing_connection, "length")

        

class SwingPropertyPanel: # Mix-in for the swing info property panel classes
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'

class SUB_PT_swing_data_master(Panel, SwingPropertyPanel):
    bl_label = "Ultimate Swing Data"

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator('sub.swing_import', icon='IMPORT', text='Import swing.prc')
        row.operator('sub.swing_export', icon='EXPORT', text='Export swing.prc')


BONE_SCALAR_PROPS = (
    ('inertial_mass', 'Mass'), ('goal_strength', 'Goal Str.'),
    ('local_gravity', 'Gravity'), ('fall_speed_scale', 'Fall Speed'),
    ('air_resistance', 'Air Res.'), ('water_resistance', 'Water Res.'),
    ('friction_rate', 'Friction'), ('wind_affect', 'Wind'),
)
BONE_RANGE_PROPS = (
    ('angle_y', 'X Limit'), ('angle_z', 'Z Limit'), ('collision_size', 'Size Head / Tail'),
)
CHAIN_PROPS = ('is_skirt', 'rotate_order', 'curve_rotate_x', 'has_unk_8')


class SUB_PT_swing_bone_chains(Panel, SwingPropertyPanel):
    bl_label = "Swing Bone Chains"
    bl_parent_id = "SUB_PT_swing_data_master"

    def draw(self, context):
        layout = self.layout
        sub_swing_data: SUB_PG_sub_swing_data = context.object.data.sub_swing_data
        chains = sub_swing_data.swing_bone_chains
        active_chain = chains[sub_swing_data.active_swing_bone_chain_index] if len(chains) > 0 else None
        active_bone = None
        if active_chain is not None and len(active_chain.swing_bones) > 0:
            active_bone = active_chain.swing_bones[active_chain.active_swing_bone_index]

        split = layout.split(factor=.5)
        c = split.column()
        c.label(text='Chains')
        c.template_list(
            "SUB_UL_swing_bone_chains", "",
            sub_swing_data, "swing_bone_chains",
            sub_swing_data, "active_swing_bone_chain_index",
            rows=4, maxrows=8,
        )
        # Grid cells stretch icon-only buttons to equal widths; a row keeps them icon-sized.
        r = c.grid_flow(columns=3, even_columns=True, align=True)
        r.operator(SUB_OP_swing_bone_chain_add.bl_idname, text='', icon='ADD')
        r.operator(SUB_OP_swing_bone_chain_remove.bl_idname, text='', icon='REMOVE')
        r.operator('sub.swing_bone_chain_auto_detect', text='', icon='FILE_REFRESH')

        c = split.column()
        c.label(text='Bones')
        if active_chain is None:
            c.enabled = False
            c.box().label(text='No chain selected')
        else:
            c.template_list(
                'SUB_UL_swing_bones', '',
                active_chain, 'swing_bones',
                active_chain, 'active_swing_bone_index',
                rows=4, maxrows=8,
            )
            r = c.row(align=True)
            r.operator(SUB_OP_swing_bone_chain_length_edit.bl_idname, text='Edit Start/End')
            r.operator('sub.swing_select_active_bone', text='', icon='RESTRICT_SELECT_OFF')
            r.prop(sub_swing_data, 'follow_active_bone', text='',
                   icon='LINKED' if sub_swing_data.follow_active_bone else 'UNLINKED')

        if active_chain is None:
            box = layout.box()
            box.label(text='No swing chains yet.', icon='INFO')
            box.label(text='Auto-Detect builds them from the S_ bones.')
            return

        layout.separator()
        layout.row().prop(sub_swing_data, 'active_tab', expand=True)
        tab = sub_swing_data.active_tab
        if tab == 'CHAIN':
            self.draw_chain_tab(layout, active_chain)
        elif tab == 'PRESETS':
            self.draw_presets_tab(layout, context)
        elif active_bone is None:
            layout.box().label(text='This chain has no bones. Use Edit Start/End.', icon='INFO')
        elif tab == 'COLLISIONS':
            self.draw_collisions_tab(layout, active_bone)
        else:
            self.draw_bone_tab(layout, active_bone)

    @staticmethod
    def draw_bone_tab(layout: UILayout, bone):
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=False)
        for name, text in BONE_SCALAR_PROPS:
            cell = grid.split(factor=.5)
            label = cell.row()
            label.alignment = 'RIGHT'
            label.label(text=text)
            cell.prop(bone, name, text='')
        col = layout.column()
        for name, text in BONE_RANGE_PROPS:
            row = col.split(factor=.4)
            label = row.row()
            label.alignment = 'RIGHT'
            label.label(text=text)
            pair = row.row(align=True)
            pair.prop(bone, name, index=0, text='')
            pair.prop(bone, name, index=1, text='')
        row = col.split(factor=.4)
        row.label(text='')
        row.prop(bone, 'ground_hit')
        layout.separator()
        r = layout.row(align=True)
        r.operator('sub.swing_bone_copy_values', text='Copy')
        r.operator('sub.swing_bone_paste_values', text='Paste')
        # wm.call_menu draws a regular button, matching Copy/Paste, instead of a dark dropdown.
        r.operator('wm.call_menu', text='Apply to', icon='DOWNARROW_HLT').name = 'SUB_MT_swing_bone_apply_values'

    @staticmethod
    def draw_chain_tab(layout: UILayout, chain):
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        for name in CHAIN_PROPS:
            col.prop(chain, name)
        if chain.has_unk_8:
            col.prop(chain, 'unk_8')

    @staticmethod
    def draw_collisions_tab(layout: UILayout, bone):
        row = layout.row()
        row.template_list(
            'SUB_UL_swing_bone_collisions', '',
            bone, 'collisions',
            bone, 'active_collision_index',
            rows=4, maxrows=8,
        )
        side = row.column(align=True)
        side.menu('SUB_MT_swing_bone_collision_add', text='', icon='ADD')
        side.operator(SUB_OP_swing_bone_collision_remove.bl_idname, text='', icon='REMOVE')
        r = layout.row(align=True)
        r.operator('sub.swing_bone_copy_collisions', text='Copy Collisions')
        r.operator('sub.swing_bone_paste_collisions', text='Paste Collisions')

    @staticmethod
    def draw_presets_tab(layout: UILayout, context):
        scene = context.scene
        for label, prop, add, remove, apply in (
            ('Bone Preset', 'sub_swing_preset', 'sub.swing_preset_add', 'sub.swing_preset_remove', 'sub.swing_preset_apply'),
            ('Chain Preset', 'sub_swing_chain_preset', 'sub.swing_chain_preset_add', 'sub.swing_chain_preset_remove', 'sub.swing_chain_preset_apply'),
        ):
            col = layout.column()
            col.label(text=label)
            r = col.row(align=True)
            r.prop(scene, prop, text='')
            r.operator(add, text='', icon='ADD')
            r.operator(remove, text='', icon='REMOVE')
            selected = getattr(scene, prop)
            sub = col.row()
            sub.enabled = bool(selected) and selected != '--'
            sub.operator(apply, text=f'Apply {label}')


class SUB_MT_swing_bone_apply_values(Menu):
    bl_label = "Apply Bone Values To"

    def draw(self, context):
        layout = self.layout
        layout.operator('sub.swing_bone_copy_values_to_all', icon='OUTLINER_OB_ARMATURE', text='Every Bone in This Chain')
        layout.operator('sub.swing_bone_copy_values_to_all_chains', icon='ARMATURE_DATA', text='Every Bone in Every Chain')


MAX_BONE_COLLISION_ICONS = 4


def draw_collision_icons(layout: UILayout, collision_kinds: list[str]):
    if not collision_kinds:
        return
    icons = layout.row(align=True)
    icons.alignment = 'RIGHT'
    for kind in collision_kinds[:MAX_BONE_COLLISION_ICONS]:
        icons.label(text='', icon=SHAPE_TYPES[kind].icon)
    hidden = len(collision_kinds) - MAX_BONE_COLLISION_ICONS
    if hidden > 0:
        icons.label(text=f'+{hidden}')


def chain_collision_kinds(chain) -> list[str]:
    used = {c.collision_type for bone in chain.swing_bones for c in bone.collisions}
    return [kind for kind in SHAPE_TYPES if kind in used]


class SUB_UL_swing_bone_chains(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(entry, "name", text="", emboss=False, icon='GROUP_BONE')
            draw_collision_icons(row, chain_collision_kinds(entry))
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SUB_UL_swing_bones(UIList):
    def draw_item(self, context, layout: UILayout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            #row.prop(entry, "name", text="", emboss=False)
            row.label(text=f'{entry.name}', icon='BONE_DATA')
            draw_collision_icons(row, [c.collision_type for c in entry.collisions])
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SUB_UL_swing_bone_collisions(UIList):
    def draw_item(self, context, layout: bpy.types.UILayout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry: SUB_PG_swing_bone_collision = item

        arma = entry.id_data
        ssd: SUB_PG_sub_swing_data = arma.sub_swing_data
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            if entry.collision_type == 'SPHERE':
                collision = ssd.spheres[entry.collision_index]
                icon = 'SPHERE'
            elif entry.collision_type == 'OVAL':
                collision = ssd.ovals[entry.collision_index]
                icon = 'MESH_CYLINDER'
            elif entry.collision_type == 'ELLIPSOID':
                collision = ssd.ellipsoids[entry.collision_index]
                icon = 'META_ELLIPSOID'
            elif entry.collision_type == 'CAPSULE':
                collision = ssd.capsules[entry.collision_index]
                icon = 'META_CAPSULE'
            elif entry.collision_type == 'PLANE':
                collision = ssd.planes[entry.collision_index]
                icon = 'MESH_PLANE'
            row.label(text=f'{collision.name}', icon=icon)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)



class SUB_MT_swing_bone_collision_add(Menu):
    bl_label = "Add from existing collision"

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row = layout.operator(SUB_OP_swing_bone_collision_add_sphere.bl_idname, text='Sphere', icon='SPHERE')
        row = layout.row()
        row = layout.operator(SUB_OP_swing_bone_collision_add_oval.bl_idname, text='Oval', icon='MESH_CYLINDER')
        row = layout.row()
        row = layout.operator(SUB_OP_swing_bone_collision_add_ellipsoid.bl_idname, text='Ellipsoid', icon='META_ELLIPSOID')
        row = layout.row()
        row = layout.operator(SUB_OP_swing_bone_collision_add_capsule.bl_idname, text='Capsule', icon='META_CAPSULE')
        row = layout.row()
        row = layout.operator(SUB_OP_swing_bone_collision_add_plane.bl_idname, text='Plane', icon='MESH_PLANE')


class ShapeType(NamedTuple):
    collection: str
    index_prop: str
    icon: str
    label: str
    add_op: str
    remove_op: str
    list_type: str


SHAPE_TYPES = {
    'SPHERE': ShapeType('spheres', 'active_sphere_index', 'SPHERE', 'Sphere',
                        'sub.swing_data_sphere_add', 'sub.swing_data_sphere_remove', 'SUB_UL_swing_data_spheres'),
    'OVAL': ShapeType('ovals', 'active_oval_index', 'MESH_CYLINDER', 'Oval',
                      'sub.swing_data_oval_add', 'sub.swing_data_oval_remove', 'SUB_UL_swing_data_ovals'),
    'ELLIPSOID': ShapeType('ellipsoids', 'active_ellipsoid_index', 'META_ELLIPSOID', 'Ellipsoid',
                           'sub.swing_data_ellipsoid_add', 'sub.swing_data_ellipsoid_remove', 'SUB_UL_swing_data_ellipsoids'),
    'CAPSULE': ShapeType('capsules', 'active_capsule_index', 'META_CAPSULE', 'Capsule',
                         'sub.swing_data_capsule_add', 'sub.swing_data_capsule_remove', 'SUB_UL_swing_data_capsules'),
    'PLANE': ShapeType('planes', 'active_plane_index', 'MESH_PLANE', 'Plane',
                       'sub.swing_data_plane_add', 'sub.swing_data_plane_remove', 'SUB_UL_swing_data_planes'),
    'CONNECTION': ShapeType('connections', 'active_connection_index', 'MOD_LENGTH', 'Connection',
                            'sub.swing_data_connection_add', 'sub.swing_data_connection_remove', 'SUB_UL_swing_data_connections'),
}

# (property, label, is_bone)
SHAPE_FIELDS = {
    'SPHERE': (('name', 'Name', False), ('bone', 'Bone', True), ('offset', 'Offset', False), ('radius', 'Radius', False)),
    'OVAL': (('name', 'Name', False), ('start_bone_name', 'Start Bone', True), ('end_bone_name', 'End Bone', True),
             ('radius', 'Radius', False), ('start_offset', 'Start Offset', False), ('end_offset', 'End Offset', False)),
    'ELLIPSOID': (('name', 'Name', False), ('bone_name', 'Bone', True), ('offset', 'Offset', False),
                  ('rotation', 'Rotation', False), ('scale', 'Scale', False)),
    'CAPSULE': (('name', 'Name', False), ('start_bone_name', 'Start Bone', True), ('end_bone_name', 'End Bone', True),
                ('start_offset', 'Start Offset', False), ('end_offset', 'End Offset', False),
                ('start_radius', 'Start Radius', False), ('end_radius', 'End Radius', False)),
    'PLANE': (('name', 'Name', False), ('bone_name', 'Bone', True), ('distance', 'Distance', False)),
    'CONNECTION': (('start_bone_name', 'Start Bone', True), ('end_bone_name', 'End Bone', True),
                   ('radius', 'Radius', False), ('length', 'Length', False)),
}


def shape_label(kind: str, item) -> tuple[str, str]:
    if kind == 'CONNECTION':
        return f'{item.start_bone_name} → {item.end_bone_name}', ''
    if kind in {'OVAL', 'CAPSULE'}:
        return item.name, f'{item.start_bone_name} → {item.end_bone_name}'
    return item.name, item.bone if kind == 'SPHERE' else item.bone_name


def shape_users(ssd, kind: str, index: int) -> int:
    return sum(
        any(c.collision_type == kind and c.collision_index == index for c in bone.collisions)
        for chain in ssd.swing_bone_chains for bone in chain.swing_bones)


def draw_shape_item(layout: UILayout, kind: str, item):
    name, bone = shape_label(kind, item)
    split = layout.split(factor=.5)
    if kind == 'CONNECTION':
        split.label(text=name, icon=SHAPE_TYPES[kind].icon)
    else:
        split.prop(item, 'name', text='', emboss=False, icon=SHAPE_TYPES[kind].icon)
    right = split.row()
    right.alignment = 'RIGHT'
    right.label(text=bone)


class SUB_PT_swing_collision_shapes(Panel, SwingPropertyPanel):
    bl_label = "Collision Shapes"
    bl_parent_id = "SUB_PT_swing_data_master"

    def draw(self, context):
        layout = self.layout
        ssd: SUB_PG_sub_swing_data = context.object.data.sub_swing_data
        counts = {kind: len(getattr(ssd, shape.collection)) for kind, shape in SHAPE_TYPES.items()}

        row = layout.row(align=True)
        row.prop_enum(ssd, 'shape_filter', 'ALL', text=f'All {sum(counts.values())}')
        for kind, shape in SHAPE_TYPES.items():
            row.prop_enum(ssd, 'shape_filter', kind, text=str(counts[kind]), icon=shape.icon)

        showing_all = ssd.shape_filter == 'ALL'
        kind = ssd.active_shape_type if showing_all else ssd.shape_filter
        shape = SHAPE_TYPES[kind]

        row = layout.row()
        if showing_all:
            self.draw_all_rows(row.column(), ssd)
        else:
            row.template_list(shape.list_type, '', ssd, shape.collection, ssd, shape.index_prop, rows=4, maxrows=10)
        side = row.column(align=True)
        if showing_all:
            side.menu('SUB_MT_swing_shape_add', text='', icon='ADD')
        else:
            side.operator('sub.swing_shape_add_start', text='', icon='ADD').shape_type = kind
        side.operator(shape.remove_op, text='', icon='REMOVE')

        if ssd.shape_draft.adding != 'NONE':
            self.draw_add_form(layout, context, ssd)
            return

        items = getattr(ssd, shape.collection)
        index = getattr(ssd, shape.index_prop)
        if not 0 <= index < len(items):
            return
        layout.separator()
        self.draw_shape_fields(layout, context, kind, items[index])
        if kind != 'CONNECTION':
            users = shape_users(ssd, kind, index)
            layout.label(text=f'Used by {users} swing bone{"" if users == 1 else "s"}', icon='LINKED')
            self.draw_attach_buttons(layout, ssd, kind, index)

    @staticmethod
    def draw_add_form(layout: UILayout, context, ssd):
        draft = ssd.shape_draft
        kind = draft.adding
        shape = SHAPE_TYPES[kind]
        box = layout.box()
        box.label(text=f'New {shape.label}', icon=shape.icon)
        col = box.column()
        col.use_property_split = True
        col.use_property_decorate = False
        fields = [draft_field for draft_field, _op_field in DRAFT_OP_FIELDS[kind]]
        for field in fields:
            if field in {'ny', 'nz'}:
                continue
            if field == 'nx':
                row = col.row(align=True, heading='Normal')
                for axis in ('nx', 'ny', 'nz'):
                    row.prop(draft, axis)
            elif field.endswith('bone_name'):
                # Connections only join swing bones, like the old dialog.
                owner, collection = (ssd, 'armature_swing_bones') if kind == 'CONNECTION' else (context.object.data, 'bones')
                col.prop_search(draft, field, owner, collection, icon='BONE_DATA')
            else:
                col.prop(draft, field)

        if kind != 'CONNECTION' and len(ssd.swing_bone_chains) > 0:
            chain = ssd.swing_bone_chains[ssd.active_swing_bone_chain_index]
            if len(chain.swing_bones) > 0:
                bone = chain.swing_bones[chain.active_swing_bone_index]
                attach = col.column(heading='Collide With')
                attach.prop(draft, 'attach_to_bone', text=bone.name)
                attach.prop(draft, 'attach_to_chain', text=f'Whole Chain {chain.name}')

        row = box.row()
        add = row.row()
        add.enabled = all(getattr(draft, field) for field in fields if field.endswith('bone_name'))
        add.operator('sub.swing_shape_add_confirm', text=f'Add {shape.label}', icon='CHECKMARK')
        row.operator('sub.swing_shape_add_cancel', text='Cancel', icon='X')

    @staticmethod
    def draw_attach_buttons(layout: UILayout, ssd, kind: str, index: int):
        if len(ssd.swing_bone_chains) == 0:
            return
        chain = ssd.swing_bone_chains[ssd.active_swing_bone_chain_index]
        if len(chain.swing_bones) == 0:
            return
        bone = chain.swing_bones[chain.active_swing_bone_index]

        def collides(swing_bone) -> bool:
            return any(c.collision_type == kind and c.collision_index == index for c in swing_bone.collisions)

        buttons = []
        if not collides(bone):
            buttons.append((f'Collide with {bone.name}', False))
        if not all(collides(b) for b in chain.swing_bones):
            buttons.append((f'Collide with chain {chain.name}', True))
        if not buttons:
            return
        col = layout.column(align=True)
        for text, whole_chain in buttons:
            op = col.operator('sub.swing_shape_attach', text=text, icon='ADD')
            op.shape_type = kind
            op.index = index
            op.whole_chain = whole_chain

    @staticmethod
    def draw_all_rows(layout: UILayout, ssd):
        col = layout.box().column(align=True)
        empty = True
        for kind, shape in SHAPE_TYPES.items():
            active_index = getattr(ssd, shape.index_prop)
            for index, item in enumerate(getattr(ssd, shape.collection)):
                empty = False
                name, bone = shape_label(kind, item)
                selected = kind == ssd.active_shape_type and index == active_index
                split = col.split(factor=.5, align=True)
                # A LEFT-aligned row is the only way to left-align a button's text.
                left = split.row()
                left.alignment = 'LEFT'
                op = left.operator('sub.swing_shape_select', text=name, icon=shape.icon,
                                   emboss=selected, depress=selected)
                op.shape_type = kind
                op.index = index
                right = split.row()
                right.alignment = 'RIGHT'
                right.label(text=bone)
        if empty:
            col.label(text='No collision shapes yet. Add one with +.')

    @staticmethod
    def draw_shape_fields(layout: UILayout, context, kind: str, item):
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        for prop, text, is_bone in SHAPE_FIELDS[kind]:
            if is_bone:
                col.prop_search(item, prop, context.object.data, 'bones', text=text, icon='BONE_DATA')
            else:
                col.prop(item, prop, text=text)
            if kind == 'PLANE' and prop == 'bone_name':
                row = col.row(align=True, heading='Normal')
                for axis in ('nx', 'ny', 'nz'):
                    row.prop(item, axis, text=axis[1].upper())


class SUB_MT_swing_shape_add(Menu):
    bl_label = "Add Collision Shape"

    def draw(self, context):
        for kind, shape in SHAPE_TYPES.items():
            self.layout.operator('sub.swing_shape_add_start', text=shape.label, icon=shape.icon).shape_type = kind


class SUB_UL_swing_data_spheres(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'SPHERE', item)


class SUB_UL_swing_data_ovals(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'OVAL', item)


class SUB_UL_swing_data_ellipsoids(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'ELLIPSOID', item)


class SUB_UL_swing_data_capsules(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'CAPSULE', item)


class SUB_UL_swing_data_planes(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'PLANE', item)


class SUB_UL_swing_data_connections(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        draw_shape_item(layout, 'CONNECTION', item)
