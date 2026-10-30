#!/usr/bin/env bash
# Build the migrated upstream core separately from the established native build.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export SRC_DIR="$HOME/work/rpcs3-latest"
export BUILD_DIR="$HOME/work/rpcs3-build-latest"
export APP_DIR="$HOME/work/ps5-rpcs3-app-latest"
export TILE_LAUNCHER_BUILD_DIR="$HOME/work/tile-launcher-latest"
exec bash "$repo/tools/wsl-build-native.sh"
