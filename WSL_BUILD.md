# Reproducible PS5 title build on Ubuntu WSL

This path is for a **personal build** of KB-RPCS3. The combined executable has an unresolved GPL-2.0-only/GPL-3.0-or-later compatibility issue: **do not redistribute it**. The original alpha's console testing was performed on PS5 firmware 13.60, not every firmware.

## Tested layout (Ubuntu 24.04 WSL)

- Windows Git checkout is accessible from WSL, e.g. `/mnt/c/Users/Callum/Documents/GitHub/KB-RPCS3`.
- Patched RPCS3 is in `~/work/rpcs3`. Its completed PS5 build is `~/work/rpcs3-build`.
- `~/work/rpcs3-build/rpcs3-link-inputs.txt` lists the core archives (165 in the October 2026 build).
- PS5_Vulkan and its native RADV build are in `~/work/PS5_Vulkan`.
- PS5_PayloadSDK fork is in `~/work/PS5_PayloadSDK`, with the commit pinned by `app/ps5/tools/setup-sdk.sh`.
- Clang 19, LLVM 19, CMake, Ninja, Python 3, Git and rsync are available.

The title build **does not rebuild RPCS3**. If the core has not compiled, run the repository's `port/rpcs3-build.sh` with your configured PS5 toolchain first. Keep `EXTRA_CFLAGS` empty and use emulated TLS.

## One command to build the title and helpers

From **WSL Ubuntu**:

```bash
cd /mnt/c/Users/Callum/Documents/GitHub/KB-RPCS3

export LLVM_CONFIG=/usr/lib/llvm-19/bin/llvm-config
export PS5_CLANG=/usr/bin/clang-19
export PS5_VULKAN_DIR="$HOME/work/PS5_Vulkan"
export RPCS3_BUILD_DIR="$HOME/work/rpcs3-build"

bash tools/wsl-build-app.sh 2>&1 | tee "$HOME/work/kb-rpcs3-full-build.log"
```

For strict failure detection when piping to `tee`, use `set -o pipefail` in your WSL shell first.

The script copies `app/` into `~/work/ps5-rpcs3-app` and the two helper source directories into `~/work/kb-rpcs3-tools`. It **preserves** `~/work/ps5-rpcs3-app/.deps/`, `build/`, `dist/` and the existing Git metadata so an incremental rebuild is possible. It converts CRLF in the copied Bash scripts to LF. It uses CMake to link the archive list explicitly with `PS5_NATIVE_TLS=OFF`.

The notices stage obtains title licence files with `git show`, so the script creates/updates a **local Git snapshot in the WSL build copy**, not a commit in your Windows source checkout or GitHub repository. The UI kit's licence is read from its exact pinned revision in either the sibling `PS5_VKHomebrewUI` checkout or the bare `.deps/PS5_VKHomebrewUI.git` archive cache.

The final title is `~/work/ps5-rpcs3-app/dist/PPSA99303/` and contains `eboot.bin`, `rpcs3ps5-text.bin`, `rpcs3ps5-io.elf`, `rpcs3ps5-launch.elf`, `tile-launcher.bin`, assets, runtime, notices and metadata. All nine required files are checked at the end.

## Experimental native TLS

From Ubuntu WSL, in the Windows source checkout:

```bash
set -o pipefail
bash tools/wsl-build-native.sh 2>&1 | tee "$HOME/work/kb-rpcs3-native-build.log"
```

This rebuilds the RPCS3 core in `~/work/rpcs3-build-native` with
`-fno-emulated-tls -ftls-model=initial-exec`, then builds the title with
`PS5_NATIVE_TLS=ON` and an explicit PT_TLS linker layout. The title output is
`~/work/ps5-rpcs3-app-native/dist/PPSA99303/`. The normal emulated build
directories are preserved. The installed SDK and UI dependency cache are shared.
Use `CONFIGURE_ONLY=1 bash tools/wsl-build-native.sh` to check core configuration.
Core compiler output is in `~/work/rpcs3-build-native.log`.

The PS5_Vulkan converter must include writable TLS sections in its file-backed
data PT_LOAD and preserve their actual alignment. The local WSL converter already
has this change; its source patch is saved at
`port/ps5-native-tls-converter.patch` for reproducing it elsewhere. Rebuild
PS5_Vulkan's `ps5-native-tool` after applying that patch.

The existing local native probe log reports correct initial values, isolation,
thread reuse, signals and destructor counts with this converter fix. This is
evidence for testing the full emulator, not a claim that RPCS3 is fixed.
The native title uses the same title ID as the emulated title: deploying it will
replace that console installation. Keep the emulated output for reverting.

## Build errors addressed

| Previous error | Permanent source fix |
|---|---|
| `no public SDK stub exports required symbol radv_EnumeratePhysicalDevices`, `sqtt_GetDeviceProcAddr`, `wsi_CreateInstance` | `app/ps5/tools/link-title.sh` passes LLVM LLD 19's `--no-dynamic-linker` to the final PIE link. This excludes missing **weak** ELF imports from the dynamic symbol table; required strong SDK imports still need actual definitions. |
| Missing `radv_ps5_stat_waits` or other RADV wait counters | `app/ps5/src/ps5_tuning.c` supplies four **weak zero-initialised diagnostic counters**; a real strong driver definition takes precedence. |
| `stage-notices.py` fails on `git rev-parse HEAD` | WSL helper creates a local source snapshot, enabling `git show` to stage exact licence text. |
| `stage-notices.py` fails reading UI kit `4451c26:LICENSE` | Packager can read the pinned commit from the bare UI kit cache created by `setup-kit.sh`. |
| Repeated/manual link setup and separate helper compilations | WSL helper reconfigures `RPCS3_LINK_INPUTS` and builds the title, I/O helper and tile launchers in one run. |
| Outdated SDK missing `ps5_vrange_reserve_at` / `commit` / `decommit` | Existing SDK pin `adc8dd795ada7bf696cd98748aae463a3970ffbb` is required; don't replace it with older SDK forks. |

The pinned SDK must be present in `~/work/PS5_PayloadSDK`; it may need to be fetched separately. These source fixes do not prove the resulting executable is stable on PS5 firmware 13.20.

## Committing the Windows source fixes

Only the Windows checkout's changed source and documentation should be committed. The WSL build copy's Git history is temporary packaging metadata. In your Windows Git checkout:

```bash
git status --short
git add app/ps5/tools/link-title.sh \
        app/ps5/src/ps5_tuning.c \
        app/ps5/tools/stage-notices.py \
        tools/launcher/build.sh \
        tools/wsl-build-app.sh \
        WSL_BUILD.md
git diff --cached --check
git diff --cached --stat
git commit -m "fix(ps5): make WSL title linking and packaging reproducible"
```

Review the staged diff first, and keep any unrelated local modifications unstaged.
