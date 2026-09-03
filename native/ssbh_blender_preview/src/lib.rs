//! Offscreen Smash Ultimate renderer for Blender.
//!
//! Loads the same model folder SSBH Editor uses (`ssbh_wgpu`) and writes RGBA
//! frames for a Python `RenderEngine` to blit. Pose comes from Blender bone
//! world matrices, not from converting Blender meshes.

use futures::executor::block_on;
use glam::{Mat4, Vec4};
use ssbh_wgpu::{
    load_render_models, CameraTransforms, ModelFolder, ModelRenderOptions, RenderModel,
    SharedRenderData, SsbhRenderer, REQUIRED_FEATURES, REQUIRED_LIMITS,
};
#[cfg(windows)]
mod gpu_share;

use image::{
    Delay, Frame, RgbaImage,
    codecs::gif::{GifEncoder, Repeat},
};
use std::{
    ffi::{c_char, CStr, CString},
    fs::File,
    io::BufWriter,
    path::{Path, PathBuf},
    ptr,
    sync::mpsc::{self, Receiver, TryRecvError},
    sync::Mutex,
};
use wgpu::{
    BufferUsages, DeviceDescriptor, Extent3d, InstanceDescriptor, PowerPreference,
    RequestAdapterOptions, TextureDescriptor, TextureDimension, TextureFormat, TextureUsages,
};

// Same format SSBH Editor / ssbh_wgpu_test use for screenshots.
const SURFACE_FORMAT: TextureFormat = TextureFormat::Rgba8UnormSrgb;
const MIN_SIZE: u32 = 8;
const MAX_SIZE: u32 = 4096;

static LAST_ERROR: Mutex<Option<CString>> = Mutex::new(None);

struct OutputTargets {
    texture: wgpu::Texture,
    view: wgpu::TextureView,
    readbacks: [wgpu::Buffer; 2],
    padded_bpr: u32,
}

#[cfg(windows)]
struct UnormBlit {
    pipeline: wgpu::RenderPipeline,
    bind_layout: wgpu::BindGroupLayout,
}

pub struct Preview {
    models: Vec<ModelFolder>,
    render_models: Vec<RenderModel>,
    renderer: SsbhRenderer,
    shared: SharedRenderData,
    output: OutputTargets,
    width: u32,
    height: u32,
    scale: f32,
    loaded_path: String,
    queue: wgpu::Queue,
    device: wgpu::Device,
    adapter: wgpu::Adapter,
    slots: [Option<Receiver<Result<(), wgpu::BufferAsyncError>>>; 2],
    cached: Vec<u8>,
    #[cfg(windows)]
    gpu_share: Option<gpu_share::GpuShare>,
    #[cfg(windows)]
    gpu_tex: Option<wgpu::Texture>,
    #[cfg(windows)]
    gpu_view: Option<wgpu::TextureView>,
    #[cfg(windows)]
    unorm_blit: Option<UnormBlit>,
    #[cfg(windows)]
    gpu_blit_bg: Option<wgpu::BindGroup>,
    lighting: Option<ssbh_data::anim_data::AnimData>,
    lighting_frame: f32,
    lighting_uploaded_frame: Option<f32>,
    clear_rgba: [f64; 4],
}

fn set_error(msg: impl AsRef<str>) {
    let text = msg.as_ref().replace('\0', "");
    if let Ok(c) = CString::new(text) {
        if let Ok(mut slot) = LAST_ERROR.lock() {
            *slot = Some(c);
        }
    }
}

fn clear_error() {
    if let Ok(mut slot) = LAST_ERROR.lock() {
        *slot = None;
    }
}

fn padded_bytes_per_row(width: u32) -> u32 {
    let unpadded = width.saturating_mul(4);
    let align = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    unpadded.div_ceil(align) * align
}

fn clamp_size(value: u32) -> u32 {
    value.clamp(MIN_SIZE, MAX_SIZE)
}

fn create_output(device: &wgpu::Device, width: u32, height: u32) -> OutputTargets {
    let width = clamp_size(width);
    let height = clamp_size(height);
    let padded_bpr = padded_bytes_per_row(width);
    let texture = device.create_texture(&TextureDescriptor {
        label: Some("ssbh_blender_preview_color"),
        size: Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: TextureDimension::D2,
        format: SURFACE_FORMAT,
        usage: TextureUsages::RENDER_ATTACHMENT
            | TextureUsages::COPY_SRC
            | TextureUsages::TEXTURE_BINDING,
        view_formats: &[],
    });
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    let buffer_size = padded_bpr as u64 * height as u64;
    let make_readback = |label| {
        device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label),
            size: buffer_size,
            usage: BufferUsages::COPY_DST | BufferUsages::MAP_READ,
            mapped_at_creation: false,
        })
    };
    OutputTargets {
        texture,
        view,
        readbacks: [
            make_readback("ssbh_blender_preview_readback_0"),
            make_readback("ssbh_blender_preview_readback_1"),
        ],
        padded_bpr,
    }
}

