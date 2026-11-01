#!/usr/bin/env bash
# HOST-ONLY signed native PS5 title access probe (no emulator or registration).
# Usage: PS5_PAYLOAD_SDK=/path/to/pinned-sdk bash tools/trophy-bridge/build_shared_root_probe.sh /NEW/private/directory
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:?Required: NEW private host-only build directory}"
if [[ -e "$out" ]]; then
    echo "Refusing to overwrite existing output: $out" >&2
    exit 2
fi
vulkan="${PS5_VULKAN_DIR:-/home/callum/work/PS5_Vulkan}"
sdk="${PS5_PAYLOAD_SDK:-/home/callum/work/PS5_Vulkan/.deps/native/ps5-payload-sdk}"
export PS5_CLANG="${PS5_CLANG:-$(command -v clang)}"
tool="$vulkan/build/host/ps5-native-tool"
native="$vulkan/tooling/native"
for p in "$sdk/bin/prospero-lld" "$sdk/bin/llvm-ar" "$vulkan/runtime/libc.prx" \
         "$native/app_crt.cpp" "$native/app-symbols.map" "$vulkan/tools/radv-link.sh" "$tool"; do
    if [[ ! -e "$p" ]]; then echo "Missing prerequisite: $p" >&2; exit 2; fi
done
mkdir -p "$out/obj" "$out/app/sce_module"
cc() { PS5_PAYLOAD_SDK="$sdk" sh "$vulkan/tooling/prospero-clang18" "$@"; }
cc -std=c++20 -O2 -fno-exceptions -fno-rtti -c "$native/app_crt.cpp" -o "$out/obj/app_crt.o"
cc -std=c11 -O2 -Wall -Wextra -Werror -c "$src/native_shared_root_probe.c" -o "$out/obj/shared_root_probe.o"
"$sdk/bin/llvm-ar" rc "$out/obj/empty.a"
# shellcheck source=/dev/null
source "$vulkan/tools/radv-link.sh"
radv_link_recipe "$vulkan" "$sdk" "$out/obj/empty.a"
"$sdk/bin/prospero-lld" --error-limit=0 --no-dynamic-linker "${radv_linker_script[@]}" \
  --eh-frame-hdr "${radv_link_flags[@]}" --version-script "$native/app-symbols.map" \
  --exclude-libs=ALL -e _start -o "$out/obj/shared_root.elf" \
  "$out/obj/app_crt.o" "$out/obj/shared_root_probe.o" \
  "${radv_link_inputs[@]}" --as-needed "$sdk"/target/lib/*.so
"$tool" link --in "$out/obj/shared_root.elf" --out "$out/obj/eboot.elf" \
  --stub-dir "$sdk/target/lib" --module-sdk 0x02000009 --companion-sdk 0x08050001 --file-name eboot.elf
"$tool" self --sign --in "$out/obj/eboot.elf" --out "$out/app/eboot.bin" --magic 0x1D3D154F
cp "$vulkan/runtime/libc.prx" "$out/app/sce_module/libc.prx"
sha256sum "$out/obj/eboot.elf" "$out/app/eboot.bin" "$out/app/sce_module/libc.prx"
echo "COMPLETE: PC-only owner shared-root access probe, NOT installed"
