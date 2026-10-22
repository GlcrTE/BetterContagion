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

Run from anywhere:  py build.py [--game "D:/.../Borderlands 4"] [--speed 2.0] [--range 1.5]
"""

import argparse
import ctypes
import functools
import json
import re
import shutil
import struct
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
OODLE = TOOLS / "oo2core_9_win64.dll"

PAK_FOOTER = 221  # V11: encryption guid, encrypted, magic, version, index offset/size/hash, 5 compression names
PAK_MAGIC = 0x5A6F12E1
PAK_DELETED = -2 ** 31  # full directory index location of a delete record

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


def read_string(buf, pos):
    n = struct.unpack_from("<i", buf, pos)[0]
    pos += 4
    if n < 0:  # UTF-16, length in characters
        return buf[pos:pos - 2 * n].decode("utf-16-le").rstrip("\0"), pos - 2 * n
    return buf[pos:pos + n].decode("latin-1").rstrip("\0"), pos + n


def oodle_decompress(data, size):
    global _oodle
    if _oodle is None:
        _oodle = ctypes.CDLL(str(OODLE)).OodleLZ_Decompress
        _oodle.restype = ctypes.c_int64
        _oodle.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]
    out = ctypes.create_string_buffer(size)
    if _oodle(data, len(data), out, size, 1, 0, 0, None, 0, None, None, None, 0, 3) != size:
        sys.exit("Oodle decompression failed")
    return out.raw


_oodle = None


class Pak:
    """Read-only V11 pak with a full directory index.

    repak 0.2.3 panics on the delete records that patch paks carry since game patch 23
    (pakchunk0-Windows_23_P.pak), so reading is done here and repak only packs."""

    def __init__(self, path: Path):
        self.path = path
        with open(path, "rb") as f:
            f.seek(-PAK_FOOTER, 2)
            footer = f.read(PAK_FOOTER)
            magic, version, index_offset, index_size = struct.unpack_from("<IIQQ", footer, 17)
            if magic != PAK_MAGIC or version != 11 or footer[16]:
                raise ValueError(f"unsupported pak (version {version}, encrypted {footer[16]})")
            self.compression = [footer[61 + 32 * i:93 + 32 * i].rstrip(b"\0").decode() for i in range(5)]
            f.seek(index_offset)
            index = f.read(index_size)
            mount, pos = read_string(index, 0)
            pos += 12  # file count, path hash seed
            if struct.unpack_from("<I", index, pos)[0]:
                pos += 36  # path hash index offset, size, hash
            pos += 4
            has_fdi, fdi_offset, fdi_size = struct.unpack_from("<IQQ", index, pos)
            if not has_fdi:
                raise ValueError("no full directory index")
            pos += 40  # flag, full directory index offset, size, hash
            size = struct.unpack_from("<I", index, pos)[0]
            self.entries = index[pos + 4:pos + 4 + size]
            f.seek(fdi_offset)
            fdi = f.read(fdi_size)
        # path -> offset into self.entries, or PAK_DELETED
        self.files = {}
        pos = 4
        for _ in range(struct.unpack_from("<I", fdi, 0)[0]):
            directory, pos = read_string(fdi, pos)
            count = struct.unpack_from("<I", fdi, pos)[0]
            pos += 4
            for _ in range(count):
                file, pos = read_string(fdi, pos)
                location = struct.unpack_from("<i", fdi, pos)[0]
                pos += 4
                if location < 0 and location != PAK_DELETED:
                    raise ValueError("non-encoded entries are not supported")
                path = (mount + directory.lstrip("/") + file).removeprefix("../../../").lstrip("/")
                self.files[path] = location

    def read(self, path):
        pos = self.files[path]
        bits = struct.unpack_from("<I", self.entries, pos)[0]
        pos += 4
        compression = (bits >> 23) & 0x3f
        block_count = (bits >> 6) & 0xffff
        block_size = bits & 0x3f
        if bits & (1 << 22):
            sys.exit(f"{self.path.name}: {path} is encrypted")
        if block_size == 0x3f:
            block_size = struct.unpack_from("<I", self.entries, pos)[0]
            pos += 4
        else:
            block_size <<= 11

        def var_int(bit):
            nonlocal pos
            fmt = "<I" if bits & (1 << bit) else "<Q"
            value = struct.unpack_from(fmt, self.entries, pos)[0]
            pos += struct.calcsize(fmt)
            return value

        offset, uncompressed = var_int(31), var_int(30)
        compressed = var_int(29) if compression else uncompressed
        # Data follows a copy of the entry header; block offsets are relative to the entry
        start = 53 + (4 + 16 * block_count if compression else 0)
        if block_count > 1:
            sizes = struct.unpack_from(f"<{block_count}I", self.entries, pos)
        else:
            sizes = (compressed,)
        with open(self.path, "rb") as f:
            f.seek(offset + start)
            data = f.read(sum(sizes))
        if not compression:
            return data
        if self.compression[compression - 1] != "Oodle":
            sys.exit(f"{self.path.name}: {path} uses {self.compression[compression - 1]} compression")
        if block_count == 1:
            return oodle_decompress(data, uncompressed)
        out, pos = [], 0
        for i, size in enumerate(sizes):
            out.append(oodle_decompress(data[pos:pos + size], min(block_size, uncompressed - i * block_size)))
            pos += size
        return b"".join(out)


@functools.cache
def open_pak(path: Path):
    return Pak(path)


def ncs_path(name):
    return f"{NCS_DIR}/Nexus-Data-{name}.ncs"


def mod_ships(pak: Path, name):
    try:
        location = open_pak(pak).files.get(ncs_path(name))
    except ValueError:  # other pak versions (some older mods): repak reads those
        result = subprocess.run([str(REPAK), "list", str(pak)], capture_output=True, text=True)
        return result.returncode == 0 and ncs_path(name) in result.stdout.splitlines()
    return location is not None and location != PAK_DELETED


def read_ncs(pak: Path, name):
    try:
        return open_pak(pak).read(ncs_path(name))
    except ValueError:
        return subprocess.run([str(REPAK), "get", str(pak), ncs_path(name)], capture_output=True, check=True).stdout


def locate(paks_dir: Path, name):
    """Pak to read <name>.ncs from.

    Another installed mod that ships the file wins, so its changes are kept. Otherwise the newest pakchunk0
    patch pak that contains it (later versions overwrite earlier ones, a delete record removes the file)."""
    game = None
    for pak in sorted(paks_dir.glob("pakchunk0-Windows_*_P.pak"), key=pak_version):
        location = open_pak(pak).files.get(ncs_path(name))
        if location is not None:
            game = None if location == PAK_DELETED else pak
    mods = [pak for pak in sorted(paks_dir.rglob("*.pak"))
            if not pak.name.startswith(("pakchunk", *OWN_PAKS)) and mod_ships(pak, name)]
    if len(mods) > 1:
        sys.exit(f"{name}: several mods ship it, cannot merge: {[m.name for m in mods]}")
    if mods:
        # A mod built before the game patch carries the old table and would undo the patch's changes
        if game and mods[0].stat().st_mtime < game.stat().st_mtime:
            sys.exit(f"{name}: {mods[0].name} is older than {game.name}, rebuild that mod first")
        return mods[0]
    return game


def extract(paks_dir: Path, name, raw_dir: Path):
    source = locate(paks_dir, name)
    if source is None:
        sys.exit(f"{name}.ncs not found in game paks")
    print(f"{name}: {source.name}")
    (raw_dir / f"{name}.ncs").write_bytes(read_ncs(source, name))


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
    ap.add_argument("--range", type=float, default=1.5,
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