fn mat4_from_cols(ptr: *const f32) -> Mat4 {
    let slice = unsafe { std::slice::from_raw_parts(ptr, 16) };
    let mut cols = [0.0f32; 16];
    cols.copy_from_slice(slice);
    Mat4::from_cols_array(&cols)
}

#[cfg(windows)]
fn create_unorm_blit(device: &wgpu::Device, dst_format: TextureFormat) -> UnormBlit {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("ssbh_unorm_blit"),
        source: wgpu::ShaderSource::Wgsl(
            r#"
@group(0) @binding(0) var src: texture_2d<f32>;

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    let uv = vec2<f32>(f32((vi << 1u) & 2u), f32(vi & 2u));
    return vec4<f32>(uv * 2.0 - 1.0, 0.0, 1.0);
}

@fragment
fn fs(@builtin(position) pos: vec4<f32>) -> @location(0) vec4<f32> {
    let t = textureLoad(src, vec2<i32>(i32(pos.x), i32(pos.y)), 0);
    let lum = max(t.r, max(t.g, t.b));
    if t.a < 0.05 || lum < 0.003 {
        return vec4<f32>(0.0);
    }
    let rgb = t.rgb / max(t.a, 0.05);
    return vec4<f32>(rgb, 1.0);
}
"#
            .into(),
        ),
    });
    let bind_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("ssbh_unorm_blit_layout"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: false },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
            count: None,
        }],
    });
    let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("ssbh_unorm_blit_pl"),
        bind_group_layouts: &[Some(&bind_layout)],
        immediate_size: 0,
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("ssbh_unorm_blit_pipe"),
        layout: Some(&pipeline_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs"),
            compilation_options: Default::default(),
            buffers: &[],
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs"),
            compilation_options: Default::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format: dst_format,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview_mask: None,
        cache: None,
    });
    UnormBlit {
        pipeline,
        bind_layout,
    }
}

impl Preview {
    fn new() -> Result<Self, String> {
        // Blender's viewport is OpenGL (nvoglv64). Probing Vulkan/GL from this
        // process crashes the NVIDIA driver. Stay on DX12 on Windows.
        let backends = if cfg!(windows) {
            wgpu::Backends::DX12
        } else {
            wgpu::Backends::VULKAN
        };
        let instance = wgpu::Instance::new(InstanceDescriptor {
            backends,
            ..InstanceDescriptor::new_without_display_handle()
        });
        let adapter = block_on(instance.request_adapter(&RequestAdapterOptions {
            power_preference: PowerPreference::HighPerformance,
            ..Default::default()
        }))
        .map_err(|e| format!("No GPU adapter for ssbh_wgpu: {e}"))?;

        let (device, queue) = block_on(adapter.request_device(&DeviceDescriptor {
            required_features: REQUIRED_FEATURES,
            required_limits: REQUIRED_LIMITS,
            ..Default::default()
        }))
        .map_err(|e| format!("request_device failed: {e}"))?;

        let width = 64;
        let height = 64;
        let scale = 1.0;
        let shared = SharedRenderData::new(&device, &queue);
        let renderer = SsbhRenderer::new(
            &device,
            &queue,
            width,
            height,
            scale,
            [0.0, 0.0, 0.0, 0.0],
            SURFACE_FORMAT,
        );
        let output = create_output(&device, width, height);
        Ok(Self {
            models: Vec::new(),
            render_models: Vec::new(),
            renderer,
            shared,
            output,
            width,
            height,
            scale,
            loaded_path: String::new(),
            queue,
            device,
            adapter,
            slots: [None, None],
            cached: Vec::new(),
            #[cfg(windows)]
            gpu_share: None,
            #[cfg(windows)]
            gpu_tex: None,
            #[cfg(windows)]
            gpu_view: None,
            #[cfg(windows)]
            unorm_blit: None,
            #[cfg(windows)]
            gpu_blit_bg: None,
            lighting: None,
            lighting_frame: 0.0,
            lighting_uploaded_frame: None,
            clear_rgba: [0.0, 0.0, 0.0, 0.0],
        })
    }

