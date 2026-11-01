# PS3 → PS5 trophy bridge (KB-RPCS3, research prototype)

**Status 2026-11-01:** PS3 trophy extraction, PS5-format UCP/UDS prototypes, live firmware detection, PS3 ISO identity verification, and a safe per-game native title plan have been implemented and tested. **Native PS5 Trophies menu registration has NOT been implemented or proven.** PSN sync is explicitly out of scope.

See [NATIVE_REGISTRATION_RESEARCH.md](NATIVE_REGISTRATION_RESEARCH.md) for a detailed, up-to-date engineering handoff.

## Console findings

**The actual connected PS5 is firmware 13.20** (read-only `kern.sdk_version=0x13200006`, kernel build `r228185/releases/13.20 Apr 16 2026`). The 13.60 in KB-RPCS3 INSTALL.md is only the reference development machine. The emulated PS3 firmware 4.93 shown by RPCS3 is unrelated.

| PS3 game | Real PS3 serial | Trophy set | Planned PS5 title | Trophies |
|---|---|---|---|---:|
| GTA IV | NPUB30702 | NPWR00132_00 | PPSA88395 | 66 |
| Dead Island Riptide | BLES01739 | NPWR03806_00 | PPSA85381 | 36 |

Dead Island's PS3 serial was obtained by reading its **real ISO9660 `PS3_GAME/PARAM.SFO` and `TROPDIR`**, not by guessing from the filename or XISO33006 launcher cache. Those planned PS5 IDs are collision-checked **but not installed**. Existing KB-RPCS3 per-game tiles hand off execution to the main PS5 title PPSA99303.

## Prerequisites

- Python 3.12+ with standard library (no third-party Python packages).
- To compile the optional PS5 firmware probe: WSL Ubuntu with `/opt/ps5-payload-sdk`, make.
- The PS5 FTP listener on port 2121 and the existing authorized ELF loader on port 9021 for live checks.

## 1. Read-only trophy snapshot and exporter

```powershell
python tools/trophy-bridge/ftp_readonly_snapshot.py --host <PS5_IP> --port 2121 --dry-run
python tools/trophy-bridge/ftp_readonly_snapshot.py --host <PS5_IP> --port 2121
python tools/trophy-bridge/export_rpc3_trophies.py --input "C:\Temp\rpcs3-trophies" --output "C:\Temp\kb-trophy-export"
```

Use the copied trophy sets' `source` directory from the generated snapshot as the exporter input. A game export contains `manifest.json` and icon images. No PS3 trophy states/timestamps are modified. Private data is kept outside Git.

## 2. PS5 trophy/UDS prototype generation (offline)

```powershell
python tools/trophy-bridge/build_ps5_ucp_prototype.py --manifest "C:\Temp\kb-trophy-export\NPWR01234_00\manifest.json" --output "C:\Temp\prototype\trophy00.ucp" --dry-run
python tools/trophy-bridge/build_paired_uds_prototype.py --manifest "C:\Temp\kb-trophy-export\NPWR01234_00\manifest.json" --out "C:\Temp\paired-prototype" --dry-run
```

Remove `--dry-run` only to create fresh PC-local output locations (existing outputs are never overwritten). The paired generator makes an experimental `trophy00.ucp` plus `uds00.ucp`, with hypothetical `_UnlockTrophy` stats/events. It does **not** generate `npbind.dat`, register anything on the PS5, or import Sony trophies.

## 3. Firmware probe (read-only console API)

Build in WSL:

```bash
cd tools/trophy-bridge
make -f Makefile.firmware PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk
```

Run from Windows/PowerShell:

```powershell
python tools/trophy-bridge/run_firmware_probe.py --host <PS5_IP> --port 9021 --elf tools/trophy-bridge/ps5_fw_probe.elf --output "C:\Temp\ps5-firmware-live.json"
```

