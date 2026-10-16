"""Build BetterContagion: Loveless' Contagion spread orbs fly faster and look for targets farther away.

When an enemy with Contagion dies, green orbs (LightProjectile_Corpohacker_Contagion_ContagionSpread,
variants _2 to _10 inherit from it) home in on new enemies. Two NCS values control this:
  light_projectile0    LightProjectile_Corpohacker_Contagion_ContagionSpread  speed  (vanilla 1200 cm/s)
  gbx_ue_data_table0   DataTable_Corpohacker_ActionSkill_Contagion  Contagion_MaxSpreadDistance  (vanilla 4000 cm)

gbx_ue_data_table0 is also shipped by VehiclesReimagined. If another installed mod ships it, that copy is used
as the base so its changes are kept, and this pak (_1001_P) loads after it.

Pipeline:
  1. Find the source copy of each NCS file (installed mod, else the newest pakchunk0 patch pak).
  2. Decode NCS -> JSON with ncs_parser.
  3. Patch the fields.
  4. Encode JSON -> NCS, re-decode to verify, and pack an unencrypted .pak.

Run from anywhere:  py build.py [--game "D:/.../Borderlands 4"] [--speed 2.0] [--range 2.0]
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
WORK = ROOT / "work"
DIST = ROOT / "dist"

REPAK = TOOLS / "repak.exe"
NCS_PARSER = TOOLS / "ncs_parser.exe"
NCS_OUTPUT = TOOLS / "output"  # ncs_parser always writes next to its binary

PAK_NAME = "BetterContagion_1001_P.pak"
OWN_PAKS = ("BetterContagion",)  # never use our own (older) builds as a source
DEFAULT_GAME = Path("D:/Games/SteamLibrary/steamapps/common/Borderlands 4")
NCS_DIR = "Engine/Content/_NCS"

PROJ_FILE = "light_projectile0"
PROJ_ENTRY = "lightprojectile_corpohacker_contagion_contagionspread"
TABLE_FILE = "gbx_ue_data_table0"
TABLE_ENTRY = "datatable_corpohacker_actionskill_contagion"
TABLE_ROW = "Contagion_MaxSpreadDistance"

VANILLA_SPEED = 1200.0
VANILLA_RANGE = 4000.0


def run(args, **kw):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)
    if result.returncode != 0:
        sys.exit(f"command failed: {args}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def pak_version(pak: Path):
    m = re.search(r"_(\d+)_P\.pak$", pak.name)
    return int(m.group(1)) if m else -1


def pak_has(pak: Path, name):
    result = subprocess.run([str(REPAK), "list", str(pak)], capture_output=True, text=True)
    return result.returncode == 0 and f"{NCS_DIR}/Nexus-Data-{name}.ncs" in result.stdout.splitlines()


def locate(paks_dir: Path, name):
    """Pak to read <name>.ncs from.

    Another installed mod that ships the file wins, so its changes are kept. Otherwise the newest pakchunk0
    patch pak that contains it (later versions overwrite earlier ones)."""
    mods = [pak for pak in sorted(paks_dir.rglob("*.pak"))
            if not pak.name.startswith(("pakchunk", *OWN_PAKS)) and pak_has(pak, name)]
    if len(mods) > 1:
        sys.exit(f"{name}: several mods ship it, cannot merge: {[m.name for m in mods]}")
    if mods:
        return mods[0]
    found = None
    for pak in sorted(paks_dir.glob("pakchunk0-Windows_*_P.pak"), key=pak_version):
        if pak_has(pak, name):
            found = pak
    return found


def extract(paks_dir: Path, name, raw_dir: Path):
    source = locate(paks_dir, name)
    if source is None:
        sys.exit(f"{name}.ncs not found in game paks")
    print(f"{name}: {source.name}")
    data = subprocess.run([str(REPAK), "get", str(source), f"{NCS_DIR}/Nexus-Data-{name}.ncs"],
                          capture_output=True, check=True).stdout
    (raw_dir / f"{name}.ncs").write_bytes(data)


def entry(table, key):
    top = next(iter(table))
    for record in table[top]["records"]:
        for e in record["entries"]:
            if key in e:
                return e[key]["value"]
    sys.exit(f"entry {key} not found")


def speed_cell(table):
    return entry(table, PROJ_ENTRY)["speed"]


def range_cell(table):
    for row in entry(table, TABLE_ENTRY)["data"]["value"]:
        row = row["value"]
        if row["row_name"]["value"] == TABLE_ROW:
            return row["row_value"]["value"]["value"]
    sys.exit(f"row {TABLE_ROW} not found")


def check_children(table):
    """The _2.._10 variants must inherit the speed, otherwise they would need their own patch."""
    top = next(iter(table))
    for record in table[top]["records"]:
        for e in record["entries"]:
            for key, body in e.items():
                if key.startswith(PROJ_ENTRY + "_") and "speed" in body["value"]:
                    sys.exit(f"{key} sets its own speed, update the build")


def set_cell(cell, value, vanilla, what):
    old = float(cell["value"])
    if old != vanilla:
        print(f"  note: {what} is {old:g} in the source, not vanilla {vanilla:g}")
    cell["value"] = f"{value:.6f}"
    print(f"  {what}: {old:g} -> {value:g}")
    return cell["value"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--speed", type=float, default=2.0, help="multiplier for the spread orb speed (vanilla 1200 cm/s)")
    ap.add_argument("--range", type=float, default=2.0,
                    help="multiplier for the distance spread orbs look for new targets (vanilla 4000 cm)")
    args = ap.parse_args()

    paks_dir = args.game / "OakGame/Content/Paks"
    if not paks_dir.is_dir():
        sys.exit(f"Paks folder not found: {paks_dir}")

    shutil.rmtree(WORK, ignore_errors=True)
    raw_dir, enc_dir, ncs_dir = WORK / "raw", WORK / "encode", WORK / "pak" / NCS_DIR
    for d in (raw_dir, enc_dir, ncs_dir):
        d.mkdir(parents=True)

    for name in (PROJ_FILE, TABLE_FILE):
        extract(paks_dir, name, raw_dir)

    # Decode
    shutil.rmtree(NCS_OUTPUT, ignore_errors=True)
    run([NCS_PARSER, raw_dir], cwd=TOOLS)
    json_dir = NCS_OUTPUT / "json"

    # Patch
    tables = {n: json.loads((json_dir / f"{n}.json").read_text(encoding="utf-8")) for n in (PROJ_FILE, TABLE_FILE)}
    check_children(tables[PROJ_FILE])
    expected = {
        PROJ_FILE: set_cell(speed_cell(tables[PROJ_FILE]), VANILLA_SPEED * args.speed, VANILLA_SPEED, "spread orb speed"),
        TABLE_FILE: set_cell(range_cell(tables[TABLE_FILE]), VANILLA_RANGE * args.range, VANILLA_RANGE,
                             "max spread distance"),
    }
    for n, table in tables.items():
        (enc_dir / f"{n}.json").write_text(json.dumps(table), encoding="utf-8")
        shutil.copy(json_dir / f"{n}_metadata.json", enc_dir / f"{n}_metadata.json")

    # Encode
    shutil.rmtree(NCS_OUTPUT, ignore_errors=True)
    run([NCS_PARSER, enc_dir], cwd=TOOLS)
    for n in tables:
        shutil.copy(NCS_OUTPUT / "ncs" / f"{n}.ncs", ncs_dir / f"Nexus-Data-{n}.ncs")

    # Verify: re-decode and compare the patched fields
    shutil.rmtree(NCS_OUTPUT, ignore_errors=True)
    run([NCS_PARSER, ncs_dir], cwd=TOOLS)
    readers = {PROJ_FILE: speed_cell, TABLE_FILE: range_cell}
    for n, value in expected.items():
        check = json.loads((NCS_OUTPUT / "json" / f"Nexus-Data-{n}.json").read_text(encoding="utf-8"))
        if readers[n](check)["value"] != value:
            sys.exit(f"verification failed: {n}")
    shutil.rmtree(NCS_OUTPUT, ignore_errors=True)

    # Pack
    DIST.mkdir(exist_ok=True)
    out = DIST / PAK_NAME
    out.unlink(missing_ok=True)
    run([REPAK, "pack", "--version", "V11", "--mount-point", "../../../", WORK / "pak", out])
    print(f"built {out}\nverification ok")


if __name__ == "__main__":
    main()
