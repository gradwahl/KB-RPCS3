#!/usr/bin/env python3
"""Compile real RSX DMA copy paths with mocks and verify the PS5 non-strict fast path.

Regression checks validate the actual upstream source extracts, including
strict/desktop behaviour and the offload queue. They do not prove FPS gains.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil

source = (Path(sys.argv[1]) / "rpcs3/Emu/RSX/RSXOffload.cpp").read_text()
start = source.index("\tvoid dma_manager::copy(void *dst, void *src, u32 length) const")
end = source.index("\n\t// Vertex utilities", start)
method = source[start:end]
start = source.index("\t\t\t\t\tcase raw_copy:")
end = source.index("\n\t\t\t\t\tcase vector_copy:", start)
case = source[start:end]
fixture = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <utility>
using u32 = uint32_t;
struct config {
    struct {
        bool multithreaded_rsx = false;
        bool strict_rendering_mode = false;
    } video;
} g_cfg;
int lookups = 0;
int locks = 0;
namespace vm {
    std::pair<u32, bool> try_get_addr(void *ptr) {
        ++lookups;
        return {ptr ? 0x1000u : 0u, !!ptr};
    }
}
namespace rsx {
template<bool, unsigned>
struct reservation_lock {
    reservation_lock(u32 address, u32 length, bool enabled) {
        if (enabled) {
            assert(address != 0 && length != 0);
            ++locks;
        }
    }
};
enum job_type { raw_copy, vector_copy };
struct packet { job_type type; void *dst; void *src; u32 length; };
struct queue {
    bool queued = false;
    packet job{};
    void push(void *dst, void *src, u32 length) {
        queued = true;
        job = {raw_copy, dst, src, length};
    }
};
struct worker {
    int m_enqueued_count = 0;
    queue m_work_queue;
};
class dma_manager {
public:
    static constexpr u32 max_immediate_transfer_size = 64;
    std::shared_ptr<worker> m_thread = std::make_shared<worker>();
    void copy(void *dst, void *src, u32 length) const;
};
"""
suffix = r"""
void execute_job(const packet& job) {
    switch (job.type) {
CASE
    default:
        assert(false);
    }
}
}
int main() {
    unsigned char src[256]{}, dst[256]{};
    for (int i = 0; i < 256; ++i) src[i] = static_cast<unsigned char>(i);
    rsx::dma_manager manager;
    for (bool strict : {false, true})
    for (bool threaded : {false, true}) {
        g_cfg.video.strict_rendering_mode = strict;
        g_cfg.video.multithreaded_rsx = threaded;
        for (u32 count : {16u, 160u}) {
            std::memset(dst, 0, sizeof(dst));
            lookups = locks = 0;
            manager.m_thread->m_work_queue.queued = false;
            manager.copy(dst, src, count);
            const bool queued = threaded && count > manager.max_immediate_transfer_size;
            assert(manager.m_thread->m_work_queue.queued == queued);
            if (queued) {
                assert(lookups == 0 && locks == 0);
                assert(dst[1] == 0); // No synchronous work yet
                rsx::execute_job(manager.m_thread->m_work_queue.job);
            }
            assert(std::memcmp(dst, src, count) == 0);
#if defined(__PROSPERO__)
            assert(lookups == (strict ? 1 : 0));
#else
            assert(lookups == 1);
#endif
            assert(locks == (strict ? 1 : 0));
        }
    }

    // Offload path must also support non-VM inputs without taking a lock.
    g_cfg.video.strict_rendering_mode = true;
    lookups = locks = 0;
    rsx::execute_job({rsx::raw_copy, dst, nullptr, 0});
    assert(lookups == 1 && locks == 0);
    return 0;
}
""".replace("CASE", case)
compiler = shutil.which("clang++-19") or shutil.which("g++") or shutil.which("c++")
if not compiler:
    raise SystemExit("A C++ compiler is required")
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    cpp = directory / "dma-copy.cpp"
    cpp.write_text(fixture + method + suffix)
    for platform, flags in (("PS5", ["-D__PROSPERO__"]), ("desktop", [])):
        executable = directory / platform
        subprocess.run([compiler, "-std=c++20", "-O2", *flags, str(cpp),
                        "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True, timeout=10)
        print(f"PASS: {platform} sync copy, offloader, strict and non-strict semantics")
