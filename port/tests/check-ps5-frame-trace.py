#!/usr/bin/env python3
"""Host smoke test for PS5 sparse timeline ring, epoch selection and waits."""
import pathlib
import subprocess
import tempfile
import textwrap

HEADER = pathlib.Path("/home/callum/work/rpcs3-latest/rpcs3/Emu/RSX/ps5_frame_trace.h")


def main():
    if not HEADER.is_file():
        raise RuntimeError(f"Missing upstream sparse trace header {HEADER}")
    with tempfile.TemporaryDirectory(prefix="ps5-framedep-test-") as t:
        d = pathlib.Path(t)
        (d / "util").mkdir()
        (d / "util" / "tsc.hpp").write_text(textwrap.dedent("""\
            #pragma once
            #include <atomic>
            #include <cstdint>
            namespace utils {
              inline std::atomic<std::uint64_t> mock_ticks{1000000};
              inline std::uint64_t get_tsc() { return mock_ticks.fetch_add(1000000); }
            }
            """))
        (d / "util" / "sysinfo.hpp").write_text(textwrap.dedent("""\
            #pragma once
            namespace utils { inline unsigned long long get_tsc_freq() { return 1000000000ull; } }
            """))
        (d / "test.cpp").write_text(textwrap.dedent(f"""\
            #define __PROSPERO__
            #include "{HEADER}"
            #include <cassert>
            using namespace ps5_frame_trace;
            int main() {{
              for (int i = 0; i < 31; ++i) {{
                guest_queue(7);
                mark(event::guest_flip, 7);
                assert(!sampled);
              }}
              assert(written == 0);
              if (!enabled) {{
                guest_queue(3);
                mark(event::guest_flip, 19);
                {{ long_wait wait(event::ppu_event_wait_begin, 0x0100000a); }}
                assert(written == 0 && epoch == 0 && !sampled);
                return 0;
              }}
              guest_queue(3);
              assert(sampled && epoch == 32 && written == 1);
              mark(event::guest_flip, 19);
              {{
                long_wait w(event::ppu_event_wait_begin, 0x0100000a);
                utils::get_tsc();
              }}
              assert(written == 4);
              record a{{}}, b{{}}, c{{}}, e{{}};
              assert(read(0, a) && read(1, b) && read(2, c) && read(3, e));
              assert((a.payload & 0xff) == 1 && (a.payload >> 40) == 32);
              assert(((b.payload >> 8) & 0xffffffffu) == 19);
              assert((c.payload & 0xff) == 14 && (e.payload & 0xff) == 15);
              assert(((c.payload >> 8) & 0xffffffffu) == 0x0100000a);
              assert(e.tsc > c.tsc && c.tsc > b.tsc);
              guest_queue(9);
              assert(!sampled && written == 4);
              for (int i=0; i<31; ++i) guest_queue(1);
              assert(sampled && epoch == 64 && written == 5);
              assert(read(4, a) && (a.payload >> 40) == 64);
              return 0;
            }}
            """))
        exe = d / "test"
        subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra",
                        "-I", str(d), str(d / "test.cpp"), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: PS5 frame-trace header smoke test (active epoch/ring behaviour or disabled no-op mode)")


if __name__ == "__main__":
    main()
