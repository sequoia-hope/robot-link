#!/usr/bin/env python3
"""assembly.py -- the assembler's packet: IPC-2581, and the answers beside it.

    python3 tools/assembly.py            # export, write the sidecar, check
    python3 tools/assembly.py --packet   # ... and boardvis's PDF packet

hardware/comms/assembly/comms.xml is KiCad's IPC-2581 export of the board as
it stands (not tracked: it is remade from the board). Beside it,
comms.boardvis.json is what boardvis (~/Software/boardvis) asks of the author:
how an operator recognises pin 1 on each part that can go in the wrong way
round, and where that answer came from. The answers are the table below, the
part numbers hardware/parts/lcsc.csv.

An entry whose source says "package convention" was NOT read off that part's
own data sheet; it is what the package family does, and is to be checked
against the reel before it is relied on.
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import circuit as SCH  # noqa: E402

PCB = ROOT / "hardware/comms/comms.kicad_pcb"
OUT = ROOT / "hardware/comms/assembly"
XML = OUT / "comms.xml"
SIDECAR = OUT / "comms.boardvis.json"
LCSC = ROOT / "hardware/parts/lcsc.csv"
BOARDVIS = Path.home() / "Software/boardvis"

CONVENTION = "package convention, not read off this part's own data sheet"

# keyed by value, as circuit.py writes it
ANSWERS = {
    "RP2350A": dict(
        pin1Evidence="A dot on the package top, beside the logo and part number, marks pin 1; "
                     "pins count anticlockwise seen from above. The centre pad underneath is "
                     "ground and must be soldered. On this board the part is turned 180 degrees "
                     "from Raspberry Pi's reference board: pin 1 is at the lower right.",
        evidenceSource="RP2350 datasheet, package markings and the QFN-60 pin list",
        datasheetUrl="https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf"),
    "3u3": dict(
        pin1Evidence="Pin 1 is the end with the polarity dot printed on the body. It is a wound "
                     "inductor with a marked winding direction, and the dot goes to pad 1, the "
                     "footprint's own dot.",
        evidenceSource="Raspberry Pi, 'Hardware design with RP2350', the core supply inductor",
        datasheetUrl="https://datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf",
        tapeOrientation="Abracon reels this part with the winding dots aligned; a substitute may "
                        "not be. Do not substitute.",
        noAlternates=True),
    "W25Q16JVUXIQ": dict(
        pin1Evidence="Pin 1 (/CS) is the corner with the dot on the package top. The centre pad "
                     "underneath is soldered.",
        evidenceSource="Winbond W25Q16JV, USON 2x3 pad configuration; the dot is " + CONVENTION,
        datasheetUrl="https://www.winbond.com/resource-files/w25q16jv%20spi%20revh%2004082019%20plus.pdf",
        tapeOrientation="Not known; check the reel."),
    "ST60A3H1": dict(
        pin1Evidence="The terminal A1 corner is identified on the package top (figure 32: a mark "
                     "in one corner, beside the 1.95 x 0.9 mm data-matrix code). There is no ball "
                     "at A1 itself: row A has balls only in columns 3 to 5. Row A is the edge "
                     "AWAY from the board edge here, row N toward it, so the A1 corner is the "
                     "inner right corner of the package seen from above (the part is "
                     "placed turned 180 degrees).",
        evidenceSource="ST DS14598 rev 4, section 7.1 (ball A1 corner, table 38 seen from below) "
                       "and 7.2 (package marking)",
        datasheetUrl="https://www.st.com/resource/en/datasheet/st60a3h1.pdf",
        note="The antenna is in this package and radiates off the board's top edge. Turned 180 "
             "degrees it would still solder down on some balls and would not work."),
    "PTN3222GM": dict(
        pin1Evidence="Pin 1 is the corner marked on the package top; the twelve lands are four "
                     "on each long side and two on each short side.",
        evidenceSource="NXP PTN3222 data sheet rev 1.2, XQFN12 outline; the top mark is " + CONVENTION,
        datasheetUrl="https://www.nxp.com/docs/en/data-sheet/PTN3222.pdf",
        tapeOrientation="Not known; check the reel."),
    "TXS0108E": dict(
        pin1Evidence="Pin 1 is at the dot or dimple on the package top, at the end with the "
                     "moulded notch or bevelled long edge.",
        evidenceSource="TI TXS0108E data sheet, PW package; the mark is " + CONVENTION,
        datasheetUrl="https://www.ti.com/lit/ds/symlink/txs0108e.pdf",
        tapeOrientation="Not known; check the reel."),
    "TLV75518P": dict(
        pin1Evidence="Three leads on one side, two on the other: it only fits one way.",
        evidenceSource="TI TLV755P data sheet, DBV package",
        datasheetUrl="https://www.ti.com/lit/ds/symlink/tlv755p.pdf"),
    "AMS1117-3.3": dict(
        pin1Evidence="Three leads on one side, the tab on the other: it only fits one way.",
        evidenceSource="AMS1117 data sheet, SOT-223",
        datasheetUrl="http://www.advanced-monolithic.com/pdf/ds1117.pdf"),
    "USBLC6-2SC6": dict(
        pin1Evidence="Three leads a side, so it can be fitted turned 180 degrees. Pin 1 is found "
                     "from the marking code on the top (UL26), read upright: pin 1 is lower left.",
        evidenceSource="ST USBLC6-2 data sheet, SOT23-6L; reading the mark is " + CONVENTION,
        datasheetUrl="https://www.st.com/resource/en/datasheet/usblc6-2.pdf",
        note="The part is symmetric about its centre for the two I/O pairs (1 and 6, 3 and 4), "
             "but turned round it puts VBUS on the ground pin: 2 is GND, 5 is VBUS.",
        tapeOrientation="Not known; check the reel."),
    "TS3USB221A": dict(
        pin1Evidence="Pin 1 is the corner marked on the package top. Ten lands: four on each "
                     "long side, one on each short side.",
        evidenceSource="TI TS3USB221A data sheet (SCDS263), RSE package; the top mark is " + CONVENTION,
        datasheetUrl="https://www.ti.com/lit/ds/symlink/ts3usb221a.pdf",
        tapeOrientation="Not known; check the reel."),
    "MMBT3904": dict(
        pin1Evidence="Two leads on one side, one on the other: it only fits one way.",
        evidenceSource="SOT-23, " + CONVENTION,
        datasheetUrl="https://www.onsemi.com/pdf/datasheet/mmbt3904lt1-d.pdf"),
    "12MHz": dict(
        pin1Evidence="Pads 1 and 3 are the crystal, diagonally opposite; 2 and 4 are the can. "
                     "Turned 180 degrees it is the same circuit, so either way round works.",
        evidenceSource="2520 four-pad crystal, " + CONVENTION,
        datasheetUrl="https://datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf",
        tapeOrientation="Does not matter: see above."),
    "green": dict(
        pin1Evidence="Pin 1 is the cathode. On the part it is the end with the green mark seen "
                     "from above, and the bar of the T or the point of the triangle on the "
                     "underside. On the board it is the end with the silkscreen bar.",
        evidenceSource="0603 chip LED, " + CONVENTION + ". Makers differ: confirm on the reel.",
        datasheetUrl="https://www.lcsc.com/product-detail/C12624.html",
        tapeOrientation="Not known; check the reel."),
    "blue": dict(
        pin1Evidence="Pin 1 is the cathode. On the part it is the end with the mark seen from "
                     "above, and the bar of the T or the point of the triangle on the underside. "
                     "On the board it is the end with the silkscreen bar.",
        evidenceSource="0603 chip LED, " + CONVENTION + ". Makers differ: confirm on the reel.",
        datasheetUrl="https://www.lcsc.com/product-detail/C2288.html",
        tapeOrientation="Not known; check the reel."),
    "USB-C": dict(
        pin1Evidence="Set by the shell and its four posts: the opening faces the board's bottom "
                     "edge. It cannot be fitted turned round.",
        evidenceSource="mechanical",
        datasheetUrl="https://www.lcsc.com/product-detail/C165948.html"),
    "LEFT": dict(
        pin1Evidence="A plain pin strip, the same either way round. Pin 1 is the square pad, "
                     "nearest the antenna end of the board.",
        evidenceSource="mechanical",
        datasheetUrl="https://www.lcsc.com/product-detail/C22465876.html"),
    "RIGHT": dict(
        pin1Evidence="A plain pin strip, the same either way round. Pin 1 is the square pad, "
                     "nearest the antenna end of the board.",
        evidenceSource="mechanical",
        datasheetUrl="https://www.lcsc.com/product-detail/C22465876.html"),
    "OV2640": dict(
        pin1Evidence="Set by the housing: on the BACK of the board, contacts toward the antenna "
                     "end, the hinged lid and the opening toward the USB end. It cannot be "
                     "fitted turned round (its two side tabs are behind the contacts).",
        evidenceSource="Hirose FH12 series drawing; mechanical",
        datasheetUrl="https://www.hirose.com/product/en/products/FH12/FH12-24S-0.5SH(55)/",
        note="The camera module is not part of the assembly. It goes in afterwards, the "
             "tail's contacts toward the board and the lens away from it."),
    "XC6206P282MR": dict(
        pin1Evidence="Two leads on one side, one on the other: it only fits one way.",
        evidenceSource="SOT-23; Torex XC6206 data sheet for the pin order (1 VSS, 2 VOUT, 3 VIN)",
        datasheetUrl="https://www.torexsemi.com/file/xc6206/XC6206.pdf",
        note="On the back. A second-source part is listed: check that its pin order is Torex's."),
    "ME6216A13M3G": dict(
        pin1Evidence="Two leads on one side, one on the other: it only fits one way.",
        evidenceSource="SOT-23; Microne ME6216 data sheet for the pin order (1 VSS, 2 VOUT, 3 VIN)",
        datasheetUrl="https://www.lcsc.com/datasheet/C236662.pdf",
        note="On the back."),
    "SWD": dict(
        pin1Evidence="Set by the housing: the opening faces off the board's right edge, and the "
                     "two side tabs are soldered.",
        evidenceSource="mechanical",
        datasheetUrl="https://www.lcsc.com/product-detail/C2845362.html"),
}


def part_numbers():
    rows = csv.DictReader(l for l in LCSC.open() if not l.startswith("#"))
    return {(r["value"], r["footprint"]): r for r in rows}


def findings():
    r = subprocess.run([sys.executable, "-m", "boardvis", "check", str(XML), "--json",
                        "--fail-on", "error"], cwd=BOARDVIS, capture_output=True, text=True)
    return json.loads(r.stdout)["findings"]


def sidecar():
    """The answers, under the keys boardvis itself gives the parts."""
    lcsc = part_numbers()
    by_value = {}
    for c in SCH.board():
        by_value.setdefault(c.value, c.fp.split(":")[1])
    SIDECAR.unlink(missing_ok=True)
    parts, comps = {}, {}
    for f in findings():
        key = f.get("partKey") or ""
        value = key.rsplit("|", 1)[-1]
        if f["check"] == "dnp-reason":
            what = "A fiducial mark" if "Fiducial" in key else "A mounting hole"
            comps[f["ref"]] = {"dnpReason": what + ": there is no part."}
        elif value in ANSWERS and key not in parts:
            row = lcsc[(value, by_value[value])]
            parts[key] = dict(ANSWERS[value], mpn=f"{row['mpn']} (LCSC {row['lcsc']})")
    doc = {"schema": 1, "design": XML.name, "locales": ["en"],
           "notes": {"provenance": __doc__.split("\n\n")[-1].replace("\n", " ").strip()},
           "parts": parts, "components": comps}
    SIDECAR.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--packet", action="store_true", help="also write boardvis's PDF packet")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kicad-cli", "pcb", "export", "ipc2581", "--version", "C", "--units", "mm",
                    "-o", str(XML), str(PCB)], check=True, capture_output=True)
    sidecar()
    left = findings()
    for f in left:
        print(f"  {f['level']:5} {f['ref']:6} {f['title']}")
    worst = sum(f["level"] == "error" for f in left)
    print(f"boardvis: {worst} errors, {len(left) - worst} other findings; "
          f"{SIDECAR.relative_to(ROOT)}")
    if a.packet:
        subprocess.run([sys.executable, "-m", "boardvis", "packet", str(XML), "-o",
                        str(OUT / "comms_assembly.pdf")], cwd=BOARDVIS, check=True)
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