The small native payload calls only `sysctlbyname` for `kern.sdk_version` and `kern.version`, then prints a result. It does not require firmware offsets or write any PS5 files. The Python runner checks the output's completion marker, BCD version and matching kernel release. Treat every future firmware update as a new compatibility-check requirement.

## 4. Confirm a PS3 ISO's real title/NPWR with bounded FTP reads

```powershell
python tools/trophy-bridge/read_ps3_iso_identity_ftp.py --host <PS5_IP> --port 2121 --iso-filename "Your Game.iso" --output "C:\Temp\ps3-iso-identity.json"
```

The script reads only a handful of ISO9660 directory records and the small `PS3_GAME/PARAM.SFO` through the FTP `REST` command. It is hard-limited to 16 ranges and 256 KiB total, **never transfers the entire game ISO**. Fails if the source isn't a readable PS3 ISO9660 disc image or lacks a matching NPWR directory.

## 5. Read-only native inventory and safe title plan

```powershell
python tools/trophy-bridge/preflight_native_registration.py --host <PS5_IP> --port 2121 --manifests "C:\Temp\kb-trophy-export" --ucp-prototypes "C:\Temp\ucp-prototypes" --report "C:\Temp\preflight.json"
python tools/trophy-bridge/plan_native_title_registration.py --host <PS5_IP> --port 2121 --preflight "C:\Temp\preflight.json" --firmware "C:\Temp\ps5-firmware-live.json" --iso-identity "C:\Temp\ps3-iso-identity.json" --out "C:\Temp\planned-ps5-titles.json"
```

The plan mirrors KB-RPCS3's tile allocation (CRC32 serial, modulo 10,000, then next available), cross-checks existing title inventory to avoid collisions, maps installed PS3 games via TROPDIR and ISO games via verified ISO contents, and **sets `registration_allowed: false` for every game**. No titles are installed.

## 6. Inspect an existing real native PS5 trophy binding (read-only)

```powershell
python tools/trophy-bridge/inspect_existing_npbind.py --host <PS5_IP> --port 2121 --title PPSA06225
```

The inspector reports only non-secret `npbind.dat` format information and the unsealed NPWR ID. It does not decrypt, authenticate, copy, reuse, fabricate or install a binding. An existing game's binding is **not** transferable to an emulated PS3 game. The reference PS5 game had 40 matching trophy conditions and UDS stats/rules.

## 7. Read-only 13.20 trophy-library fingerprints and PS3 unlock changes

The firmware-bound fingerprint tool reads only four native system libraries into RAM, verifies PS5 ELF structure and computes SHA-256 checksums. This helps compare exact versions when researching future 13.20 support; it does **not** resolve/execute trophy API symbols or establish firmware patch offsets.

```powershell
python tools/trophy-bridge/fingerprint_native_trophy_runtime.py --host <PS5_IP> --firmware "C:\Temp\ps5-firmware-live.json" --report "C:\Temp\ps5-trophy-runtime-fingerprint.json"
```

The live 13.20 report confirms `libSceNpTrophy2.sprx` (124,416 B), `libSceNpTrophy.sprx` (230,220 B), `libSceNpManager.sprx` (476,816 B) and `libSceIpmi.sprx` (92,476 B). All passed ELF structure checks; their SHA-256 values are in the private report outside Git. **Library presence does not imply synthetic trophy registration support.**

`poll_ps3_trophy_changes.py` reads the current RPCS3 `TROPUSR.DAT` records via FTP and compares them to your copied baseline manifests. It produces a PC-only event diff with new PS3 unlocks and flags unexpected reversals. It does not touch the console's native trophy service, deliver events to it, modify PS3 records, or connect to PSN.

```powershell
python tools/trophy-bridge/poll_ps3_trophy_changes.py --host <PS5_IP> --manifests "C:\Temp\kb-trophy-export" --native-plan "C:\Temp\planned-ps5-titles.json" --report "C:\Temp\offline-ps3-trophy-diff.json"
```