    fn try_attach_gpu_share(&mut self, width: u32, height: u32) {
        #[cfg(windows)]
        {
            self.gpu_share = None;
            self.gpu_tex = None;
            self.gpu_view = None;
            self.unorm_blit = None;
            self.gpu_blit_bg = None;
            match gpu_share::GpuShare::create(
                &self.adapter,
                &self.device,
                &self.queue,
                width,
                height,
            ) {
                Ok((texture, share)) => {
                    let blit = create_unorm_blit(&self.device, share.wgpu_format());
                    let gpu_view = texture.create_view(&wgpu::TextureViewDescriptor::default());
                    let gpu_blit_bg = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: Some("ssbh_unorm_blit_bg"),
                        layout: &blit.bind_layout,
                        entries: &[wgpu::BindGroupEntry {
                            binding: 0,
                            resource: wgpu::BindingResource::TextureView(&self.output.view),
                        }],
                    });
                    self.unorm_blit = Some(blit);
                    self.gpu_view = Some(gpu_view);
                    self.gpu_blit_bg = Some(gpu_blit_bg);
                    self.gpu_tex = Some(texture);
                    self.gpu_share = Some(share);
                }
                Err(err) => {
                    set_error(format!("GPU present unavailable: {err}"));
                    self.gpu_share = None;
                    self.gpu_tex = None;
                    self.gpu_view = None;
                    self.unorm_blit = None;
                    self.gpu_blit_bg = None;
                }
            }
        }
        #[cfg(not(windows))]
        {
            let _ = (width, height);
        }
    }

    fn resize(&mut self, width: u32, height: u32, scale: f32) {
        let width = clamp_size(width);
        let height = clamp_size(height);
        let scale = if scale.is_finite() && scale > 0.0 {
            scale
        } else {
            1.0
        };
        if self.width == width && self.height == height && (self.scale - scale).abs() < 0.001 {
            return;
        }
        self.wait_pending();
        #[cfg(windows)]
        {
            self.gpu_share = None;
            self.gpu_tex = None;
            self.gpu_view = None;
            self.unorm_blit = None;
            self.gpu_blit_bg = None;
        }
        self.renderer
            .resize(&self.device, width, height, scale);
        self.output = create_output(&self.device, width, height);
        self.width = width;
        self.height = height;
        self.scale = scale;
        self.cached.clear();
    }

    fn load_folder(&mut self, path: &Path) -> Result<(), String> {
        if !path.is_dir() {
            return Err(format!("Model folder not found: {}", path.display()));
        }
        let folder = ModelFolder::load_folder(path);
        if folder.find_mesh().is_none() {
            return Err(format!(
                "No .numshb in {}. Import a Smash model first.",
                path.display()
            ));
        }
        self.render_models = load_render_models(
            &self.device,
            &self.queue,
            std::iter::once(&folder),
            &self.shared,
        );
        self.models = vec![folder];
        self.loaded_path = path.to_string_lossy().into_owned();
        Ok(())
    }

    fn set_camera(
        &mut self,
        view: Mat4,
        proj: Mat4,
        camera_pos: Vec4,
        width: f32,
        height: f32,
        scale: f32,
    ) {
        // Python may pull lighting back in ortho without moving the view, so
        // Smash meshes stay aligned with Blender overlays.
        let camera_pos = if camera_pos.length_squared() > 1e-8 {
            camera_pos
        } else {
            view.inverse().w_axis
        };
        let mvp = proj * view;
        let transforms = CameraTransforms {
            model_view_matrix: view,
            projection_matrix: proj,
            mvp_matrix: mvp,
            mvp_inv_matrix: mvp.inverse(),
            camera_pos,
            screen_dimensions: glam::vec4(width, height, scale, 0.0),
        };
        self.renderer.update_camera(&self.queue, transforms);
    }

    fn set_clear_color(&mut self, r: f64, g: f64, b: f64, a: f64) {
        self.clear_rgba = [r, g, b, a];
        self.renderer.set_clear_color([r, g, b, a]);
    }

    fn load_lighting(&mut self, path: &Path) -> Result<(), String> {
        let data = ssbh_data::anim_data::AnimData::from_file(path)
            .map_err(|e| format!("Failed to load lighting: {e}"))?;
        self.renderer
            .update_stage_uniforms(&self.queue, &data, self.lighting_frame);
        self.lighting_uploaded_frame = Some(self.lighting_frame);
        self.lighting = Some(data);
        Ok(())
    }

    fn clear_lighting(&mut self) {
        self.lighting = None;
        self.lighting_uploaded_frame = None;
        self.renderer.reset_stage_uniforms(&self.queue);
    }

    fn set_lighting_frame(&mut self, frame: f32) {
        self.lighting_frame = if frame.is_finite() { frame } else { 0.0 };
    }

    fn apply_lighting(&mut self, force: bool) {
        let Some(data) = self.lighting.as_ref() else {
            return;
        };
        if !force && self.lighting_uploaded_frame == Some(self.lighting_frame) {
            return;
        }
        self.renderer
            .update_stage_uniforms(&self.queue, data, self.lighting_frame);
        self.lighting_uploaded_frame = Some(self.lighting_frame);
    }

    fn set_world_transforms(&mut self, names: &[String], matrices: &[Mat4]) {
        if self.render_models.is_empty() {
            return;
        }
        let mut by_name = std::collections::HashMap::with_capacity(names.len());
        for (name, mat) in names.iter().zip(matrices.iter()) {
            by_name.insert(name.as_str(), *mat);
        }
        for (model, render_model) in self.models.iter().zip(self.render_models.iter_mut()) {
            let skel = model.find_skel();
            render_model.apply_world_transform_edits(&self.queue, skel, |worlds| {
                let Some(skel) = skel else {
                    return;
                };
                for (i, bone) in skel.bones.iter().enumerate() {
                    if i >= worlds.len() {
                        break;
                    }
                    if let Some(mat) = by_name.get(bone.name.as_str()) {
                        worlds[i] = *mat;
                    }
                }
            });
        }
    }

    fn set_custom_vectors(&mut self, labels: &[String], param: &str, values: &[f32]) {
        for (i, label) in labels.iter().enumerate() {
            let Some(xyzw) = values.get(i * 4..i * 4 + 4) else {
                break;
            };
            let mut updates = Vec::new();
            for model in &self.models {
                let Some(matl) = model.find_matl() else {
                    continue;
                };
                for entry in &matl.entries {
                    if !labels_match(&entry.material_label, label) {
                        continue;
                    }
                    let mut cloned = entry.clone();
                    let mut found = false;
                    for vec_param in &mut cloned.vectors {
                        if param_matches(vec_param.param_id, param) {
                            vec_param.data =
                                ssbh_data::Vector4::new(xyzw[0], xyzw[1], xyzw[2], xyzw[3]);
                            found = true;
                            break;
                        }
                    }
                    if found {
                        updates.push(cloned);
                    }
                }
            }
            for render_model in &mut self.render_models {
                for cloned in &updates {
                    render_model.update_material_params(&self.queue, cloned, &self.shared);
                }
            }
        }
    }

    fn restore_material_params(&mut self) {
        for (model, render_model) in self.models.iter().zip(self.render_models.iter_mut()) {
            let Some(matl) = model.find_matl() else {
                continue;
            };
            for entry in &matl.entries {
                render_model.update_material_params(&self.queue, entry, &self.shared);
            }
        }
    }

    fn set_mesh_visibility(&mut self, names: &[String], subindices: &[u32], visibles: &[u8]) {
        let count = names.len().min(subindices.len()).min(visibles.len());
        for render_model in &mut self.render_models {
            for mesh in &mut render_model.meshes {
                mesh.is_visible = true;
            }
            for i in 0..count {
                let visible = visibles[i] != 0;
                let mut matched = false;
                for mesh in &mut render_model.meshes {
                    if mesh.name == names[i] && mesh.subindex as u32 == subindices[i] {
                        mesh.is_visible = visible;
                        matched = true;
                    }
                }
                if matched {
                    continue;
                }
                for mesh in &mut render_model.meshes {
                    if mesh.name == names[i] {
                        mesh.is_visible = visible;
                    }
                }
            }
        }
    }

    fn wait_pending(&mut self) {
        for i in 0..2 {
            let Some(rx) = self.slots[i].take() else {
                continue;
            };
            let _ = self.device.poll(wgpu::PollType::wait_indefinitely());
            let _ = rx.recv();
            self.output.readbacks[i].unmap();
        }
    }

    fn copy_mapped(&mut self, slot: usize, out: &mut [u8]) -> Result<(), String> {
        let padded = self.output.padded_bpr as usize;
        let width = self.width as usize;
        let height = self.height as usize;
        let tight = width * 4;
        let needed = tight * height;
        if out.len() < needed {
            return Err(format!(
                "RGBA buffer too small: need {needed}, got {}",
                out.len()
            ));
        }
        let mapped = self.output.readbacks[slot].slice(..).get_mapped_range();
        if padded == tight {
            out[..needed].copy_from_slice(&mapped[..needed]);
        } else {
            for y in 0..height {
                let src = y * padded;
                let dst = y * tight;
                out[dst..dst + tight].copy_from_slice(&mapped[src..src + tight]);
            }
        }
        drop(mapped);
        for a in out[..needed].iter_mut().skip(3).step_by(4) {
            *a = if *a < 10 { 0 } else { 255 };
        }
        self.cached.clear();
        self.cached.extend_from_slice(&out[..needed]);
        Ok(())
    }

    fn free_slot(&self) -> Option<usize> {
        (0..2).find(|&i| self.slots[i].is_none())
    }

    fn using_gpu(&self) -> bool {
        #[cfg(windows)]
        {
            self.gpu_share.is_some()
        }
        #[cfg(not(windows))]
        {
            false
        }
    }

    fn submit_gpu_frame(&mut self) -> Result<(), String> {
        self.apply_lighting(false);
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("ssbh_blender_preview_gpu"),
            });
        {
            let _pass = self.renderer.render_models(
                &mut encoder,
                &self.output.view,
                &self.render_models,
                self.shared.database(),
                &ModelRenderOptions::default(),
            );
        }
        #[cfg(windows)]
        if let (Some(blit), Some(gpu_view), Some(bg)) = (
            self.unorm_blit.as_ref(),
            self.gpu_view.as_ref(),
            self.gpu_blit_bg.as_ref(),
        ) {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("ssbh_blender_preview_unorm_blit"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: gpu_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                occlusion_query_set: None,
                timestamp_writes: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&blit.pipeline);
            pass.set_bind_group(0, bg, &[]);
            pass.draw(0..3, 0..1);
        }
        self.queue.submit([encoder.finish()]);
        #[cfg(windows)]
        if let Some(share) = self.gpu_share.as_mut() {
            share.signal()?;
        }
        Ok(())
    }

    fn present_gl(
        &mut self,
        dest_w: u32,
        dest_h: u32,
        submit: bool,
        cover_grid: bool,
    ) -> Result<(), String> {
        if self.render_models.is_empty() {
            return Err("No Smash model loaded".into());
        }
        #[cfg(windows)]
        {
            if self.gpu_share.is_none() {
                self.try_attach_gpu_share(self.width, self.height);
            }
            if self.gpu_share.is_none() {
                return Err("GPU present is not available".into());
            }
            self.gpu_share.as_mut().unwrap().ensure_gl()?;
            let must_submit = submit || self.gpu_view.is_none();
            if must_submit {
                self.submit_gpu_frame()?;
            }
            let result = self.gpu_share.as_mut().unwrap().present_gl(
                dest_w,
                dest_h,
                must_submit,
                cover_grid,
            );
            if result.is_err() {
                self.gpu_share = None;
                self.gpu_tex = None;
                self.gpu_view = None;
                self.unorm_blit = None;
                self.gpu_blit_bg = None;
            }
            result
        }
        #[cfg(not(windows))]
        {
            let _ = (dest_w, dest_h, submit, cover_grid);
            Err("GPU present is Windows-only".into())
        }
    }

    fn submit_frame(&mut self) -> Result<(), String> {
        let Some(slot) = self.free_slot() else {
            return Ok(());
        };
        self.apply_lighting(false);
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("ssbh_blender_preview"),
            });
        {
            let _pass = self.renderer.render_models(
                &mut encoder,
                &self.output.view,
                &self.render_models,
                self.shared.database(),
                &ModelRenderOptions::default(),
            );
        }
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                aspect: wgpu::TextureAspect::All,
                texture: &self.output.texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.output.readbacks[slot],
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.output.padded_bpr),
                    rows_per_image: Some(self.height),
                },
            },
            Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );
        let (sender, receiver) = mpsc::channel();
        encoder.map_buffer_on_submit(
            &self.output.readbacks[slot],
            wgpu::MapMode::Read,
            0..,
            move |result| {
                let _ = sender.send(result);
            },
        );
        self.queue.submit([encoder.finish()]);
        self.slots[slot] = Some(receiver);
        Ok(())
    }

    fn complete_slot(
        &mut self,
        slot: usize,
        out: &mut [u8],
        wait: bool,
    ) -> Result<bool, String> {
        let Some(rx) = self.slots[slot].take() else {
            return Ok(false);
        };
        if !wait {
            let _ = self.device.poll(wgpu::PollType::Poll);
            match rx.try_recv() {
                Ok(Ok(())) => {}
                Ok(Err(err)) => {
                    self.output.readbacks[slot].unmap();
                    return Err(format!("Map readback failed: {err:?}"));
                }
                Err(TryRecvError::Empty) => {
                    self.slots[slot] = Some(rx);
                    return Ok(false);
                }
                Err(TryRecvError::Disconnected) => {
                    return Err("Readback channel closed".into());
                }
            }
        } else {
            self.device
                .poll(wgpu::PollType::wait_indefinitely())
                .map_err(|e| format!("GPU poll failed: {e}"))?;
            rx.recv()
                .map_err(|_| "Readback channel closed".to_string())?
                .map_err(|e| format!("Map readback failed: {e:?}"))?;
        }
        self.copy_mapped(slot, out)?;
        self.output.readbacks[slot].unmap();
        Ok(true)
    }

    fn complete_pending(&mut self, out: &mut [u8], wait: bool) -> Result<bool, String> {
        for i in 0..2 {
            if self.complete_slot(i, out, false)? {
                return Ok(true);
            }
        }
        if !wait {
            return Ok(false);
        }
        for i in 0..2 {
            if self.slots[i].is_some() {
                return self.complete_slot(i, out, true);
            }
        }
        Ok(false)
    }

    fn poll_frame(&mut self, out: &mut [u8]) -> Result<(u32, u32, bool), String> {
        if self.render_models.is_empty() {
            return Err("No Smash model loaded".into());
        }
        let got_new = self.complete_pending(out, false)?;
        Ok((self.width, self.height, got_new))
    }

    fn render(&mut self, out: &mut [u8]) -> Result<(u32, u32, bool), String> {
        if self.render_models.is_empty() {
            return Err("No Smash model loaded".into());
        }
        let needed = self.width as usize * self.height as usize * 4;

        let got_new = self.complete_pending(out, false)?;
        if self.free_slot().is_some() {
            self.submit_frame()?;
        }
        if got_new {
            return Ok((self.width, self.height, true));
        }
        if self.cached.len() == needed {
            return Ok((self.width, self.height, false));
        }

        self.complete_pending(out, true)?;
        if self.free_slot().is_some() {
            self.submit_frame()?;
        }
        Ok((self.width, self.height, true))
    }

    /// Submit the current pose and block until that frame is in `out`.
    fn render_wait(&mut self, out: &mut [u8]) -> Result<(u32, u32, bool), String> {
        if self.render_models.is_empty() {
            return Err("No Smash model loaded".into());
        }
        let _ = self.complete_pending(out, true);
        if self.free_slot().is_none() {
            self.wait_pending();
        }
        self.submit_frame()?;
        if !self.complete_pending(out, true)? {
            return Err("Capture readback failed".into());
        }
        Ok((self.width, self.height, true))
    }
}

