"""The CPU-readback blit decodes premultiplied sRGB bytes like the OpenGL present.

Needs a GPU context, so it runs windowed (not --background), once per backend:
blender --factory-startup --gpu-backend vulkan --python-exit-code 1 --python tests/test_smash_viewport_cpu_blit_gpu.py
"""
from pathlib import Path
import numpy as np

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
import gpu
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')

raw = np.array([
    255, 128, 0, 255,    0, 0, 0, 0,          # top row: opaque orange, empty
    94, 94, 94, 128,     255, 255, 255, 255,  # bottom row: half-covered edge, white
], dtype=np.uint8)
backdrop = (0.25, 0.5, 0.75, 1.0)
offscreen = gpu.types.GPUOffScreen(2, 2, format='RGBA32F')
with offscreen.bind():
    framebuffer = gpu.state.active_framebuffer_get()
    framebuffer.clear(color=backdrop)
    viewport.draw_readback(viewport.upload_readback(bytearray(raw.tobytes()), 2, 2))
    pixels = np.array(framebuffer.read_color(0, 0, 2, 2, 4, 0, 'FLOAT').to_list()).reshape(2, 2, 4)
offscreen.free()
top, bottom = pixels[1], pixels[0]  # framebuffer rows are read bottom-up
edge = 0.111932 / (128 / 255)
expected = {
    'orange': (top[0], (1.0, 0.2158605, 0.0, 1.0)),
    'empty keeps backdrop': (top[1], backdrop),
    'edge un-premultiplied': (bottom[0], (edge, edge, edge, 1.0)),
    'white': (bottom[1], (1.0, 1.0, 1.0, 1.0)),
}
for label, (got, want) in expected.items():
    assert np.allclose(got, want, atol=2e-3), (gpu.platform.backend_type_get(), label, got, want)
# Cropped readback: only the covered box is uploaded and drawn in place.
import ctypes
from types import SimpleNamespace


def fake_render(_preview, address, length, rect):
    # 3x2 image; one covered pixel at x=1, y=0 (top row), orange.
    out = (ctypes.c_float * length).from_address(address)
    out[0:4] = [1.0, 128 / 255, 0.0, 1.0]
    rect[0], rect[1], rect[2], rect[3] = 1, 0, 1, 1
    return 0


calls = []
submits = []
viewport._lib = SimpleNamespace(
    ssbh_preview_submit_readback=lambda preview: submits.append(preview) or 0,
    ssbh_preview_collect_float=lambda *a: calls.append(a) or fake_render(*a))
offscreen = gpu.types.GPUOffScreen(3, 2, format='RGBA32F')
with offscreen.bind():
    framebuffer = gpu.state.active_framebuffer_get()
    framebuffer.clear(color=backdrop)
    assert viewport.render_cropped(1, 3, 2, True)
    assert viewport.render_cropped(1, 3, 2, False)  # unchanged: reuses the upload
    pixels = np.array(framebuffer.read_color(0, 0, 3, 2, 4, 0, 'FLOAT').to_list()).reshape(2, 3, 4)
    # A frame started early (frame change) is collected by the next draw, without resubmitting.
    viewport._presubmitted = True
    assert viewport.render_cropped(1, 3, 2, False)
    assert not viewport._presubmitted
    # A pending first frame already owns the render, even before its texture exists.
    viewport._blit_tex_key = None
    viewport._presubmitted = True
    assert viewport.render_cropped(1, 3, 2, False)
    assert not viewport._presubmitted
    assert len(submits) == 1, submits
    # Real changes after presubmission still require a fresh render.
    viewport._presubmitted = True
    assert viewport.render_cropped(1, 3, 2, True)
    assert not viewport._presubmitted
offscreen.free()
assert len(calls) == 4 and len(submits) == 2, (calls, submits)
assert np.allclose(pixels[1][1], (1.0, 0.2158605, 0.0, 1.0), atol=2e-3), pixels
for row, col in ((1, 0), (1, 2), (0, 0), (0, 1), (0, 2)):
    assert np.allclose(pixels[row][col], backdrop, atol=1e-3), (row, col, pixels)
print('SMASH_VIEWPORT_CPU_BLIT_GPU_OK', gpu.platform.backend_type_get())
# quit_blender can hang during Vulkan startup shutdown; exit directly once checked.
import os, sys
sys.stdout.flush()
os._exit(0)
