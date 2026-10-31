#!/usr/bin/env python3
"""Host presentation-contract + real neural GPU smoke tests (not PS5 gameplay)."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vulkan-headers", type=Path,
                        default=Path.home() / "work/deps/Vulkan-Headers-1.4.354/include")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    app = REPO / "app"
    tests = REPO / "port/tests"
    model = (app / "ps5/src/framegen_model.cpp.in").read_text().replace("@ROOT@", str(app))
    (out / "model.cpp").write_text(model)
    flags = ["clang++-19", "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread",
             "-I" + str(app / "ps5/src"), "-I" + str(app / "framegen/include"),
             "-I" + str(app / "framegen/src"),
             "-I" + str(args.vulkan_headers)]
    run(*flags, tests / "check-ps5-framegen-policy.cpp", "-o", out / "policy")
    run(out / "policy")
    run(*flags, tests / "ps5-framegen-present-mock.cpp", app / "ps5/src/ps5_framegen.cpp",
        out / "model.cpp", "-o", out / "present-mock")
    run(out / "present-mock", timeout=30)
    print("PASS Off/On/Adaptive, image-change rejection/recovery, coherent/noncoherent preview, cadence, semaphore ownership, midpoint/real ordering, resize/teardown, "
          "allocation fallback, device loss and acquire/suboptimal recovery", flush=True)
    sources = sorted((app / "framegen/src").glob("*.cpp"))
    run(*flags, "-Wno-missing-designated-field-initializers", app / "framegen/tests/test_framegen.cpp",
        *sources, "-l:libvulkan.so.1", "-o", out / "upstream-unit")
    run(out / "upstream-unit", app / "framegen/shaders")
    shaders = list((app / "framegen/shaders").glob("*.spv"))
    for path in shaders:
        run("spirv-val", "--target-env", "vulkan1.3", path)
    run(*flags, "-Wno-missing-designated-field-initializers", app / "framegen/tests/neural_run.cpp",
        *sources, "-l:libvulkan.so.1", "-o", out / "neural-run")
    frame = bytes([32, 64, 128, 255]) * (64 * 64)
    for name in ("a.rgba", "b.rgba"):
        (out / name).write_bytes(frame)
    env = dict(os.environ, VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/lvp_icd.json")
    run(*flags, "-Wno-missing-designated-field-initializers", tests / "ps5-framegen-preview-gpu.cpp",
        out / "model.cpp", *sources, "-l:libvulkan.so.1", "-o", out / "preview-gpu")
    run(out / "preview-gpu", env=env, timeout=30)
    run(out / "neural-run", app / "framegen/models/network.fgw", out / "a.rgba", out / "b.rgba",
        "64", "64", "0.5", out / "midpoint.rgba", "1", env=env, timeout=180)
    actual = (out / "midpoint.rgba").read_bytes()
    assert len(actual) == len(frame)
    error = max(abs(a - b) for a, b in zip(actual, frame))
    assert error <= 1, error
    report = {"mock_presentation_contract": "PASS", "upstream_device_free": "PASS",
              "adaptive_image_change_rejection_and_recovery": "PASS",
              "off_passthrough_and_preview_memory_fallback": "PASS",
              "lavapipe_production_preview_readback_and_detector": "PASS",
              "spirv_modules_validated": len(shaders), "lavapipe_neural_static_frame": "PASS",
              "static_max_channel_error": error, "PS5_gameplay": "NOT RUN"}
    (out / "host-checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PASS actual lavapipe neural midpoint/static-frame pixel readback", flush=True)


if __name__ == "__main__":
    main()
