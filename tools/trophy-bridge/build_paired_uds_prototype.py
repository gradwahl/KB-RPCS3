#!/usr/bin/env python3
"""EXPERIMENTAL offline paired PS5 trophy/UDS UCP prototypes.

Synthesizes local UDS stat definitions and event extraction rules for each PS3
non-platinum trophy. Intended ONLY for interoperability research: these files
are NOT Sony-authorized/signed, have no npbind.dat, cannot register as-is,
and do not unlock anything on the PS5 or PSN. No console communication.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_ps5_ucp_prototype import (
    build_trophy_entries,
    inspect_ucp,
    pack_ucp,
    UcpFormatError,
)

NPWR_PATTERN = re.compile(r"NPWR[0-9]{5}_[0-9]{2}")


def _json(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def uds_files(manifest: dict) -> dict[str, bytes]:
    commid = manifest.get("communication_id")
    if not isinstance(commid, str) or not NPWR_PATTERN.fullmatch(commid):
        raise UcpFormatError("Invalid NPWR ID")
    trophies = manifest.get("trophies")
    if not isinstance(trophies, list) or not trophies or len(trophies) > 4096:
        raise UcpFormatError("Invalid trophy list")
    stats, rules = [], []
    seen_ids = set()
    for trophy in trophies:
        tid = trophy.get("id")
        if not isinstance(tid, int) or not 0 <= tid <= 9999 or tid in seen_ids:
            raise UcpFormatError(f"Invalid trophy ID: {tid}")
        seen_ids.add(tid)
        if trophy.get("grade") == "platinum":
            continue
        stat_id = 1000 + tid
        name = f"_autoGenTrophy_{tid:04d}"
        source_id = f"{tid:04d}"
        stats.append({
            "statId": stat_id,
            "definitionGroup": "autoGenTrophy",
            "sourceId": source_id,
            "statName": name,
            "origin": "console",
            "dataType": "uint64",
            "aggregation": "count",
            "maxValue": "1",
            "minValue": "0",
            "initialValue": "0",
        })
        rules.append({
            "ruleId": stat_id,
            "definitionGroup": "autoGenTrophy",
            "sourceId": source_id,
            "condition": {
                "eventName": "_UnlockTrophy",
                "property": {"path": "$._trophy_id", "comparator": "==",
                             "value": str(tid)},
            },
            "action": {"output": {"statId": stat_id, "statName": name,
                                  "sourceId": source_id}},
        })
    events = [{
        "eventName": "_UnlockTrophy",
        "eventType": "custom",
        "definitionGroup": "trophy",
        "properties": [{"dataType": "int32", "property": "$._trophy_id"}],
    }]
    return {
        "enum_definition.json": _json({
            "schemaVersion": "1.1",
            "npCommunicationId": commid,
            "enumDefinitionRevision": 1,
            "enumArray": [],
        }),
        "events_definition.json": _json({
            "configurationId": 1,
            "events": events,
            "nextOffset": 0,
            "previousOffset": 0,
            "totalItemCount": len(events),
        }),
        "stats_definition.json": _json({
            "schemaVersion": "1.1",
            "npCommunicationId": commid,
            "statsDefinitionRevision": 1,
            "statDefinitionArray": stats,
        }),
        "stats_extraction.json": _json({
            "schemaVersion": "1.1",
            "npCommunicationId": commid,
            "statsExtractionRevision": 1,
            "statsExtractionRuleArray": rules,
        }),
    }


def validate_links(trophy_files: dict[str, bytes], uds: dict[str, bytes]) -> dict:
    conf = json.loads(trophy_files["tropconf.json"])
    stats = json.loads(uds["stats_definition.json"])
    extraction = json.loads(uds["stats_extraction.json"])
    stat_ids = {str(s["statId"]) for s in stats["statDefinitionArray"]}
    rule_stats = {str(rule["action"]["output"]["statId"]) for rule in extraction["statsExtractionRuleArray"]}
    condition_ids = {t["unlockCondition"]["udsStatId"]
                     for t in conf["trophies"] if "unlockCondition" in t}
    if stat_ids != rule_stats or stat_ids != condition_ids:
        raise UcpFormatError("Unmatched trophy and UDS stat references")
    if any("unlockCondition" not in t for t in conf["trophies"] if t["grade"] != "P"):
        raise UcpFormatError("Non-platinum trophy lacks synthetic UDS condition")
    return {
        "trophies": len(conf["trophies"]),
        "stat_definitions": len(stat_ids),
        "extraction_rules": len(rule_stats),
        "ids_linked": True,
    }


def build_pair(manifest_path: Path) -> tuple[bytes, bytes, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "kb-rpcs3-ps3-trophy-export/v1":
        raise UcpFormatError("Not an RPCS3 trophy export")
    trophy_files = build_trophy_entries(manifest_path, experimental_uds_conditions=True)
    uds = uds_files(manifest)
    links = validate_links(trophy_files, uds)
    trophy_bytes, uds_bytes = pack_ucp(trophy_files), pack_ucp(uds)
    inspect_ucp(trophy_bytes)
    inspect_ucp(uds_bytes)
    return trophy_bytes, uds_bytes, links


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path,
                        help="New output directory for BOTH prototype UCPs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.out.exists() and not args.dry_run:
            raise UcpFormatError("Output directory already exists; no overwrites allowed")
        trophy, uds, links = build_pair(args.manifest)
        if not args.dry_run:
            args.out.mkdir(parents=True, exist_ok=False)
            (args.out / "trophy00.ucp").write_bytes(trophy)
            (args.out / "uds00.ucp").write_bytes(uds)
        print(json.dumps({
            "status": "OFFLINE_SYNTHETIC_UDS_RESEARCH_ONLY_NOT_REGISTERABLE",
            "destination": str(args.out),
            "trophy_ucp_bytes": len(trophy),
            "uds_ucp_bytes": len(uds),
            "dry_run": args.dry_run,
            "validation": links,
            "binding": "MISSING_SONY_NPBIND",
            "event_provider": "NOT_IMPLEMENTED",
        }, indent=2))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"paired UDS prototype: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
