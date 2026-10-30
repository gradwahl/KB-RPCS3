#!/usr/bin/env python3
"""Compile the real identity method and check console and desktop selection."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
source = (root / 'rpcs3/Emu/RSX/VK/VKGSRender.cpp').read_text()
start = source.index('std::string VKGSRender::configured_logical_id() const')
end = source.index('\nbool VKGSRender::', start)
method = source[start:end]
fixture = r'''
#include <cassert>
#include <string>
enum class video_renderer { null, vulkan };
struct setting {
    std::string value;
    std::string to_string() const { return value; }
};
struct {
    struct {
        video_renderer renderer = video_renderer::vulkan;
        struct { setting adapter; } vk;
    } video;
} g_cfg;
namespace rsx {
video_renderer resolve_render_backend_type(video_renderer type) { return type; }
}
struct VKGSRender {
    std::string logical_id() const { return "Vulkan | PlayStation 5 GPU (RADV NAVI21)"; }
    std::string configured_logical_id() const;
};
'''
checks = r'''
int main() {
    VKGSRender renderer;
    for (const auto* name : {"", "PS5 GPU (RADV)",
                            "PlayStation 5 GPU (RADV NAVI21)", "Other GPU"}) {
        g_cfg.video.vk.adapter.value = name;
#ifdef __PROSPERO__
        // Every saved alias resolves to the console's single physical GPU.
        assert(renderer.configured_logical_id() == renderer.logical_id());
#else
        assert(renderer.configured_logical_id() ==
            (std::string(name).empty() ? renderer.logical_id() : "Vulkan | " + std::string(name)));
#endif
    }
    g_cfg.video.renderer = video_renderer::null;
    assert(renderer.configured_logical_id().empty());
}
'''
with tempfile.TemporaryDirectory() as tmp:
    test = Path(tmp) / 'identity.cpp'
    test.write_text(fixture + method + checks)
    for platform, defines in [('PS5', ['-D__PROSPERO__']), ('desktop', [])]:
        executable = Path(tmp) / platform
        subprocess.run(['c++', '-std=c++17', *defines, str(test), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
        print(f'{platform}: renderer identity checks passed')
