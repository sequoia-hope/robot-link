#!/usr/bin/env python3
"""regen.py -- check the board as it stands, and remake what the pages show.

    python3 tools/regen.py            # check, assembly packet, viewer, page status
    python3 tools/regen.py --check    # only the checks; writes nothing but reports

The checks are KiCad's DRC with the project's rules (and schematic parity),
KiCad's ERC, the drawn schematic's netlist against tools/circuit.py, and
boardvis on the IPC-2581 export. Anything outstanding is printed and the exit
status is non-zero, so a page is not rebuilt around a board that fails.

Then pcbview (~/Software/pcbview) builds the viewer as pcbview.toml says and
writes it into index.html, and the status line there is counted off the board.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
HW = ROOT / "hardware/comms"
PCB, SCH = HW / "comms.kicad_pcb", HW / "comms.kicad_sch"
PAGE = ROOT / "index.html"
PCBVIEW = Path.home() / "Software/pcbview/bin/pcbview"
sys.path.insert(0, str(TOOLS))


def run(*cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def checks():
    """{name: (count outstanding, what was counted)}"""
    import circuit
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        run("kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity",
            "--all-track-errors", "-o", tmp / "drc.json", PCB)
        d = json.loads((tmp / "drc.json").read_text())
        out["DRC"] = (len(d.get("violations", ())), "violations")
        out["unconnected"] = (len(d.get("unconnected_items", ())), "pads")
        # A net with no label on the sheets has KiCad's name for it there and
        # circuit.py's on the board; that is a difference of names, and the
        # connections themselves are the netlist check below.
        out["parity"] = (sum(p["type"] != "net_conflict" for p in d.get("schematic_parity", ())),
                         "differences from the schematic, net names apart")
        run("kicad-cli", "sch", "erc", "--format", "json", "--severity-all",
            "-o", tmp / "erc.json", SCH)
        e = json.loads((tmp / "erc.json").read_text())
        out["ERC"] = (sum(len(s.get("violations", ())) for s in e.get("sheets", ())), "violations")
    r = run(sys.executable, TOOLS / "schdraw.py", "--check")
    out["netlist"] = (0 if r.returncode == 0 and "matches" in r.stdout else 1,
                      "drawn schematic vs circuit.py")
    r = run(sys.executable, TOOLS / "assembly.py")
    m = re.search(r"boardvis: (\d+) errors", r.stdout)
    out["assembly"] = (int(m.group(1)) if m else 1, "boardvis errors")
    out["_counts"] = (len(circuit.board()), len(circuit.nets()))
    return out


def page(res):
    import circuit
    parts, nets = res["_counts"]
    saved = datetime.datetime.fromtimestamp(PCB.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    line = (f"<p><b>Rev {circuit.REV}</b>, board saved {saved}: {parts} parts, {nets} nets; "
            f"DRC {res['DRC'][0]} violations, {res['unconnected'][0]} unconnected, "
            f"{res['parity'][0]} differences from the schematic (net names apart); ERC {res['ERC'][0]}; "
            f"boardvis {res['assembly'][0]} errors. Not fabricated.</p>")
    s = PAGE.read_text()
    s, n = re.subn(r"(<!-- status:begin -->).*?(<!-- status:end -->)",
                   lambda m: f"{m.group(1)}\n    {line}\n    {m.group(2)}", s, flags=re.S)
    if n != 1:
        sys.exit("index.html: no status markers")
    PAGE.write_text(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="only the checks")
    a = ap.parse_args()
    res = checks()
    bad = 0
    for k, (n, what) in res.items():
        if not k.startswith("_"):
            print(f"  {k:12} {n:3}  {what}")
            bad += n
    if bad:
        sys.exit("regen: the board does not pass; nothing rebuilt")
    if a.check:
        return
    page(res)
    r = run(PCBVIEW, "build", ROOT / "pcbview.toml", cwd=ROOT)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:])
    if r.returncode:
        sys.exit("regen: pcbview failed")


if __name__ == "__main__":
    main()
