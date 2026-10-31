#!/usr/bin/env python3
"""Reversible NPUB30702 scheduler comparison; launch/position the game manually."""
import argparse
import ftplib
import io
import json
from pathlib import Path
import re
import statistics
import time

ROOT = "/data/homebrew/PPSA99303/rpcs3"
CONFIG = ROOT + "/custom_configs/config_NPUB30702.yml"
MODES = {"A": "Operating System", "B": "RPCS3 Scheduler"}


def get(ftp, path):
    data = io.BytesIO()
    ftp.retrbinary("RETR " + path, data.write)
    return data.getvalue()


def replace_setting(data, key, value):
    pattern = rb"(?m)^(  " + re.escape(key.encode()) + rb": )[^\r\n]*"
    data, count = re.subn(pattern, lambda m: m[1] + value.encode(), data)
    if count != 1:
        raise ValueError(f"Expected exactly one {key}, found {count}")
    return data


def setting(text, key):
    match = re.search(r"(?m)^  " + re.escape(key) + r": ([^\r\n]*)", text)
    return match[1] if match else None


def mfc_meter_errors(text, expected):
    """Validate compiled experiment mode and the shared no-helper-probe policy."""
    markers = re.findall(r"PS5 MFCMETER: gate ([01]) helper_probes ([01])", text)
    reasons = []
    if not markers or markers[-1] != (str(expected), "0"):
        reasons.append(f"runtime MFC meter/helper mode does not match gate={expected}, probes=0")
    if setting(text, "Enable Performance Report") != "false":
        reasons.append("Performance Report must be disabled for the MFC timer experiment")
    if "PS5 SPUHELP:" in text or "PS5 SPUHELPSTAT:" in text:
        reasons.append("heavy SPU helper diagnostics present in MFC timer experiment")
    return reasons


