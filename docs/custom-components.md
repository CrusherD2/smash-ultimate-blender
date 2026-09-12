# Custom animation rig components

Open **Ultimate → Animation Tools → Make Custom Components**, directly below
**Create Animation Rig**. The floating editor retains its configuration when you
close it to select bones in the viewport.

1. Add an entry with **+**, choose its component type, and give it a name.
2. Assign bones with the search fields or **Add Selected Bones**. Lists scroll,
   so a preset can contain multiple components and many bone assignments.
3. Choose the parent, axes, range, and per-bone weights. Negative weights reverse
   individual bones. **Distribute Weights** creates a curl gradient or a signed fan.
4. Choose **Build / Update Components**. The default also saves the preset.
5. Use **Select Control** to find the generated control. The trash button removes
   only that built component; its definition remains available to rebuild.

The component types are bone-based eye look targets, custom IK, jaw rotation,
eyelid/blink rotation, tail/tentacle curls, wing/feather fans, and general rotation
sliders. Eye targets move freely. Other component sliders move on local Y.
Thumb opposition belongs at the thumb base; the finger slider repair now detects
palmward curl axes and uses a smaller thumb flexion range.

For custom IK, select the chain start and end (or the full chain), then choose
**Use Selected Chain**. The editor proposes a bend joint, which can be changed.
The path preview includes intermediate bones. Existing chains cannot overlap.
Adding another chain does not rematch or key previously created IK controls.
The simpler Custom IK section also has selection-based detection and active-bone
pickers.

Presets are JSON data, stored through Blender's user scripts directory:

```text
%APPDATA%\Blender Foundation\Blender\X.X\scripts\presets\smash_custom_components\
```

**Load Preset** restores editable definitions; review bone assignments before
building on another character. Updating a built component preserves controller
keys and rest placement. To change an existing controller's parent or change an
IK chain's membership, remove that built component first. The list's minus button
only removes an entry from the preset editor.

NUANMB export automatically samples the evaluated skeleton when a rig or pose
constraints/drivers are present. It includes IK, fingers, bone eyes, custom wing
mechanisms, other custom components, and the existing EyeLook material controls
when material export is enabled. It writes temporary object/material actions and
restores the working actions afterward. Controller and mechanism bones are omitted.
Raw animation export continues to preserve editable source keys.

Validation is available in `tests/test_custom_components_blender.py`,
`tests/test_reference_rig_export_blender.py`, and the existing IK, floor-contact,
and animation-workflow suites. Run with Blender's `--background --factory-startup
--python-exit-code 1 --python` options. Set `SUB_REFERENCE_BLEND` to supply a local
reference rig for the reference export test and playback profiler. No reference
blend is saved by those checks.
