#!/usr/bin/env python3
"""Apply and preserve the narrow tri-state config / bridge core integration."""
from pathlib import Path
import argparse, difflib, json, subprocess

REPO = Path(__file__).resolve().parents[2]
SRC = Path.home()/"work/rpcs3-latest"
BACKUP = Path.home()/"work/framegen0076-original-20261031"
PATCH = REPO/"port/rpcs3-latest-patches/0076-PS5-adaptive-frame-generation-mode.patch"
originals = {}
planned = {}
recover = False

def edit(name, replacements):
    path=SRC/name
    raw=path.read_bytes()
    text=raw.decode().replace("\r\n","\n")
    if recover:
        for item in replacements:
            before,after=item[:2]
            if after in text:
                assert text.count(after)==(item[2] if len(item)==3 else 1),(name,after)
                text=text.replace(after,before)
    originals[name]=(text.replace("\n","\r\n") if b"\r\n" in raw else text).encode()
    for item in replacements:
        before,after=item[:2]
        assert text.count(before)==(item[2] if len(item)==3 else 1),(name,before)
        text=text.replace(before,after)
    final=text.replace("\n","\r\n") if b"\r\n" in raw else text
    planned[name]=final.encode()

def main():
    global recover
    parser=argparse.ArgumentParser(); parser.add_argument("--recover-partial",action="store_true")
    recover=parser.parse_args().recover_partial
    assert not PATCH.exists(), "Existing patch; do not overwrite"
    assert not BACKUP.exists() or (recover and not any(BACKUP.iterdir())), "Existing backup; do not overwrite"
    edit("rpcs3/Emu/system_config_types.h",[("enum class frame_limit_type\n{", "#ifdef __PROSPERO__\nenum class ps5_frame_generation_mode\n{\n\toff = 0,\n\ton = 1,\n\tadaptive = 2,\n};\n#endif\n\nenum class frame_limit_type\n{")])
    edit("rpcs3/Emu/system_config_types.cpp",[("template <>\nvoid fmt_class_string<frame_limit_type>::format", "#ifdef __PROSPERO__\ntemplate <>\nvoid fmt_class_string<ps5_frame_generation_mode>::format(std::string& out, u64 arg)\n{\n\tformat_enum(out, arg, [](ps5_frame_generation_mode value)\n\t{\n\t\tswitch (value)\n\t\t{\n\t\tcase ps5_frame_generation_mode::off: return \"Off\";\n\t\tcase ps5_frame_generation_mode::on: return \"On\";\n\t\tcase ps5_frame_generation_mode::adaptive: return \"Adaptive\";\n\t\t}\n\t\treturn unknown;\n\t});\n}\n#endif\n\ntemplate <>\nvoid fmt_class_string<frame_limit_type>::format")])
    config_type='''#ifdef __PROSPERO__
// Accept the original boolean YAML without changing saved user files.
struct ps5_frame_generation_setting : cfg::_enum<ps5_frame_generation_mode>
{
    using base = cfg::_enum<ps5_frame_generation_mode>;
    using base::base;
    bool from_string(std::string_view value, bool dynamic = false) override
    {
        if (value == "true") value = "On";
        else if (value == "false") value = "Off";
        return base::from_string(value, dynamic);
    }
};
#endif

'''
    edit("rpcs3/Emu/system_config.h",[("struct cfg_root : cfg::node", config_type+"struct cfg_root : cfg::node"),('cfg::_bool ps5_frame_generation{ this, "Frame Generation (MihawkGen)", false };', 'ps5_frame_generation_setting ps5_frame_generation{ this, "Frame Generation (MihawkGen)", ps5_frame_generation_mode::off };')])
    edit("rpcs3/Emu/RSX/VK/vkutils/swapchain.cpp",[("g_cfg.video.ps5_frame_generation &&", "g_cfg.video.ps5_frame_generation.get() != ps5_frame_generation_mode::off &&",2), ("else if (g_cfg.video.ps5_frame_generation)", "else if (g_cfg.video.ps5_frame_generation.get() != ps5_frame_generation_mode::off)"), ("image, semaphore, &result, vk::acquire_global_submit_lock", "image, semaphore, &result, static_cast<u32>(g_cfg.video.ps5_frame_generation.get()), vk::acquire_global_submit_lock")])
    edit("rpcs3/ps5/ps5_framegen.h",[("VkSemaphore rendered, VkResult *result, void (*lock_queue)", "VkSemaphore rendered, VkResult *result, uint32_t mode, void (*lock_queue)")])
    changed=planned
    chunks=["From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\nFrom: KB <kb@kb-rpcs3.example>\nDate: Sat, 31 Oct 2026 13:00:00 +0000\nSubject: [PATCH] PS5: Off, On and Adaptive frame-generation modes\n\nPreserve legacy boolean configs and pass the selected mode to the title\npresentation bridge. Adaptive image-change rejection lives in the title.\n---\n"]
    BACKUP.mkdir(exist_ok=True)
    for name,before in originals.items():
        target=BACKUP/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(before)
        chunks.append(f"diff --git a/{name} b/{name}\n")
        chunks.extend(difflib.unified_diff(before.decode().splitlines(keepends=True), changed[name].decode().splitlines(keepends=True), fromfile="a/"+name,tofile="b/"+name))
    PATCH.write_bytes("".join(chunks).encode())
    for name,data in changed.items(): (SRC/name).write_bytes(data)
    subprocess.run(["git","-C",str(SRC),"apply","--reverse",str(PATCH)],check=True)
    assert all((SRC/n).read_bytes()==v for n,v in originals.items())
    subprocess.run(["git","-C",str(SRC),"apply",str(PATCH)],check=True)
    assert all((SRC/n).read_bytes()==v for n,v in changed.items())
    manifest=json.loads((REPO/"port/rpcs3-latest.json").read_text()); assert manifest["patch_count"]==75
    manifest["patch_count"]=76
    (REPO/"port/rpcs3-latest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("PASS patch0076 exact reverse/replay; prior dirty source preserved",BACKUP)

if __name__=="__main__": main()