impl Drop for Preview {
    fn drop(&mut self) {
        self.wait_pending();
    }
}

fn trim_blender_suffix(name: &str) -> &str {
    if name.len() >= 4 {
        let (head, tail) = name.split_at(name.len() - 4);
        if tail.as_bytes()[0] == b'.' && tail[1..].bytes().all(|b| b.is_ascii_digit()) {
            return head;
        }
    }
    name
}

fn labels_match(entry: &str, want: &str) -> bool {
    if entry == want {
        return true;
    }
    let want_trim = trim_blender_suffix(want);
    let entry_trim = trim_blender_suffix(entry);
    entry == want_trim || entry_trim == want || entry_trim == want_trim
}

fn param_matches(id: ssbh_data::matl_data::ParamId, name: &str) -> bool {
    format!("{id:?}") == name
}

fn catch<T>(f: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(result) => result,
        Err(_) => Err("ssbh_blender_preview panicked".into()),
    }
}

unsafe fn preview_mut<'a>(ptr: *mut Preview) -> Result<&'a mut Preview, String> {
    ptr.as_mut().ok_or_else(|| "Null preview handle".into())
}

unsafe fn c_str<'a>(ptr: *const c_char) -> Result<&'a str, String> {
    if ptr.is_null() {
        return Err("Null string".into());
    }
    CStr::from_ptr(ptr)
        .to_str()
        .map_err(|_| "Path is not valid UTF-8".into())
}

