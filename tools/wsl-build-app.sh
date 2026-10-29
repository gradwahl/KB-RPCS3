#!/usr/bin/env bash
# Build KB-RPCS3 in Ubuntu/WSL without Lima. Creates local WSL Git snapshot for licence staging.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
native_tls=${PS5_NATIVE_TLS:-OFF}
case "$native_tls" in
    ON|1) native_tls=ON ;;
    OFF|0) native_tls=OFF ;;
    *) echo "PS5_NATIVE_TLS must be ON/OFF or 1/0" >&2; exit 2 ;;
esac
app=${APP_DIR:-"$HOME/work/ps5-rpcs3-app"}
vulkan=${PS5_VULKAN_DIR:-"$HOME/work/PS5_Vulkan"}
links=${RPCS3_LINK_INPUTS:-"${RPCS3_BUILD_DIR:-$HOME/work/rpcs3-build}/rpcs3-link-inputs.txt"}
launcher_build=${TILE_LAUNCHER_BUILD_DIR:-"$HOME/work/tile-launcher"}
helper_sources=${KB_HELPER_SOURCES:-"$HOME/work/kb-rpcs3-tools"}
export LLVM_CONFIG=${LLVM_CONFIG:-/usr/lib/llvm-19/bin/llvm-config}
export PS5_CLANG=${PS5_CLANG:-/usr/bin/clang-19}
export PS5_VULKAN_DIR="$vulkan"
export APP_DIR="$app"

if [[ "$(uname -s)" != Linux ]]; then
    echo "Run in Ubuntu WSL, not Windows Git Bash." >&2
    exit 2
fi
for program in rsync git cmake ninja python3 sed; do
    command -v "$program" >/dev/null || { echo "Missing command: $program" >&2; exit 2; }
done
for path in "$PS5_CLANG" "$LLVM_CONFIG" "$repo/app/ps5/tools/build.sh" \
            "$repo/tools/iohelper/main.c" "$repo/tools/launcher/build.sh"; do
    [[ -e "$path" ]] || { echo "Missing: $path" >&2; exit 2; }
done
[[ -s "$links" ]] || { echo "RPCS3 archive list missing: $links" >&2; exit 2; }
[[ -d "$vulkan" ]] || { echo "Missing PS5_Vulkan checkout: $vulkan" >&2; exit 2; }
[[ "$app" != "$repo/app" ]] || { echo "APP_DIR must be a separate build copy." >&2; exit 2; }

echo "==> Syncing app and helper sources into WSL"
mkdir -p "$app" "$helper_sources/iohelper" "$helper_sources/launcher"
# Keep existing WSL SDK, build products and other untracked local data.
rsync -a --exclude='/.git/' --exclude='/build/' --exclude='/dist/' \
    --exclude='/.deps/' --exclude='/klog/' "$repo/app/" "$app/"
rsync -a "$repo/tools/iohelper/" "$helper_sources/iohelper/"
rsync -a "$repo/tools/launcher/" "$helper_sources/launcher/"
# Windows files may have CRLF line endings, which break bash under WSL.
find "$app/ps5" "$helper_sources/launcher" -type f -name '*.sh' -print0 |
    xargs -0 -r sed -i 's/\r$//'

# The packager reads exact licence texts from a Git revision.
# This Git commit is WSL-only; it never changes or pushes the Windows repo.
if [[ ! -d "$app/.git" ]]; then
    git init -q "$app"
fi
exclude="$app/.git/info/exclude"
mkdir -p "$(dirname "$exclude")"
touch "$exclude"
for pattern in '/.deps/' '/build/' '/dist/' '/klog/' '/*.log'; do
    grep -Fxq "$pattern" "$exclude" || printf '%s\n' "$pattern" >> "$exclude"
done
git -C "$app" add -A
if ! git -C "$app" diff --cached --quiet; then
    git -C "$app" -c user.name='KB-RPCS3 local build' \
        -c user.email='local-build@localhost' \
        commit -qm 'Snapshot WSL title sources and licences'
fi
git -C "$app" rev-parse --verify HEAD >/dev/null

echo "==> Configuring full RPCS3 title with $links"
sdk=$(bash "$app/ps5/tools/setup-sdk.sh")
# Ignore any unrelated global /opt/ps5-payload-sdk setting: the title and its
# launcher must both use the exact pinned SDK installed by setup-sdk.sh.
export PS5_PAYLOAD_SDK="$sdk"
cmake -S "$app/ps5" -B "$app/build/ps5" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$sdk/toolchain/prospero.cmake" \
    -DCMAKE_BUILD_TYPE=Release -DPS5_VULKAN_DIR="$vulkan" \
    -DRPCS3_LINK_INPUTS="$links" -DPS5_NATIVE_TLS="$native_tls"

echo "==> Compiling, linking, signing and staging title assets"
bash "$app/ps5/tools/build.sh"
dist="$app/dist/PPSA99303"
test -s "$dist/eboot.bin"

echo "==> Building write helper and game-tile launchers"
"$sdk/bin/prospero-clang" -Wall -Werror -O2 \
    -o "$dist/rpcs3ps5-io.elf" "$helper_sources/iohelper/main.c"
bash "$helper_sources/launcher/build.sh" "$launcher_build"
cp "$launcher_build/app/eboot.bin" "$dist/tile-launcher.bin"
"$sdk/bin/prospero-clang" -Wall -Werror -O2 \
    -o "$dist/rpcs3ps5-launch.elf" "$helper_sources/launcher/launch.c" \
    -lSceSystemService -lSceUserService

if [[ -s "$repo/app/examples/rpcs3ps5/data/rpcs3-config-db.json" ]]; then
    cp "$repo/app/examples/rpcs3ps5/data/rpcs3-config-db.json" \
        "$dist/rpcs3-config-db.json"
fi
echo "==> Verifying title files"
for file in eboot.bin rpcs3ps5-text.bin rpcs3ps5-io.elf \
    rpcs3ps5-launch.elf tile-launcher.bin sce_module/libc.prx \
    sce_sys/param.json LEGAL.txt licenses/components.json; do
    [[ -s "$dist/$file" ]] || { echo "Missing: $file" >&2; exit 1; }
    echo "OK: $file"
done
du -sh "$dist"
echo "Build complete: $dist"
