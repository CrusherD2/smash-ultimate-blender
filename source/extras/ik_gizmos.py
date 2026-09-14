"""Clickable wireframe buttons inset into the selected IK control box."""

import bpy
from mathutils import Matrix, Vector, Euler
import blf
from bpy_extras.view3d_utils import location_3d_to_region_2d
from .control_appearance import controls


def selected(context):
    obj = context.object
    pb = context.active_pose_bone
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE' or not pb:
        return None
    from .create_animation_rig import armature_has_animation_rig
    from ..blender_compat import is_pose_bone_selected
    if not armature_has_animation_rig(obj) or not is_pose_bone_selected(pb) or pb.bone.hide:
        return None
    kind = pb.bone.get('sub_ik_control_kind')
    target = pb.bone.get('sub_ik_control_target')
    info = (kind, target, '', '') if kind and target else controls(obj).get(pb.name)
    return (obj, pb, info) if info else None


def button_layout(context):
    found = selected(context)
    if not found or not context.region or context.region.type != 'WINDOW':
        return []
    obj, pb, info = found
    if not pb.custom_shape or pb.name != info[1]:
        return []
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    pose = evaluated.pose.bones[pb.name]
    shape_pose = evaluated.pose.bones.get(pb.custom_shape_transform.name) if pb.custom_shape_transform else pose
    scale = Vector(pb.custom_shape_scale_xyz)
    if pb.use_custom_shape_bone_size:
        scale *= pb.length
    matrix = (evaluated.matrix_world @ shape_pose.matrix
              @ Matrix.Translation(pb.custom_shape_translation)
              @ Euler(pb.custom_shape_rotation_euler).to_matrix().to_4x4()
              @ Matrix.Diagonal((*scale, 1)))
    bounds = [Vector(v) for v in pb.custom_shape.bound_box]
    low = Vector(tuple(min(v[i] for v in bounds) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in bounds) for i in range(3)))
    view = context.space_data.region_3d
    camera = view.view_matrix.inverted().translation
    faces = []
    for axis in range(3):
        u, v = [i for i in range(3) if i != axis]
        for side in (0, 1):
            points = []
            for x, y in ((0,0),(1,0),(1,1),(0,1)):
                p = low.copy()
                p[axis] = (low,high)[side][axis]
                p[u],p[v] = (low,high)[x][u],(low,high)[y][v]
                points.append(matrix @ p)
            normal = Vector((0,0,0))
            normal[axis] = 1 if side else -1
            normal = matrix.to_3x3().inverted_safe().transposed() @ normal
            toward = camera-sum(points,Vector())/4 if view.is_perspective else view.view_rotation @ Vector((0,0,1))
            if normal.dot(toward) <= 0:
                continue
            quad = [location_3d_to_region_2d(context.region, view, p) for p in points]
            if any(p is None for p in quad):
                continue
            area = abs(sum(quad[i].x*quad[(i+1)%4].y-quad[(i+1)%4].x*quad[i].y for i in range(4)))
            faces.append((area,quad))
    if not faces:
        return []
    _, quad = max(faces,key=lambda entry:entry[0])
    # Use the lower edge of the visible box face as the button rail. All
    # positions are on that face, so they rotate and scale with the widget.
    edge = min(range(4),key=lambda i:(quad[i].y+quad[(i+1)%4].y)/2)
    a,b,c,d = [quad[(edge+i)%4] for i in range(4)]
    if a.x>b.x:
        a,b,c,d=b,a,d,c
    def point(u,v):
        return a*(1-u)*(1-v)+b*u*(1-v)+c*u*v+d*(1-u)*v
    contact = any(l.control == info[1] for l in obj.sub_floor_contact.limbs)
    indexes = [0,1,2] if contact else [2]
    result=[]
    for slot,index in enumerate(indexes):
        center=.5+(slot-(len(indexes)-1)/2)*.29
        corners=[point(center+u,v) for u,v in ((-.11,.08),(.11,.08),(.11,.23),(-.11,.23))]
        # Tiny/edge-on boxes cannot offer a reliable click target.
        if (corners[1]-corners[0]).length<12 or (corners[3]-corners[0]).length<6:
            continue
        result.append((index,corners,point(center,.28)))
    return result


