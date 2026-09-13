# Custom animation rig components

Open **Ultimate → Animation Tools → Make Custom Components**, directly below
**Create Animation Rig**. This opens a separate Blender window that stays open
when you work in the main viewport. Resize it like any Blender window. Its
Properties search focuses the Custom Rig Components panel.

The editor follows three steps. Use **+** to add a component, or select an existing
entry in the list. **Load** and **Save Preset** stay at the top.

1. **Bones:** choose the type and name, then use selected bones or search by name.
   Once the assignments are valid, choose **Next: Create Controls**.
2. **Controls:** choose the default shape and essential movement settings.
   **Advanced Placement & Behavior** contains offsets, orientation, parenting,
   ranges and bone weights. **Selected Control Appearance** edits individual
   handles. Both sections start closed. **Build Controls & Continue** builds only
   this component, so unfinished entries do not block it.
3. **Animate:** select the control in the viewport or create facial poses. Pose
   capture buttons appear while editing a pose; management/reset options stay
   under **Manage Saved Poses**.

Bone eyes, eyelids and mouth expressions use captured poses:

1. Build facial controls with the assigned bones in their neutral position. That
   becomes the baseline; **Manage Saved Poses** lets you recapture it later.
2. Click **Create / Replace Pose**, pose the original bones, and capture an expression.
   **Cancel Pose Edit** restores the pose from before editing.
3. Animate the generated sliders between 0 (neutral) and 1 (captured pose).
   Captures include translation, rotation and scale. Expressions can be blended.
   Each component supports up to 32 named expressions; add components as needed.

For **Eyelids**, capture one eye closed with the other neutral, then do the reverse.
Each capture gets a slider. **Both Eyelids** combines both captures, clamped so
using a shared and individual slider together does not double the closure.
For **Mouth Expressions**, capture names such as Smile, Frown and Open; each gets
an independent slider. **Expression Strength** fades the complete mouth pose in
and out. These are bone poses, so no mesh shape keys are required.

For **Bone Eyes (Captured Poses)**, the visible control is a look pad.
**Show Rotation Controller** optionally exposes the rear orbit pivot. Position the 3D cursor
at the desired pivot and enable **Place Eye Pivot at 3D Cursor** before the first
build, or use the automatic offset behind the eyes. Rotate the optional pivot to orbit
the eye bones. To author orbital limits, use **Create Orbit Limit**, rotate the rear
pivot, then save **Left**, **Right**, **Up** or **Down**. The separate look pad
interpolates these limits and preserves the orbital arc. **Create / Replace Pose** also lets
you capture additional eye-bone offsets for those directions. Existing keyed
controls retain their rest placement on rebuild.

Captures are saved with the preset when **Save Preset When Building** is enabled.
Review and recapture offsets when reusing a preset on differently proportioned
characters. The facial system uses native Blender constraints and drivers, with
no additional Python frame handler.

**Look Target** is a separate component: assigned bones track a movable target,
without requiring captured poses. Choose the bone forward axis for your model.

**Movement Plane** selects side/up-down (XZ, the default for new eye components),
side/front-back (XY), or front/up-down (YZ). **Control Position Offset** and
**Control Orientation** change the actual controls when you Build / Update,
including their movement axes and handle origin. They are stored in the preset.
Existing presets retain their earlier plane until you change it.

**Isolated Bones** creates an independent handle for each assigned bone. Use it
for feet without leg chains, floating hands, or props: moving Hip, Trans, or other
parent bones leaves them in place. Move or rotate the handles to animate them.
The original skeleton hierarchy is retained; no IK solver is created. Moving the
armature object itself still moves the rig as a whole.

