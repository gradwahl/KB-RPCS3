#!/usr/bin/env bash
# Experimental native-TLS core + title; keep emulated build outputs intact.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export LLVM_CONFIG=${LLVM_CONFIG:-/usr/lib/llvm-19/bin/llvm-config}
export PS5_CLANG=${PS5_CLANG:-/usr/bin/clang-19}
export BUILD_DIR=${BUILD_DIR:-"$HOME/work/rpcs3-build-native"}
export RPCS3_BUILD_DIR="$BUILD_DIR"
export RPCS3_LINK_INPUTS="$BUILD_DIR/rpcs3-link-inputs.txt"
export JOBS=${JOBS:-2}
export APP_DIR=${APP_DIR:-"$HOME/work/ps5-rpcs3-app-native"}
export TILE_LAUNCHER_BUILD_DIR=${TILE_LAUNCHER_BUILD_DIR:-"$HOME/work/tile-launcher-native"}
export PS5_NATIVE_TLS=ON
export EXTRA_CFLAGS='-fno-emulated-tls -ftls-model=initial-exec'

# Reuse the installed, pinned SDK and UI cache; build/dist stay separate.
test -d "$HOME/work/ps5-rpcs3-app/.deps"
mkdir -p "$APP_DIR"
if [[ ! -e $APP_DIR/.deps ]]; then
    ln -s "$HOME/work/ps5-rpcs3-app/.deps" "$APP_DIR/.deps"
fi

# The source checkout may have Windows line endings. Execute an LF copy of
# this script, while the app helper must retain its original repo-relative path.
core_script=$(mktemp)
trap 'rm -f "$core_script"' EXIT
sed 's/\r$//' "$repo/port/rpcs3-build.sh" > "$core_script"
CONFIGURE_ONLY=1 bash "$core_script" rpcs3_ps5
python3 - "$BUILD_DIR/CMakeCache.txt" <<'PY'
import sys
cache = open(sys.argv[1]).read().splitlines()
for language in ('C', 'CXX'):
    flags = next(line.split('=', 1)[1] for line in cache
                 if line.startswith(f'CMAKE_{language}_FLAGS:'))
    if not all(flag in flags.split() for flag in
               ('-fno-emulated-tls', '-ftls-model=initial-exec')):
        raise SystemExit(f'Native build cache has incorrect {language} flags: {flags}')
PY
[[ ${CONFIGURE_ONLY:-0} == 1 ]] && exit 0
bash "$core_script" rpcs3_ps5
bash "$repo/tools/wsl-build-app.sh"