def draw_labels():
    context=bpy.context
    if not getattr(context.scene,'sub_ik_view_buttons',False):
        return
    if not context.space_data or context.space_data.type!='VIEW_3D' or not context.space_data.show_gizmo:
        return
    blf.color(0,.55,.85,1,1)
    blf.enable(0,blf.SHADOW)
    blf.shadow(0,3,0,0,0,.8)
    for index,corners,position in button_layout(context):
        label=('Plant','Release','Switch FK')[index]
        blf.size(0,11*context.preferences.system.ui_scale)
        width,_=blf.dimensions(0,label)
        available=(corners[1]-corners[0]).length*1.15
        if width>available:
            blf.size(0,max(7,11*context.preferences.system.ui_scale*available/width))
        width,_=blf.dimensions(0,label)
        blf.position(0,position.x-width/2,position.y,0)
        blf.draw(0,label)
    blf.disable(0,blf.SHADOW)


class SUB_GT_ik_box_button(bpy.types.Gizmo):
    bl_idname='SUB_GT_ik_box_button'

    def setup(self):
        self.corners=[]
        self.use_draw_scale=False
        self.use_draw_modal=False

    def draw(self,context):
        if not self.corners:
            return
        vertices=[(p.x,p.y,0) for p in self.corners]
        outline=[vertices[i] for edge in ((0,1),(1,2),(2,3),(3,0)) for i in edge]
        self.draw_custom_shape(self.new_custom_shape('LINES',outline))
        if self.is_highlight:
            fill=[vertices[i] for i in (0,1,2,0,2,3)]
            self.draw_custom_shape(self.new_custom_shape('TRIS',fill))

    def test_select(self,context,location):
        if len(self.corners)!=4:
            return -1
        p=Vector(location)
        crosses=[]
        for i,a in enumerate(self.corners):
            b=self.corners[(i+1)%4]
            crosses.append((b.x-a.x)*(p.y-a.y)-(b.y-a.y)*(p.x-a.x))
        return 0 if all(v>=0 for v in crosses) or all(v<=0 for v in crosses) else -1


class SUB_OP_ik_view_button(bpy.types.Operator):
    bl_idname = 'sub.ik_view_button'
    bl_label = 'Selected IK Control'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(
        items=[
            ('PLANT', 'Plant', ''),
            ('RELEASE', 'Release', ''),
            ('FK', 'Switch to FK', ''),
        ]
    )

    @classmethod
    def description(cls, context, properties):
        return {
            'PLANT': 'Plant this IK control and key the contact',
            'RELEASE': 'Release this IK control and key the contact',
            'FK': 'Switch this limb group to FK and key the switch',
        }[properties.action]

    def execute(self, context):
        found = selected(context)
        if not found:
            return {'CANCELLED'}
        obj, pb, (kind, target, shape, tool) = found
        if self.action == 'FK':
            return bpy.ops.sub.anim_rig_toggle_ik_fk(
                limbs=kind, set_enabled=True, enable_ik=False
            )
        return bpy.ops.sub.floor_contact(action=self.action, control=target)


class SUB_GGT_ik_buttons(bpy.types.GizmoGroup):
    bl_idname = 'SUB_GGT_ik_buttons'
    bl_label = 'IK Actions'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.sub_ik_view_buttons and selected(context))

    def setup(self, context):
        self.buttons = []
        for action in ('PLANT', 'RELEASE', 'FK'):
            gizmo = self.gizmos.new('SUB_GT_ik_box_button')
            gizmo.scale_basis = 1
            gizmo.line_width = 2
            gizmo.color = (0.35, 0.75, 1)
            gizmo.alpha = 0.85
            gizmo.color_highlight = (0.3, 0.65, 1)
            gizmo.alpha_highlight = 1
            gizmo.target_set_operator('sub.ik_view_button').action = action
            self.buttons.append(gizmo)

    def draw_prepare(self, context):
        positions = {index:corners for index,corners,label in button_layout(context)}
        for index,gizmo in enumerate(self.buttons):
            gizmo.hide = index not in positions
            gizmo.corners = positions.get(index,[])
            gizmo.matrix_basis = Matrix.Identity(4)


_label_handler = None


def register():
    global _label_handler
    bpy.types.Scene.sub_ik_view_buttons = bpy.props.BoolProperty(
        name='IK Buttons in Viewport', default=True
    )
    bpy.utils.register_class(SUB_OP_ik_view_button)
    bpy.utils.register_class(SUB_GT_ik_box_button)
    bpy.utils.register_class(SUB_GGT_ik_buttons)
    _label_handler = bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _label_handler
    if _label_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_label_handler, 'WINDOW')
        _label_handler = None
    bpy.utils.unregister_class(SUB_GGT_ik_buttons)
    bpy.utils.unregister_class(SUB_GT_ik_box_button)
    bpy.utils.unregister_class(SUB_OP_ik_view_button)
    del bpy.types.Scene.sub_ik_view_buttons
