"""Run in interactive factory Blender; verifies the compact sidebar and IK buttons."""

from pathlib import Path

fixture = Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8'), str(fixture), 'exec'))
import traceback, os

initial_windows = len(bpy.context.window_manager.windows)
bpy.context.preferences.view.show_splash = False
bpy.ops.wm.save_userpref()
compat = importlib.import_module(MODULE + '.source.blender_compat')
obj.data[rig.ARMATURE_FLAG] = True
cc.custom_ik.create_from_settings(
    bpy.context,
    obj,
    SimpleNamespace(
        name='UI Test', root='Tail0', middle='Tail2', end='Tail3', kind='ARMS'
    ),
)
target = next(ik.custom_jobs(obj))[2]
floor.setup_limb(bpy.context, obj, target, 'ARMS')
for pb in obj.pose.bones:
    compat.set_pose_bone_select(pb, False)
compat.set_pose_bone_select(obj.pose.bones[target], True)
obj.data.bones.active = obj.data.bones[target]
# Show the selected target and trigger real GizmoGroup setup/draw.
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.region_3d.view_location = obj.pose.bones[target].head
area.spaces.active.region_3d.view_distance = 12
area.spaces.active.show_gizmo = True
area.spaces.active.show_region_ui = True
# Display the real sidebar panel in the compact default region.
panel_type = bpy.types.Panel.bl_rna_get_subclass_py('SUB_PT_animation_tools')
bpy.utils.unregister_class(panel_type)
panel_type.bl_options = set()
panel_type.bl_category = 'Item'
bpy.utils.register_class(panel_type)
for panel_id in ('SUB_PT_import_model','SUB_PT_export_model','SUB_PT_import_anim','SUB_PT_export_anim'):
    panel = bpy.types.Panel.bl_rna_get_subclass_py(panel_id)
    if panel:
        panel.bl_options = {'DEFAULT_CLOSED'}

gg = importlib.import_module(MODULE + '.source.extras.ik_gizmos')
gizmo_seen = []
original_draw = gg.SUB_GGT_ik_buttons.draw_prepare


def checked_draw(self, context):
    original_draw(self, context)
    gizmo_seen.append(True)


gg.SUB_GGT_ik_buttons.draw_prepare = checked_draw


def finish():
    try:
        appearance_payload = json.loads(
            (
                cc.preset_dir() / (bpy.path.clean_name(editor.preset_name) + '.json')
            ).read_text(encoding='utf-8')
        )
        assert (
            abs(appearance_payload['appearances'][target]['offset'][0] - 0.123) < 1e-6
        ), 'RNA appearance edit did not auto-save'
        assert len(bpy.context.window_manager.windows) == initial_windows
        assert editor.is_open
        with bpy.context.temp_override(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
            for pb in obj.pose.bones:
                compat.set_pose_bone_select(pb, pb.name == target)
            obj.data.bones.active = obj.data.bones[target]
            assert bpy.ops.sub.control_shape(action='EDIT') == {'FINISHED'}
            panel = importlib.import_module(MODULE + '.source.extras.misc_panel').SUB_PT_animation_tools
            assert panel.poll(bpy.context), 'Sidebar disappeared during widget editing'
            assert bpy.ops.sub.control_shape(action='FINISH') == {'FINISHED'}
            assert bpy.context.view_layer.objects.active == obj and obj.mode == 'POSE'
        assert gizmo_seen, 'Viewport buttons never drew'
        with bpy.context.temp_override(
            window=window,
            area=area,
            region=next(r for r in area.regions if r.type == 'WINDOW'),
        ):
            bpy.ops.screen.screenshot(
                filepath=os.path.join(os.environ['TEMP'], 'sub_ik_buttons.png')
            )
            assert bpy.ops.sub.ik_view_button(action='PLANT') == {'FINISHED'}
            limb = next(l for l in obj.sub_floor_contact.limbs if l.control == target)
            assert limb.planted
            assert bpy.ops.sub.ik_view_button(action='RELEASE') == {'FINISHED'}
            assert not limb.planted
            assert bpy.ops.sub.ik_view_button(action='FK') == {'FINISHED'}
            assert obj.data.sub_use_ik_arms == 0
        obj.data[rig.ARMATURE_FLAG] = False
        assert not gg.SUB_GGT_ik_buttons.poll(bpy.context), 'Standalone IK displayed buttons'
        obj.data[rig.ARMATURE_FLAG] = True
        assert bpy.ops.sub.custom_components() == {'FINISHED'}
        assert not editor.is_open
        print('REAL COMPONENT SIDEBAR AND GIZMO DRAW PASSED', flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()


step_images = iter(('BONES', 'CONTROLS', 'ANIMATE'))
current_step = 'BONES'


def capture_step():
    global current_step
    with bpy.context.temp_override(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
        bpy.ops.screen.screenshot(filepath=os.path.join(os.environ['TEMP'], 'sub_components_' + current_step + '.png'))
    try:
        current_step = next(step_images)
    except StopIteration:
        return None
    editor.page = current_step
    area.tag_redraw()
    return 1.0


def start():
    try:
        with bpy.context.temp_override(
            window=window,
            area=area,
            region=next(r for r in area.regions if r.type == 'WINDOW'),
        ):
            assert bpy.ops.sub.custom_components('INVOKE_DEFAULT') == {'FINISHED'}
        obj.pose.bones[target].custom_shape_translation.x = 0.123
        bpy.msgbus.publish_rna(key=(bpy.types.PoseBone, 'custom_shape_translation'))
        editor.page = 'BONES'
        next(step_images)
        bpy.app.timers.register(capture_step, first_interval=1)
        bpy.app.timers.register(finish, first_interval=5)
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=2)