Live 2026-11-01 results: GTA IV remains **1/66**, Dead Island Riptide remains **0/36**, **zero new unlocks**, zero reversals. This validates the *read-only ingestion path*, not native PS5 trophy delivery. Both reports are outside Git under `KB-RPCS3-Trophy-Bridge-Data`.

## Test

```powershell
python -m unittest discover -s tools/trophy-bridge/tests -v
```

**73 offline tests pass**, including ISO9660 fixtures, firmware output consistency, collision handling, broken/duplicate trophy data, UCP integrity, UDS cross-references, binding TLV parsing and refusal to treat prototype packages as registerable.

## 8. Per-game native title-lifecycle prototype (PC-only, NOT installed)

`native_owner_probe.c` is a minimal **20-second native PS5 title**. It reports an identifying line to klog, stays alive briefly, and exits using the normal PS5 title exit service. It makes no trophy API calls, doesn't launch RPCS3, writes no console files, and never connects to the network.

The standalone title was compiled and signed on the PC with the **project's pinned PS5 SDK**. The generic SDK was missing the required native-title library; the pinned SDK completed the build. `build_native_owner_probe.sh` refuses to overwrite existing host build directories and never sends anything to the PS5.

```bash
PS5_PAYLOAD_SDK=/home/callum/work/PS5_Vulkan/.deps/native/ps5-payload-sdk \
  bash tools/trophy-bridge/build_native_owner_probe.sh /path/to/new/private-build
```

`stage_native_owner_probes.py` reads only the verified firmware 13.20, registration-disabled PS5 title plan and generates separate **host-only** test-title folders for `PPSA88395` (GTA IV) and `PPSA85381` (Dead Island Riptide), with the signed SELF, `libc.prx`, unique `param.json`, `native-owner.txt`, and standard-size PNG assets. No emulator and no `npbind.dat`, `trophy00.ucp`, or `uds00.ucp` are included.

```powershell
python tools/trophy-bridge/stage_native_owner_probes.py --native-plan "C:\Temp\planned-ps5-titles.json" --signed-app "C:\Temp\native-owner-build\app" --out "C:\Temp\new-native-owner-test-staging"
```

Local staged output: `Documents\KB-RPCS3-Trophy-Bridge-Data\kb-rpcs3-trophies_2026-11-01_02-34-49\native-owner-titles-stage-20261101` with a `STAGE-ONLY-NO-INSTALL.json` checksum manifest. Signed `eboot.bin` for this local build: **194,691 bytes**, SHA-256 `a63a0f481f4f69056109f2fca210517cd1db31cb3afbdecb28bd8277d100fe21`.

**Historical staging note:** The owner packages were originally built on the PC only. Since then, GTA IV's `PPSA88395` *disposable native owner test* was installed, launched, and unregistered on the real PS5; Dead Island's `PPSA85381` owner-test package remains PC-only. See the live test section below. Future installation requires a specific approved safe deployment and rollback test.

**Full emulator under separate title is still nontrivial.** The existing tile process exits before launching the shared `PPSA99303`. `library.cpp` assumes `PS5_APP_ROOT/rpcs3`, while RPCS3 patches `0012` (config/executable), `0028` (JIT/code mirror), `0031` (write helper) and the I/O helper's fixed `/data/homebrew/PPSA99303/rpcs3` root also assume the original app or path. Simply copying the main emulator executable to a new tile without coordinated storage/mirror/write-helper changes is not safe. A native-title owner probe cannot register PS3 trophies by itself.
## 9. LIVE PS5 title-lifecycle test: passed, disposable app unregistered (2026-11-01)

At the user's explicit request, **one** signed disposable owner-test title (`PPSA88395`, label `GTA IV — OWNER TEST (NOT TROPHIES)`) was staged, installed via FTP + ShadowMountPlus on a **13.20** PS5, launched from Games Home with Chiaki, and subsequently removed. The standalone process returned to Games Home after its 20-second bounded lifetime. Live `pslist.elf` captured **PID 255 `eboot.bin`**, and ShadowMountPlus independently tied PID 255 to native PS5 title **PPSA88395**, without launching the common emulator `PPSA99303`.

