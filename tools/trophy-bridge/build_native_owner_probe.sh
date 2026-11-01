#!/usr/bin/env bash
# Build a standalone SIGNED PS5 title-lifecycle probe, NOT an installer.
# It does not include RPCS3, trophy APIs, live PS5 file operations or patches.
# Source based on existing KB-RPCS3 tools/launcher/build.sh title link recipe.
# Usage: bash tools/trophy-bridge/build_native_owner_probe.sh /path/to/host-output
set -euo pipefail
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:?first argument: NEW PRIVATE OUTPUT DIRECTORY}"
if [[ -e "$out" ]]; then
  echo "Output already exists, will not overwrite: $out" >&2
  exit 2
fi
vulkan="${PS5_VULKAN_DIR:-/home/callum/work/PS5_Vulkan}"
sdk="${PS5_PAYLOAD_SDK:-/opt/ps5-payload-sdk}"
export PS5_CLANG="${PS5_CLANG:-$(command -v clang)}"
tool="$vulkan/build/host/ps5-native-tool"
native="$vulkan/tooling/native"
if [[ ! -x "$tool" || ! -f "$vulkan/runtime/libc.prx" || ! -f "$native/app_crt.cpp" ]]; then
  echo "PS5 native title linker/resources missing - compile would not be reliable" >&2
  exit 2
fi
if [[ ! -f "$sdk/bin/prospero-lld" || ! -f "$vulkan/tools/radv-link.sh" ]]; then
  echo "PS5 SDK link prerequisites missing" >&2
  exit 2
fi
mkdir -p "$out/obj" "$out/app/sce_module"
cc() { PS5_PAYLOAD_SDK="$sdk" sh "$vulkan/tooling/prospero-clang18" "$@"; }
cc -std=c++20 -O2 -fno-exceptions -fno-rtti -c "$native/app_crt.cpp" -o "$out/obj/app_crt.o"
cc -std=c11 -O2 -Wall -Wextra -Werror -c "$src/native_owner_probe.c" -o "$out/obj/native_owner.o"
"$sdk/bin/llvm-ar" rc "$out/obj/empty.a"
# shellcheck source=/dev/null
source "$vulkan/tools/radv-link.sh"
radv_link_recipe "$vulkan" "$sdk" "$out/obj/empty.a"
"$sdk/bin/prospero-lld" --error-limit=0 --no-dynamic-linker "${radv_linker_script[@]}" --eh-frame-hdr "${radv_link_flags[@]}" \
  --version-script "$native/app-symbols.map" --exclude-libs=ALL -e _start \
  -o "$out/obj/owner.elf" "$out/obj/app_crt.o" "$out/obj/native_owner.o" \
  "${radv_link_inputs[@]}" --as-needed "$sdk"/target/lib/*.so
"$tool" link --in "$out/obj/owner.elf" --out "$out/obj/eboot.elf" \
  --stub-dir "$sdk/target/lib" --module-sdk 0x02000009 --companion-sdk 0x08050001 --file-name eboot.elf
"$tool" self --sign --in "$out/obj/eboot.elf" --out "$out/app/eboot.bin" --magic 0x1D3D154F
cp "$vulkan/runtime/libc.prx" "$out/app/sce_module/libc.prx"
sha256sum "$out/app/eboot.bin" "$out/app/sce_module/libc.prx"
echo "Build complete. HOST ONLY. Not installed to PS5."
