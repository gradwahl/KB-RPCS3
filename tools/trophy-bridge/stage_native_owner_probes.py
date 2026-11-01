#!/usr/bin/env python3
"""Stage uninstalled 20-second native PS5 per-game title-ownership probes.

Produces two (or more) independent, signed, OFFLINE PS5 title-folder prototypes
in a NEW PC-side directory only. The SELF probe does NOT run RPCS3 or register
trophies. The output is deliberately never uploaded, installed, or deployed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

PS5_TITLE = re.compile(r"^PPSA8\d{4}$")
SERIAL = re.compile(r"^[A-Z0-9]{9}$")
NPWR = re.compile(r"^NPWR\d{5}_\d{2}$")
SIGNED_SELF_MAGIC = bytes.fromhex("4f153d1d")
MAX_BIN_SIZE = 8 * 1024 * 1024


class StageError(ValueError):
    pass


def encode_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Generate tiny, unbranded RGB PNGs using standard Python only."""
    if not 32 <= width <= 3840 or not 32 <= height <= 2160:
        raise StageError("PNG size out of range")
    if not all(isinstance(c, int) and 0 <= c <= 255 for c in rgb):
        raise StageError("Invalid color")
    def block(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    row = b"\0" + bytes(rgb) * width
    compressor = zlib.compressobj(8)
    compressed = bytearray()
    for _ in range(height):
        compressed.extend(compressor.compress(row))
    compressed.extend(compressor.flush())
    return (
        b"\x89PNG\r\n\x1a\n" +
        block(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
        block(b"IDAT", bytes(compressed)) +
        block(b"IEND", b"")
    )


def check_plan(plan: dict) -> list[dict]:
    if (plan.get("schema") != "kb-rpcs3-safe-native-trophy-plan/v1" or
        plan.get("registration_mode") != "DISABLED_OFFLINE_PLANNING_ONLY" or
        plan.get("console_firmware") != "13.20" or
        plan.get("writes_console") is not False or
        plan.get("creates_npbind") is not False):
        raise StageError("Plan is not a verified, safe 13.20 offline-only mapping")
    games = plan.get("games")
    if not isinstance(games, list) or not 1 <= len(games) <= 20:
        raise StageError("Invalid game plan")
    seen_ids, seen_serials, seen_npwr = set(), set(), set()
    for game in games:
        title = game.get("ps5_title_id")
        serial = game.get("ps3_serial")
        npwr = game.get("npwr")
        if not all([
            isinstance(title, str) and PS5_TITLE.fullmatch(title),
            isinstance(serial, str) and SERIAL.fullmatch(serial),
            isinstance(npwr, str) and NPWR.fullmatch(npwr),
            title not in seen_ids, serial not in seen_serials, npwr not in seen_npwr,
            game.get("registration_allowed") is False,
            game.get("ps5_title_status") == "PLAN_ONLY_NOT_INSTALLED",
            game.get("ps5_trophy_menu_ready") is False,
            game.get("identity_evidence") in {
                "installed_PS3_TROPDIR",
                "verified_ISO_PS3_GAME_PARAM_SFO_and_TROPDIR",
            }
        ]):
            raise StageError("Game title plan is ambiguous, unsafe, or already installed")
        seen_ids.add(title); seen_serials.add(serial); seen_npwr.add(npwr)
    return games


def make_param(game: dict) -> dict:
    title_id = game["ps5_title_id"]
    name = str(game.get("ps3_game", ""))[:96]
    if not name or any(ord(c) < 32 for c in name):
        raise StageError("Invalid title name")
    return {
        "ageLevel": {"default": 0},
        "applicationCategoryType": 0,
        "applicationDrmType": "free",
        "attribute": 0,
        "attribute2": 0,
        "attribute3": 524352,
        "conceptId": title_id[4:],
        "contentBadgeType": 1,
        "contentId": f"UP9000-{title_id}_00-RPCS3OWNER000000",
        "contentVersion": "01.000.000",
        "downloadDataSize": 0,
        "gameIntent": {"permittedIntents": [{"intentType": "launchActivity"}]},
        "localizedParameters": {
            "defaultLanguage": "en-US",
            "en-US": {"titleName": f"{name} — OWNER TEST (NOT TROPHIES)"},
        },
        "masterVersion": "01.00",
        "pubtools": {
            "creationDate": "2026-11-01 00:00:00",
            "loudnessSnd0": "-28.00",
            "toolVersion": "2.00",
        },
        "requiredSystemSoftwareVersion": "0x0000000000000000",
        "sdkVersion": "0x0000000000000000",
        "titleId": title_id,
        "versionFileUri": "",
    }


def stage(plan: dict, built_app: Path, destination: Path, only_title: str | None = None,
          probe_purpose: str = "lifecycle") -> dict:
    games = check_plan(plan)
    if only_title is not None:
        if not PS5_TITLE.fullmatch(only_title):
            raise StageError("Invalid single-test PS5 title ID")
        games = [game for game in games if game["ps5_title_id"] == only_title]
        if len(games) != 1:
            raise StageError("Requested PS5 title is missing or ambiguous")
    if probe_purpose not in ("lifecycle", "shared_root"):
        raise StageError("Unrecognized owner-probe purpose")
    if destination.exists():
        raise StageError("Output exists; refusing to overwrite or delete any title")
    eboot = built_app / "eboot.bin"
    libc = built_app / "sce_module" / "libc.prx"
    for file in (eboot, libc):
        if not file.is_file() or not 1024 <= file.stat().st_size <= MAX_BIN_SIZE:
            raise StageError(f"Missing/oversize native title binary: {file}")
    with eboot.open("rb") as stream:
        if stream.read(4) != SIGNED_SELF_MAGIC:
            raise StageError("Missing PS5 signed-title SELF header")
    if plan.get("used_ps5_title_ids_seen") and set(plan["used_ps5_title_ids_seen"]) & {x["ps5_title_id"] for x in games}:
        raise StageError("Planned native title collides with known existing PS5 title")

    destination.mkdir(parents=True, exist_ok=False)
    output = {"schema": "kb-rpcs3-native-owner-proof-stage/v1",
              "firmware": plan["console_firmware"],
              "status": "HOST_ONLY_UNDEPLOYED_NO_TROPHY_REGISTRATION",
              "probe_purpose": probe_purpose,
              "ps5_files_changed": False, "registration_allowed": False,
              "events_delivered": 0, "apps": []}
    for idx, game in enumerate(games):
        tid = game["ps5_title_id"]
        folder = destination / tid
        (folder / "sce_sys").mkdir(parents=True)
        (folder / "sce_module").mkdir()
        shutil.copyfile(eboot, folder / "eboot.bin")
        shutil.copyfile(libc, folder / "sce_module/libc.prx")
        param = make_param(game)
        if len(param["contentId"]) != 36:
            raise StageError("PS5 contentId must be 36 characters")
        (folder / "sce_sys/param.json").write_text(
            json.dumps(param, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (folder / "native-owner.txt").write_text(
            f"{tid} {game['npwr']} {game['ps3_serial']}\n", encoding="ascii"
        )
        (folder / "sce_sys/icon0.png").write_bytes(
            encode_png(512, 512, (75 + idx * 17, 42, 85 + idx * 20))
        )
        (folder / "sce_sys/pic0.png").write_bytes(
            encode_png(3840, 2160, (30 + idx * 8, 15, 36 + idx * 10))
        )
        filehashes = {
            path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()
        }
        output["apps"].append({
            "title_id": tid,
            "ps3_serial": game["ps3_serial"],
            "npwr": game["npwr"],
            "source": ("SIGNED_OWNER_LIFECYCLE_PROBE_NO_RPCS3"
                       if probe_purpose == "lifecycle" else
                       "SIGNED_SHARED_ROOT_READ_ONLY_PROBE_NO_RPCS3"),
            "contains_trophy_assets": False,
            "has_game_emulator": False,
            "probe_auto_exits_after_seconds": 20,
            "file_sha256": filehashes,
        })
    (destination / "STAGE-ONLY-NO-INSTALL.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native-plan", type=Path, required=True)
    ap.add_argument("--signed-app", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only-title", help="Stage only one explicitly planned PPSA8xxxx title")
    ap.add_argument("--probe-purpose", choices=("lifecycle", "shared_root"), default="lifecycle")
    args = ap.parse_args()
    try:
        mapping = json.loads(args.native_plan.read_text(encoding="utf-8"))
        result = stage(mapping, args.signed_app, args.out, args.only_title, args.probe_purpose)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        ap.exit(1, f"Native-title host stage blocked: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