The guarded installer `deploy_owner_test_ftp.py` is **hardcoded to this single test ID and the six exact files**. It refuses overwrites or unverified converted binaries. The PS5 FTP daemon may return signed PS5 SELF/PRX files as decrypted ELF from `RETR`; the proper verification compares **entry point and all `PT_LOAD`/`PT_TLS` segment metadata and bytes** to the locally extracted original, not entire file hashes. The other files use exact SHA-256. The installer makes `eboot.bin`/`libc.prx` executable and sends `sce_sys/param.json` **last**. Two earlier attempts were safely rolled back **before** registration after strict whole-file checks detected the converted-format readbacks; final install succeeded once both binary conversions were verified.

**Cleanup order is critical.** ShadowMountPlus reinstalled the test app after the first stock PS5 Options → Delete while its `/data/homebrew/PPSA88395` source still existed. `cleanup_owner_test_source.py` then verified the owner marker and title metadata, exact whitelisted six-file tree and two independent stopped-process lists, removed **only** the test source, and left system paths untouched. A second stock PS5 Options → Delete unregistered the now-unbacked title. Final read-only checks showed `/data/homebrew/PPSA88395`, `/system_data/priv/appmeta/PPSA88395` and `/user/app/PPSA88395` absent, no `eboot.bin` running, and no purple owner-test tile on Games Home. An **empty** `/system_ex/app/PPSA88395` directory remained accessible; it was not manually modified. The unrelated PS Store tile briefly displayed a `Can't load` message during navigation, without evidence that the test caused it.

The complete private PC-side record is `Documents\KB-RPCS3-Trophy-Bridge-Data\kb-rpcs3-trophies_2026-11-01_02-34-49\native-owner-test-final-result-20261101.json` (with original install/source-removal reports alongside it). No original emulator files, games, saves, PS5 trophy data, profile data or PSN activity were touched. The Dead Island test title was **never installed**.

**Meaning:** One independent native PS5 title process is now proven workable on firmware 13.20. **This is not a PS5 trophy registration**. We still need a real per-game emulator process/storage architecture, a legitimate matching NPWR binding, native trophy registration on 13.20, and guest PS3 trophy event delivery. Do not add synthetic trophy or binding files to the verified owner test unless a separate, reversible integration has first been demonstrated.
## 10. Separate native-title emulator: shared-data sandbox probe and paired-binary audit (PC-only, 2026-11-01)

The previous live test proved that PS5 firmware **13.20** can run a separate native `PPSA88395` owner title. The *actual emulator* cannot yet run under that ID, because it expects `/app0/rpcs3` as its config/game root, `/app0/rpcs3ps5-text.bin` as the executable instruction mirror, and `/app0/rpcs3ps5-io.elf` as the PS3 write helper. The helper separately targets the original `/data/homebrew/PPSA99303/rpcs3` directory. Do not copy live trophy or save folders, fabricate symlinks or change the live helper merely to work around these paths.

New `native_shared_root_probe.c` is a signed, bounded **read-only** PS5 owner-title app. It validates the exact `PPSA88395` owner marker and uses only `stat`/`opendir`/`closedir` to check the existing shared PS3 data root and its `dev_hdd0` child, the local `/app0/rpcs3` path, and `stat` on local executable/mirror/helper paths. It neither reads PS3 profile/trophy files nor writes anything, starts the emulator, creates symlinks, loads plugins or calls the PS5 trophy service. It exits normally after 20 seconds. This checks data access from *inside the independent title sandbox*; ordinary FTP access does not establish that.

Build in WSL Ubuntu-24.04 with the project's **pinned SDK**:

```bash
bash tools/trophy-bridge/build_shared_root_probe.sh /path/to/new-private-build-directory
```

