#!/usr/bin/env bash
# Reproduce the pinned upstream migration in a NEW checkout.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export RPCS3_UPSTREAM_REV
RPCS3_UPSTREAM_REV=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_revision"])' "$here/rpcs3-latest.json")
export RPCS3_PATCH_DIR="$here/rpcs3-latest-patches"
export RPCS3_PORT_BRANCH=ps5/upstream-20261029
exec bash "$here/apply-rpcs3-patches.sh" "${1:?usage: prepare-rpcs3-latest.sh <new-checkout-directory>}"