#[no_mangle]
pub extern "C" fn ssbh_preview_create() -> *mut Preview {
    clear_error();
    match catch(Preview::new) {
        Ok(preview) => Box::into_raw(Box::new(preview)),
        Err(err) => {
            set_error(err);
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_destroy(ptr: *mut Preview) {
    if !ptr.is_null() {
        drop(Box::from_raw(ptr));
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_load_folder(
    ptr: *mut Preview,
    path: *const c_char,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        let path = Path::new(unsafe { c_str(path)? });
        preview.load_folder(path)
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_resize(
    ptr: *mut Preview,
    width: u32,
    height: u32,
    scale: f32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        preview.resize(width, height, scale);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_camera(
    ptr: *mut Preview,
    view: *const f32,
    proj: *const f32,
    camera_pos: *const f32,
    width: f32,
    height: f32,
    scale: f32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        if view.is_null() || proj.is_null() || camera_pos.is_null() {
            return Err("Null camera pointer".into());
        }
        let preview = unsafe { preview_mut(ptr)? };
        let view = mat4_from_cols(view);
        let proj = mat4_from_cols(proj);
        let pos = unsafe { std::slice::from_raw_parts(camera_pos, 4) };
        preview.set_camera(
            view,
            proj,
            Vec4::new(pos[0], pos[1], pos[2], pos[3]),
            width,
            height,
            scale,
        );
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_world_transforms(
    ptr: *mut Preview,
    names: *const *const c_char,
    matrices: *const f32,
    count: u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        if count == 0 {
            return Ok(());
        }
        if names.is_null() || matrices.is_null() {
            return Err("Null bone pointer".into());
        }
        let name_ptrs = unsafe { std::slice::from_raw_parts(names, count as usize) };
        let mut bone_names = Vec::with_capacity(count as usize);
        for ptr in name_ptrs {
            bone_names.push(unsafe { c_str(*ptr) }?.to_owned());
        }
        let floats = unsafe { std::slice::from_raw_parts(matrices, count as usize * 16) };
        let mut mats = Vec::with_capacity(count as usize);
        for chunk in floats.chunks_exact(16) {
            let mut cols = [0.0f32; 16];
            cols.copy_from_slice(chunk);
            mats.push(Mat4::from_cols_array(&cols));
        }
        preview.set_world_transforms(&bone_names, &mats);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_mesh_visibility(
    ptr: *mut Preview,
    names: *const *const c_char,
    subindices: *const u32,
    visibles: *const u8,
    count: u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        if count == 0 {
            preview.set_mesh_visibility(&[], &[], &[]);
            return Ok(());
        }
        if names.is_null() || subindices.is_null() || visibles.is_null() {
            return Err("Null mesh visibility pointer".into());
        }
        let name_ptrs = unsafe { std::slice::from_raw_parts(names, count as usize) };
        let mut mesh_names = Vec::with_capacity(count as usize);
        for ptr in name_ptrs {
            mesh_names.push(unsafe { c_str(*ptr) }?.to_owned());
        }
        let subindices = unsafe { std::slice::from_raw_parts(subindices, count as usize) };
        let visibles = unsafe { std::slice::from_raw_parts(visibles, count as usize) };
        preview.set_mesh_visibility(&mesh_names, subindices, visibles);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_custom_vector(
    ptr: *mut Preview,
    labels: *const *const c_char,
    param: *const c_char,
    values: *const f32,
    count: u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        if count == 0 {
            preview.restore_material_params();
            return Ok(());
        }
        if labels.is_null() || param.is_null() || values.is_null() {
            return Err("Null custom vector pointer".into());
        }
        let param_name = unsafe { c_str(param) }?.to_owned();
        let name_ptrs = unsafe { std::slice::from_raw_parts(labels, count as usize) };
        let mut mat_labels = Vec::with_capacity(count as usize);
        for ptr in name_ptrs {
            mat_labels.push(unsafe { c_str(*ptr) }?.to_owned());
        }
        let floats = unsafe { std::slice::from_raw_parts(values, count as usize * 4) };
        preview.set_custom_vectors(&mat_labels, &param_name, floats);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_render(
    ptr: *mut Preview,
    out_rgba: *mut u8,
    out_len: usize,
    out_width: *mut u32,
    out_height: *mut u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        if out_rgba.is_null() {
            return Err("Null RGBA pointer".into());
        }
        let preview = unsafe { preview_mut(ptr)? };
        let out = unsafe { std::slice::from_raw_parts_mut(out_rgba, out_len) };
        preview.render(out)
    });
    match result {
        Ok((w, h, is_new)) => {
            if !out_width.is_null() {
                unsafe {
                    *out_width = w;
                }
            }
            if !out_height.is_null() {
                unsafe {
                    *out_height = h;
                }
            }
            if is_new {
                0
            } else {
                1
            }
        }
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_poll(
    ptr: *mut Preview,
    out_rgba: *mut u8,
    out_len: usize,
    out_width: *mut u32,
    out_height: *mut u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        if out_rgba.is_null() {
            return Err("Null RGBA pointer".into());
        }
        let preview = unsafe { preview_mut(ptr)? };
        let out = unsafe { std::slice::from_raw_parts_mut(out_rgba, out_len) };
        preview.poll_frame(out)
    });
    match result {
        Ok((w, h, is_new)) => {
            if !out_width.is_null() {
                unsafe {
                    *out_width = w;
                }
            }
            if !out_height.is_null() {
                unsafe {
                    *out_height = h;
                }
            }
            if is_new {
                0
            } else {
                1
            }
        }
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_using_gpu(ptr: *mut Preview) -> i32 {
    match unsafe { preview_mut(ptr) } {
        Ok(preview) if preview.using_gpu() => 1,
        _ => 0,
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_present_gl(
    ptr: *mut Preview,
    dest_width: u32,
    dest_height: u32,
    submit: i32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        preview.present_gl(dest_width, dest_height, submit & 1 != 0, submit & 2 != 0)
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            let fallback = err.contains("not available")
                || err.contains("wgl")
                || err.contains("WGL")
                || err.contains("GPU present");
            set_error(err);
            if fallback {
                1
            } else {
                -1
            }
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_clear_color(
    ptr: *mut Preview,
    r: f32,
    g: f32,
    b: f32,
    a: f32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        preview.set_clear_color(r as f64, g as f64, b as f64, a as f64);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_load_lighting(
    ptr: *mut Preview,
    path: *const c_char,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        let path = Path::new(unsafe { c_str(path)? });
        preview.load_lighting(path)
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_clear_lighting(ptr: *mut Preview) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        preview.clear_lighting();
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_set_lighting_frame(
    ptr: *mut Preview,
    frame: f32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let preview = unsafe { preview_mut(ptr)? };
        preview.set_lighting_frame(frame);
        Ok(())
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_render_wait(
    ptr: *mut Preview,
    out_rgba: *mut u8,
    out_len: usize,
    out_width: *mut u32,
    out_height: *mut u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        if out_rgba.is_null() {
            return Err("Null RGBA pointer".into());
        }
        let preview = unsafe { preview_mut(ptr)? };
        let out = unsafe { std::slice::from_raw_parts_mut(out_rgba, out_len) };
        preview.render_wait(out)
    });
    match result {
        Ok((w, h, is_new)) => {
            if !out_width.is_null() {
                unsafe {
                    *out_width = w;
                }
            }
            if !out_height.is_null() {
                unsafe {
                    *out_height = h;
                }
            }
            if is_new {
                0
            } else {
                1
            }
        }
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

/// 1080p cap used for clipboard GIFs in SSBH Editor.
const GIF_CAPTURE_WIDTH: u32 = 1920;
const GIF_CAPTURE_HEIGHT: u32 = 1080;
const GIF_ENCODER_SPEED: i32 = 10;

struct GifSession {
    encoder: GifEncoder<BufWriter<File>>,
    delay: Delay,
    width: u32,
    height: u32,
}

static GIF_SESSION: Mutex<Option<GifSession>> = Mutex::new(None);

fn gif_session() -> Result<std::sync::MutexGuard<'static, Option<GifSession>>, String> {
    GIF_SESSION
        .lock()
        .map_err(|_| "GIF encoder lock poisoned".into())
}

fn fit_gif_frame(image: RgbaImage) -> RgbaImage {
    let (width, height) = image.dimensions();
    if width <= GIF_CAPTURE_WIDTH && height <= GIF_CAPTURE_HEIGHT {
        return image;
    }
    let scale = (GIF_CAPTURE_WIDTH as f32 / width as f32)
        .min(GIF_CAPTURE_HEIGHT as f32 / height as f32);
    let new_w = ((width as f32 * scale).round() as u32).max(1);
    let new_h = ((height as f32 * scale).round() as u32).max(1);
    image::imageops::resize(&image, new_w, new_h, image::imageops::FilterType::Triangle)
}

fn gif_begin(path: &Path, delay_ms: u32, speed: i32) -> Result<(), String> {
    let mut slot = gif_session()?;
    *slot = None;
    let file = File::create(path).map_err(|e| format!("Error creating file {path:?}: {e}"))?;
    let speed = if speed <= 0 { GIF_ENCODER_SPEED } else { speed };
    let mut encoder = GifEncoder::new_with_speed(BufWriter::new(file), speed);
    encoder
        .set_repeat(Repeat::Infinite)
        .map_err(|e| format!("Error configuring GIF encoder: {e}"))?;
    let delay_ms = delay_ms.max(1);
    *slot = Some(GifSession {
        encoder,
        delay: Delay::from_numer_denom_ms(delay_ms, 1),
        width: 0,
        height: 0,
    });
    Ok(())
}

fn gif_add_frame(rgba: &[u8], width: u32, height: u32) -> Result<(), String> {
    let needed = width as usize * height as usize * 4;
    if rgba.len() < needed {
        return Err(format!(
            "GIF frame buffer too small: need {needed}, got {}",
            rgba.len()
        ));
    }
    let raw = RgbaImage::from_raw(width, height, rgba[..needed].to_vec())
        .ok_or_else(|| "Invalid GIF frame buffer".to_owned())?;
    let mut image = fit_gif_frame(raw);
    let mut slot = gif_session()?;
    let session = slot.as_mut().ok_or_else(|| "GIF encoder is not active".to_owned())?;
    if session.width == 0 {
        session.width = image.width();
        session.height = image.height();
    } else if image.dimensions() != (session.width, session.height) {
        image = image::imageops::resize(
            &image,
            session.width,
            session.height,
            image::imageops::FilterType::Triangle,
        );
    }
    let delay = session.delay;
    let frame = Frame::from_parts(image, 0, 0, delay);
    session
        .encoder
        .encode_frame(frame)
        .map_err(|e| format!("Error encoding GIF frame: {e}"))?;
    Ok(())
}

fn gif_finish() -> Result<(), String> {
    let mut slot = gif_session()?;
    let session = slot.take().ok_or_else(|| "GIF encoder is not active".to_owned())?;
    drop(session.encoder);
    Ok(())
}

fn gif_cancel() {
    if let Ok(mut slot) = gif_session() {
        *slot = None;
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_gif_begin(
    path: *const c_char,
    delay_ms: u32,
    speed: i32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        let path = PathBuf::from(unsafe { c_str(path)? });
        gif_begin(&path, delay_ms, speed)
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_gif_add_frame(
    rgba: *const u8,
    len: usize,
    width: u32,
    height: u32,
) -> i32 {
    clear_error();
    let result = catch(|| {
        if rgba.is_null() {
            return Err("Null RGBA pointer".into());
        }
        let pixels = unsafe { std::slice::from_raw_parts(rgba, len) };
        gif_add_frame(pixels, width, height)
    });
    match result {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_gif_finish() -> i32 {
    clear_error();
    match catch(gif_finish) {
        Ok(()) => 0,
        Err(err) => {
            set_error(err);
            -1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ssbh_preview_gif_cancel() -> i32 {
    gif_cancel();
    0
}

#[no_mangle]
pub extern "C" fn ssbh_preview_last_error() -> *const c_char {
    match LAST_ERROR.lock() {
        Ok(slot) => slot
            .as_ref()
            .map(|s| s.as_ptr())
            .unwrap_or(ptr::null()),
        Err(_) => ptr::null(),
    }
}
