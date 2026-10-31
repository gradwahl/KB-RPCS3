#!/usr/bin/env python3
"""Patch0071 reversible replay, exact original and gate tests.

No emulator reset. Compare only the two files modified/created by patch0071.
Compile-time default OFF is required; ON must be explicit for diagnostic builds.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "port/rpcs3-latest-patches/0071-PS5-opt-in-bounded-Vulkan-fence-wait.patch"
SOURCE = "rpcs3/Emu/RSX/VK/vkutils/sync.cpp"
HEADER = "rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h"


def call(*args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=40)
    if p.returncode:
        raise AssertionError(f"{args}\nexit={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def test(source: Path, original: Path):
    expected = json.loads((original / "manifest.json").read_text("utf8"))
    assert expected["patch"] == 71
    sync_bytes = (source / SOURCE).read_bytes()
    header_bytes = (source / HEADER).read_bytes()
    assert hashlib.sha256(sync_bytes).hexdigest() == expected["new_sha256"]
    assert hashlib.sha256(header_bytes).hexdigest() == expected["header_sha256"]
    assert PATCH.read_text("utf8").count("diff --git ") == 2
    assert "#define PS5_VK_FENCE_TIMED_WAIT 0" in header_bytes.decode()
    with tempfile.TemporaryDirectory(prefix="vk-fence0071-replay-") as d:
        target = Path(d)
        call("git", "init", "-q", str(target))
        for name, data in [(SOURCE, sync_bytes), (HEADER, header_bytes)]:
            file = target / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        call("git", "apply", "--reverse", "--check", str(PATCH), cwd=target)
        call("git", "apply", "--reverse", str(PATCH), cwd=target)
        assert not (target / HEADER).exists()
        original_bytes = (original / "sync.cpp").read_bytes()
        assert (target / SOURCE).read_bytes() == original_bytes
        assert hashlib.sha256(original_bytes).hexdigest() == expected["old_sha256"]
        call("git", "apply", "--check", str(PATCH), cwd=target)
        call("git", "apply", str(PATCH), cwd=target)
        assert (target / SOURCE).read_bytes() == sync_bytes
        assert (target / HEADER).read_bytes() == header_bytes
        test_file = target / "gate.cpp"
        test_file.write_text(
            '#include "rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h"\n'
            '#if PS5_VK_FENCE_TIMED_WAIT != EXPECTED\n#error Wrong switch value\n#endif\n'
            'int main(){return 0;}\n', encoding="utf8"
        )
        for value in (0, 1):
            args = ["clang++-19", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    f"-DEXPECTED={value}", "-I", str(source), str(test_file),
                    "-o", str(target / f"gate{value}")]
            if value:
                args.insert(-3, "-DPS5_VK_FENCE_TIMED_WAIT=1")
            call(*args)
            call(str(target / f"gate{value}"))
    print("PASS patch0071 reversible replay of exact original, default OFF and diagnostic ON gate")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path.home() / "work/rpcs3-latest")
    p.add_argument("--original", type=Path, default=Path.home() / "work/cpu-plan-vk-fence0071-original-20261031")
    args = p.parse_args()
    test(args.source, args.original)