def upload_config(ftp, wanted):
    # The console file can be owned by the title user, rather than the FTP user.
    # Preserve its permissions while temporarily allowing the transfer.
    listing = []
    ftp.retrlines("LIST " + ROOT + "/custom_configs/", listing.append)
    entries = [line.split() for line in listing if line.split()[-1:] == ["config_NPUB30702.yml"]]
    if len(entries) != 1 or not re.fullmatch(r"-[rwx-]{9}", entries[0][0]):
        raise ValueError("Cannot determine existing config permissions")
    permissions = entries[0][0][1:]
    mode = "".join(str(sum(bit for char, bit in zip(permissions[i:i+3], (4, 2, 1))
                           if char != "-")) for i in (0, 3, 6))
    ftp.sendcmd("SITE CHMOD 666 " + CONFIG)
    try:
        ftp.storbinary("STOR " + CONFIG, io.BytesIO(wanted))
        if get(ftp, CONFIG) != wanted:
            raise RuntimeError("Config read-back mismatch; restore original.yml before restarting")
    finally:
        ftp.sendcmd("SITE CHMOD " + mode + " " + CONFIG)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "apply", "capture", "restore"])
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--label", default="run1")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--expected-resolution", type=int, help="Verify active Resolution Scale percentage during capture")
    parser.add_argument("--expected-mfc-meter-gate", type=int, choices=(0, 1),
                        help="Verify compiled MFC timer mode, helper probes OFF and performance reporting OFF")
    parser.add_argument("--expected-tuning", action="append", default=[], metavar="KEY=VALUE",
                        help="Verify runtime PS5 TUNING line; repeat to check multiple keys")
    parser.add_argument("--host", default="192.168.0.137")
    parser.add_argument("--port", type=int, default=2121)
    args = parser.parse_args()
    if args.action in ("apply", "capture") and not args.mode:
        parser.error("--mode A or B is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.label):
        parser.error("--label must contain only letters, digits, underscores or hyphens")
    if not 30 <= args.seconds <= 55:
        parser.error("--seconds must be 30–55")
    folder = args.session
    with ftplib.FTP(timeout=25) as ftp:
        ftp.connect(args.host, args.port)
        ftp.login()
        if args.action == "prepare":
            folder.mkdir(parents=True, exist_ok=False)
            original = get(ftp, CONFIG)
            (folder / "original.yml").write_bytes(original)
            (folder / "before.log").write_bytes(get(ftp, ROOT + "/RPCS3.log"))
            (folder / "patch_config.yml").write_bytes(get(ftp, ROOT + "/patch_config.yml"))
            (folder / "patches.yml").write_bytes(get(ftp, ROOT + "/patches/NPUB30702_patch.yml"))
            text = original.decode("utf-8")
            for key, expected in [("Clocks scale", "100"), ("Frame limit", "60"),
                                  ("SPU XFloat Accuracy", "Approximate")]:
                if setting(text, key) != expected:
                    raise ValueError(f"Unexpected {key}; review baseline before applying")
            baseline = replace_setting(original, "SPU Block Size", "Mega")
            for mode, scheduler in MODES.items():
                (folder / f"{mode}.yml").write_bytes(
                    replace_setting(baseline, "Thread Scheduler Mode", scheduler))
            print(f"Saved original, prior log, patches and A/B variants in {folder}")
        elif args.action in ("apply", "restore"):
            target = folder / (f"{args.mode}.yml" if args.action == "apply" else "original.yml")
            wanted = target.read_bytes()
            current = get(ftp, CONFIG)
            known = [(folder / name).read_bytes() for name in ("original.yml", "A.yml", "B.yml")]
            if current not in known:
                raise ValueError("Console config changed outside this test; refusing to overwrite")
            upload_config(ftp, wanted)
            print(f"Verified {target.name} on console. Takes effect on next game launch.")
        else:
            stem = folder / f"{args.mode}-{args.label}"
            if stem.with_suffix(".log").exists():
                raise ValueError("Capture label already exists; use a new label")
            before = get(ftp, ROOT + "/RPCS3.log")
            print(f"Capturing new log windows for {args.seconds}s; keep the scene unchanged.", flush=True)
            time.sleep(args.seconds)
            after = get(ftp, ROOT + "/RPCS3.log")
            stem.with_suffix(".log").write_bytes(after)
            reasons = []
            if not after.startswith(before):
                reasons.append("log restarted or changed during capture")
            new = after[len(before):].decode("utf-8", errors="replace")
            full = after.decode("utf-8", errors="replace")
            if args.expected_mfc_meter_gate is not None:
                reasons.extend(mfc_meter_errors(full, args.expected_mfc_meter_gate))
            for key, value in [("Thread Scheduler Mode", MODES[args.mode]),
                               ("SPU Block Size", "Mega"), ("Clocks scale", "100"),
                               ("SPU XFloat Accuracy", "Approximate"), ("Frame limit", "60")]:
                if setting(full, key) != value:
                    reasons.append(f"runtime {key} does not match {value}")
            resolution = setting(full, "Resolution Scale")
            if args.expected_resolution is not None and resolution != str(args.expected_resolution):
                reasons.append(f"runtime Resolution Scale {resolution} does not match {args.expected_resolution}")
            for name in ("Unlock FPS", "ARMSX3 Approximate collision fix"):
                if not any("Applied patch" in line and f"description='{name}'" in line
                           for line in full.splitlines()):
                    reasons.append(f"missing applied patch: {name}")
            tuning_lines = [line.split("PS5 TUNING:", 1)[1].strip()
                            for line in full.splitlines() if "PS5 TUNING:" in line]
            current_tuning = {}
            if tuning_lines:
                current_tuning = dict(re.findall(r"([a-z_]+)=(-?\d+)", tuning_lines[-1]))
            for expected in args.expected_tuning:
                if not re.fullmatch(r"[a-z_]+=-?\d+", expected):
                    parser.error(f"Invalid --expected-tuning {expected}; expected KEY=VALUE")
                key, wanted = expected.split("=", 1)
                if current_tuning.get(key) != wanted:
                    reasons.append(f"runtime tuning {key}={current_tuning.get(key)} != {wanted}")
            narrow_check_rows = [int(n) for n in re.findall(r"PS5 NARROW CHECK: (\d+) mismatches", full)]
            if any(v != 0 for v in narrow_check_rows):
                reasons.append("narrow-store equivalence checker reported mismatch(es)")
            if ("spu_narrow_ls_check=1" in args.expected_tuning and not narrow_check_rows):
                reasons.append("narrow-store checker did not report a result")
            rows = re.findall(r"PS5 FPS: ([\d.]+) \| frame p50 ([\d.]+) p95 ([\d.]+) p99 ([\d.]+) ms, 1% low ([\d.]+)", new)
            rows = [list(map(float, row)) for row in rows]
            timing = [(float(a), float(b)) for a, b in re.findall(
                r"PS5 TIMING: guest/host ([\d.]+), vblank ([\d.]+)/s", new)]
            if len(rows) < 4 or len(timing) < 4:
                reasons.append("too few new FPS/timing windows; game may not be running")
            if any(abs(ratio - 1) > .03 or not 57 <= hz <= 63 for ratio, hz in timing):
                reasons.append("runtime speed or vblank outside normal-speed bounds")
            result = {"mode": args.mode, "scheduler": MODES[args.mode], "valid": not reasons,
                      "reasons": reasons, "windows": len(rows), "seconds": args.seconds,
                      "resolution_scale": resolution,
                      "mfc_meter_mode": re.findall(r"PS5 MFCMETER: gate ([01]) helper_probes ([01])", full)[-1:] or None,
                      "note": "Window summaries, not pooled frame percentiles; use the same warmed scene."}
            if rows:
                for i, key in enumerate(["fps", "p50_ms", "p95_ms", "p99_ms", "one_percent_low_fps"]):
                    result["mean_window_" + key] = round(statistics.mean(r[i] for r in rows), 2)
                result["min_window_fps"] = min(r[0] for r in rows)
            result["new_spu_compilations"] = new.count("New SPU block compiled successfully")
            result["cpu_reports"] = [line for line in new.splitlines() if "PS5 CPU:" in line]
            stem.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in result.items() if k != "cpu_reports"}, indent=2))


if __name__ == "__main__":
    main()