Stage **only** GTA IV's owner test title, on the PC:

```powershell
python tools/trophy-bridge/stage_native_owner_probes.py --native-plan "C:\Temp\planned-ps5-titles.json" --signed-app "C:\Temp\shared-root-probe-build\app" --only-title PPSA88395 --probe-purpose shared_root --out "C:\Temp\new-shared-root-probe-stage"
```

Successful **host-only build**: signed PS5 `eboot.bin` 195,891 bytes, SHA-256 `121f82bd9919d9c86e591593079139813f5bf456eb67be2d73a4cc2b680039a6`. Private stage: `KB-RPCS3-Trophy-Bridge-Data/kb-rpcs3-trophies_2026-11-01_02-34-49/shared-root-owner-stage-20261101`. It has exactly one native title, no game emulator, no trophy files and `registration_allowed: false`. **Not installed; no change to the PS5.** Any later deployment requires separate user approval and the same source-first/PS5-UI-second uninstall order verified in the previous test.

An independent `plan_emulator_owner_pair.py` validates the **real patch-76 emulator signed SELF + converted ELF + code mirror**, all host-side: signed SELF magic, independently extracted signed SELF's complete ELF `PT_LOAD`/`PT_TLS` segments versus the build ELF (including entry point), and the code mirror's 28-byte header, address, size and SHA-256 of the actual executable segment. It never packages or installs the emulator. To reproduce the audit:

```bash
python3 tools/trophy-bridge/plan_emulator_owner_pair.py --native-plan /path/to/planned-ps5-titles.json --elf /home/callum/work/framegen0076-local-guard-20261031/eboot.elf --self /home/callum/work/framegen0076-local-guard-20261031/eboot.bin --mirror /home/callum/work/framegen0076-local-guard-20261031/rpcs3ps5-text.bin --extracted-self /path/to/decrypted-same-signed-eboot.elf --report /path/to/new-private-report.json
```

Live-installed patch-76 build archive **passed**: signed SELF 116,092,046 bytes, SHA-256 `a88da9f889520925379f75c36fc1b9a3cc3465b70fa2ad4856da53cda467b719`; text mirror 74,680,081 bytes, SHA-256 `880f15b704b721e8974fee40468541680e62fb94c5da52b081e38389ecdce957`. The signed SELF extraction matches **every** converted ELF LOAD/TLS segment, and the mirror's 74,680,053 instruction bytes match the executable segment exactly. The complete host-side evidence is saved in `host-emulator-owner-pair-audit-20261101-v2.json` under the same private data folder.

**Status is deliberately `HOST_ONLY_PAIR_VERIFIED_NOT_DEPLOYABLE`.** In-title shared-data access is still unmeasured; `/app0/rpcs3` mapping and helper paths are not implemented for the new title; valid native trophy binding and registration for firmware 13.20 remain unavailable. This audit is an executable identity/integrity result, **not a PS5 emulator boot or native trophy test**. 73 offline tests pass.
## Remaining blocker

The public [PS5-PHU-Trophy-System](https://github.com/ArkSama/PS5-PHU-Trophy-System) documents firmware patch support through **12.70**, not this console's **13.20**. Our UCP/UDS prototypes contain only untrusted synthetic definitions. A real native PS5 trophy-list install additionally requires a Sony-accepted, title-specific `npbind.dat`, a per-game active PS5 trophy owner, and firmware-appropriate SceShellCore/trophy-service registration. None of those is verified on 13.20.

**Do not upload the generated archives to system/profile trophy folders, recycle another game's protected binding, or apply 12.70 SceShellCore patch offsets on 13.20.** No PS5 system/trophy files were modified by this work; the only console-side execution was the read-only firmware probe.

Private host outputs (original trophy states, icon assets and research archives) live outside Git under:

`C:\Users\Callum\Documents\KB-RPCS3-Trophy-Bridge-Data\kb-rpcs3-trophies_2026-11-01_02-34-49`
