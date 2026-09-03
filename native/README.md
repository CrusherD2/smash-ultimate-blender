# Smash Viewport native plugin

Blender's Python GPU overlay cannot match SSBH Editor. This crate wraps
`ssbh_wgpu` (the same renderer SSBH Editor uses), renders offscreen, and the
addon blits that image into a 3D View set to **Rendered**.

Solid / Material shading stay Workbench / EEVEE.

Windows builds ship `native/bin/ssbh_blender_preview.dll` so Smash Viewport
works after an addon update. Rebuild and replace that file when the crate
changes.

## Build

1. Put `ssbh_wgpu` at `native/vendor/ssbh_wgpu`.
   - Junction or clone [ScanMountGoat/ssbh_wgpu](https://github.com/ScanMountGoat/ssbh_wgpu), or
   - Junction your SSBH Editor `vendor/ssbh_wgpu` folder (keeps lighting in lockstep with the editor you already use).
2. Nightly or recent stable Rust (wgpu 29).
3. From `native/ssbh_blender_preview/`:

```
cargo build --release
```

Copy the result over the shipped plugin:

- Windows: `ssbh_blender_preview/target/release/ssbh_blender_preview.dll`
- Destination: `native/bin/ssbh_blender_preview.dll`

The addon searches `native/bin/` then `target/release/` then `target/debug/`.

Do not commit `vendor/`, `target/`, or `*.reload.dll`. Do not put a
machine-specific path in `Cargo.toml`.