The collapsible **Selected Control Appearance** section edits default Animation Rig controls as well as
custom controls: circle, square, slider, box, diamond, sphere, crosshair, arrow,
foot and knob. Choose a shape and apply it to selected controls. Custom widget
objects, nonuniform scale, offset and rotation are also available; click
**Save Control Appearance** to save explicitly after editing these fields. To turn a
widget offset/rotation into a functional change to a generated controller,
choose **Apply Offset / Rotation to Actual Control**; it resets the widget offset
and moves/rotates the bone's actual control frame. Existing local animation keys
then follow the new frame. **Make Widget Mesh
Editable** copies the active control's mesh and enters Edit Mode. Edit its
vertices in the main viewport, then click **Finish Widget Editing**. Other controls
keep their own geometry. **Auto-save Appearance** is enabled by default. Shape choices, size, offsets,
rotation, functional adjustments, and edited widget geometry are written to the
current preset. Applying a shape or finishing a mesh edit saves immediately;
direct field edits are saved after a short debounce. **Save Preset** also captures
current appearance changes. Turn off auto-save to save manually.

Preset files contain the widget geometry, so loading and rebuilding on another
armature does not depend on widget objects from the original blend. Matching
bone names receive their saved individual appearance; old presets still load.
Individual appearance overrides take precedence over the component default shape.

Jaw rotation, tail/tentacle curls, wing/feather fans and general rotation sliders
remain available. Thumb opposition belongs at the thumb base; finger sliders
detect palmward curl axes and use a smaller thumb flexion range.

For custom IK, select the chain start and end (or the full chain), then choose
**Use Selected Chain**. The editor proposes a bend joint, which can be changed.
The path preview includes intermediate bones. Existing chains cannot overlap.
Adding another chain does not rematch or key previously created IK controls.
The simpler Custom IK section also has selection-based detection and active-bone
pickers. The Animation Rig recognizes the extra foot-roll, toe and custom IK
controls for styling, selection tools and switching. LegC and ClavicleC are hidden
and unselectable when building or restoring the Animation Rig.

With viewport gizmos enabled, selecting an IK controller shows a **Switch to FK**
icon beside it. When that chain has floor contact set up, **Plant** and **Release**
icons appear too. Hover for their labels. These use the same keyed operators as
the IK panel. **IK Buttons in Viewport** in the components window disables them.

Presets are JSON data, stored through Blender's user scripts directory:

```text
%APPDATA%\Blender Foundation\Blender\X.X\scripts\presets\smash_custom_components\
```

**Load Preset** restores editable definitions; review bone assignments before
building on another character. Updating a built component preserves controller
keys and rest placement. To change an existing controller's parent or change an
IK chain's membership, remove that built component first. The list's minus button
only removes an entry from the preset editor.

**Create Animation Rig ? Custom Components** reveals a component-preset selector.
The selected preset is built along with the regular rig. Bone names must match
the target skeleton.

**Rig Extras ? Custom Components** has **Bake & Remove** and **Remove** actions.
These actions stay outside the component editor. Baking samples the scene frame range
onto the original bones before removing controllers. **Bake and Remove Rig**
includes a Custom Components checkbox; plain **Remove Animation Rig** removes
custom components without baking them. Preset files remain available for reuse.

NUANMB export automatically samples the evaluated skeleton when a rig or pose
constraints/drivers are present. It includes IK, fingers, bone eyes, look targets, isolated bones, custom wing
mechanisms, other custom components, and the existing EyeLook material controls
when material export is enabled. It writes temporary object/material actions and
restores the working actions afterward. Controller and mechanism bones are omitted.
Raw animation export continues to preserve editable source keys.

Validation is available in `tests/test_face_components_blender.py`,
`tests/test_custom_components_blender.py`,
`tests/test_reference_rig_export_blender.py`, and the existing IK, floor-contact,
and animation-workflow suites. Run with Blender's `--background --factory-startup
--python-exit-code 1 --python` options. Set `SUB_REFERENCE_BLEND` to supply a local
reference rig for the reference export test and playback profiler. No reference
blend is saved by those checks.

`tests/test_components_window_blender.py` runs without `--background` in an
isolated factory Blender session to check the real window and gizmo drawing.

`tests/test_components_lifecycle_blender.py` checks functional placement, isolated
feet, live export, component baking, and rig creation from a component preset.

`tests/test_component_appearance_presets_blender.py` verifies appearance autosave,
portable edited meshes, functional offsets, and the progressive editor pages.
