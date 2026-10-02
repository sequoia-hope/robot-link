#!/usr/bin/env python3
"""schlayout.py -- the comms board's sheets, laid out by hand.

tools/schdraw.py draws; this says where. One function a sheet: each part's
place and turn, the wires worth drawing (a supply rail and what hangs off it,
a pair between two parts that face each other), and labels for what leaves a
block. What a layout leaves alone schdraw finishes -- a supply or ground
symbol on a power pin, a label on a signal pin, a no-connect flag.

    python3 tools/schlayout.py            # check every sheet against the netlist
    python3 tools/gen_board.py --no-pcb --force   # write them

Three sheets, as circuit.SHEETS has them:

    01_mcu         the RP2350A as Raspberry Pi's minimal design draws it,
                   the flash, buttons, debug connector, headers
    02_link        repeater -- ST60A3H1 -- translator, left to right, the way
                   the signals go
    03_usb_power   connector, ESD, the two switches; the two regulators

Coordinates are grid units of 2.54 mm, y down.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit as CIR
import schdraw

# Nets that leave a sheet get a global label; the rest stay local.
def global_nets():
    seen = {}
    for c in CIR.board():
        for n in c.nets.values():
            if n:
                seen.setdefault(n, set()).add(c.sheet)
    # ... and so does everything on the headers: a column of pin names reads
    # better as sixteen flags than as flags and bare names mixed
    hdr = {n for c in CIR.board() if c.ref in ("J2", "J3") for n in c.nets.values() if n}
    return {n for n, sh in seen.items() if len(sh) > 1} | hdr


def notes(*paras, width=64):
    import textwrap
    return "\\n".join("\\n".join(textwrap.wrap(p, width)) for p in paras)


# -------------------------------------------------------------------- MCU ---
def mcu(s):
    s.block("RP2350A", 26, 20, 104, 73)
    u = s.place("U1", 75, 50, fields=(-12, -20.5))

    # supplies along the top: DVDD on +1V1, everything else on +3V3
    for n in ("39", "23", "6"):
        s.wire(u[n], u[n].go(0, -2))
    s.wire((66, 28), (68, 28))
    s.power(s.g(67, 28), "+1V1")
    for n in ("54", "45", "38", "30", "20", "11", "1", "53", "44"):
        s.wire(u[n], u[n].go(0, -2))
    s.wire((71, 28), (81.5, 28))
    s.power(s.g(75.5, 28), "+3V3")

    # the core regulator: AVDD through its RC, VIN on +3V3 with its own
    # 4u7, LX through L1 to +1V1, which FB senses
    s.wire(u["46"], (58, 34.5), (58, 26), (48, 26))
    s.place("R5", 46.5, 26, rot=90, fields="above")
    s.power(s["R5"]["1"], "+3V3", stub=1)
    s.place("C9", 52, 27.5, fields="right")
    s.flag(s.g(55, 26), "VREG_AVDD", stub=1)
    s.wire(u["49"], (56, 35.5), (56, 31), (53.5, 31))
    s.power(s.g(56, 31), "+3V3")
    s.place("C6", 53.5, 32.5, fields="left")
    s.place("L1", 50, 37.5, rot=90, fields="below")
    s.wire(u["48"], s["L1"]["2"])
    s.wire(u["50"], (44, 36.5), (44, 37.5))
    s.wire(s["L1"]["1"], (28.5, 37.5))
    for ref, x in (("C7", 42), ("C10", 37.5), ("C8", 33), ("C11", 28.5)):
        s.place(ref, x, 39, fields="right")
    s.power(s.g(31, 37.5), "+1V1")
    s.flag(s.g(40, 37.5), "+1V1", stub=1)
    s.power(u["47"], "GND", stub=1)

    # QSPI: labels here and at the flash
    for n in ("60", "57", "59", "58", "55", "56"):
        s.label(u[n], stub=2)

    # crystal: XIN straight in, XOUT through R2
    s.wire(u["21"], (50, 51), (50, 55))
    y = s.place("Y1", 53, 55, fields=(-1.6, -2.2, "left"))
    s.wire((50, 55), y["1"])
    s.place("C3", 50, 56.5, fields="left")
    s.place("R2", 59, 53, rot=270, fields="below")
    s.wire(u["22"], s["R2"]["1"])
    s.wire(s["R2"]["2"], (56, 53), (56, 55), y["3"])
    s.place("C4", 56, 56.5, fields="right")

    for n in ("26", "24", "25"):
        s.label(u[n], stub=2)

    # USB: 27R in series with each data line, at the chip
    s.wire(u["52"], (89, 33), (89, 29))
    s.wire(u["51"], (90, 34), (90, 32))
    s.place("R7", 93, 29, rot=270, fields="above")
    s.place("R8", 93, 32, rot=270, fields="below")
    s.wire((89, 29), s["R7"]["2"])
    s.wire((90, 32), s["R8"]["2"])
    s.wire(s["R7"]["1"], (98, 29))
    s.label(s.g(98, 29), "USB_DP", stub=0, d=(1, 0))
    s.wire(s["R8"]["1"], (98, 32))
    s.label(s.g(98, 32), "USB_DM", stub=0, d=(1, 0))
    for p in u.pins.values():
        if p.d == (1, 0) and p.net and p.num not in ("52", "51"):
            s.label(p, stub=2)

    # IOVDD decoupling as the reference has it: one 100n a supply pin
    s.block("3V3 decoupling", 60, 9, 101, 18)
    s.wire((63, 12), (95, 12))
    s.power(s.g(63, 12), "+3V3")
    for ref, x in zip(("C12", "C13", "C14", "C15", "C16", "C17", "C18"),
                      (65, 70, 75, 80, 85, 90, 95)):
        s.place(ref, x, 13.5, fields="right")

    # the flash
    s.block("QSPI flash", 3, 32, 26, 54)
    f = s.place("U3", 19, 44, fields=(1.5, 6.5, "left"))
    for n in ("6", "5", "2", "3", "7"):
        s.label(f[n], stub=2)
    s.wire(f["1"], (11, 41))
    s.label(s.g(11, 41), "QSPI_SS", stub=0, d=(-1, 0))
    s.place("R6", 13, 39.5, rot=180, fields="left")
    s.label(s["R6"]["2"], stub=1, d=(0, -1), text_dir=(1, 0))
    s.wire(f["8"], (19, 37), (22, 37))
    s.power(s.g(19, 37), "+3V3")
    s.place("C2", 22, 38.5, fields="right")

    # buttons: BOOTSEL pulls QSPI_SS low through R6; RUN to ground through R4
    s.block("Buttons", 3, 57, 24, 73)
    b = s.place("SW1", 13, 62, fields="above")
    s.label(b["2"], stub=1)
    s.power(b["1"], "GND", stub=1)
    r = s.place("SW2", 13, 68, fields="above")
    s.label(r["2"], stub=1)
    s.wire(r["1"], (8, 68))
    s.place("R4", 8, 69.5, fields="left")

    # debug connector, LED
    s.block("SWD", 30, 77, 50, 90)
    j = s.place("J4", 43, 83, fields=(2, -1, "left"))
    s.label(j["1"], stub=2)
    s.label(j["3"], stub=2)
    s.wire(j["2"], (36, 83), (36, 86))
    s.power(s.g(36, 86), "GND")
    s.block("LED", 54, 77, 74, 90)
    s.place("R9", 62, 81, rot=270, fields="above")
    s.label(s["R9"]["1"], stub=1, d=(1, 0))
    d = s.place("D3", 58, 84.5, rot=90, fields="right")
    s.wire(s["R9"]["2"], (58, 81), d["2"])

    # headers
    s.block("Headers, 0.9 in apart", 108, 12, 150, 40)
    a = s.place("J2", 124, 27, fields=(-1, -9.5, "left"))
    c = s.place("J3", 145, 27, fields=(-1, -9.5, "left"))
    for part in (a, c):
        for p in part.pins.values():
            # the rails as flags too: sixteen names in a column read better
            # than names with supply symbols poking out between them
            s.label(p, stub=1, kind="global_label")
    s.block("Mounting holes, M2.5", 108, 46, 150, 56)
    for k in range(4):
        s.place(f"H{k + 1}", 114 + 9 * k, 51, fields="below")

    s.text(notes(
        "The RP2350A, its core regulator, crystal, flash and decoupling are Raspberry Pi's "
        "RP2350A minimal design (RP-006440), part for part; the crystal is a 2520 with 27 p "
        "where that has an ABM8 and 15 p.",
        "GPIO: 0-7 right-hand header. 8/9 USB path selects. 10 RF_EN. 11 1.8 V enable. "
        "12/13 tunnelled SDA/SCL (I2C0). 14 LINK_STATUS. 15 MODE_INT. 16/17 tunnelled "
        "TXD/RXD (UART0). 18/19 configuration bus (I2C1). 20 translator enable. "
        "21-24, 26-29 left-hand header. 25 LED.",
        "The headers carry the 3.3 V side of every line the ST60 takes from a host, so a "
        "host that is not the RP2350 can run the link."), 108, 60, size=1.27)


# ------------------------------------------------------------------- link ---
def link(s):
    s.block("eUSB2 repeater", 10, 24, 42, 52)
    p = s.place("U5", 30, 40, fields=(1.5, 6.3, "left"))
    s.wire(p["12"], (29.5, 31), (22, 31))
    s.place("C26", 26, 32.5, fields="left")
    s.place("C27", 22, 32.5, fields="left")
    s.power(s.g(22, 31), "+1V8")
    s.wire(p["10"], (30.5, 31), (38, 31))
    s.place("C28", 34, 32.5, fields="right")
    s.place("C29", 38, 32.5, fields="right")
    s.power(s.g(38, 31), "+3V3")
    s.wire(p["1"], (29.5, 46), (30.5, 46), p["4"])
    s.power(s.g(30, 46), "GND")
    for n in ("9", "8", "5", "7", "6"):
        s.label(p[n], stub=1)
    # ADDR on +1V8: address 0x43
    s.wire(p["11"], (13, 43), (13, 31), (22, 31))

    s.block("ST60A3H1", 46, 24, 96, 52)
    u = s.place("U4", 60, 42, fields=(-7.5, 7.8, "left"))
    # eUSB2: TX and RX tied at the part (DS14598 fig. 4, note 1)
    s.wire(p["2"], u["C4"])
    s.wire(u["L4"], (50, 40), (50, 37))
    s.wire(p["3"], u["C5"])
    s.wire(u["L5"], (48, 41), (48, 38))
    # its supply: +1V8 through the 0 R link
    s.wire(u["C3"], (59.5, 30))
    s.wire(u["L3"], (60.5, 30))
    s.wire((55, 30), (72, 30))
    s.place("R20", 53.5, 30, rot=90, fields="above")
    s.power(s["R20"]["1"], "+1V8", stub=1)
    for ref, x in (("C21", 64), ("C22", 68), ("C23", 72)):
        s.place(ref, x, 31.5, fields="right")
    s.flag(s.g(57, 30), "ST_VDD", stub=1)
    for n in ("E1", "F1", "G1", "J1", "B2", "D1", "K1", "M2"):
        s.label(u[n], stub=1)
    # RF_EN: 3.3 V to 1.8 V by divider
    s.wire(u["H1"], (86, 40))
    s.place("R22", 84, 41.5, fields="right")
    s.place("R21", 87.5, 40, rot=270, fields="above")
    s.label(s["R21"]["1"], stub=1, d=(1, 0))

    s.block("1.8 V - 3.3 V translator", 100, 24, 138, 52)
    t = s.place("U6", 118, 38, fields=(1.5, 8.3, "left"))
    for q in t.pins.values():
        if q.num not in ("2", "19", "11"):
            s.label(q, stub=6 if q.num == "10" else 1)      # OE's flag clear of A1's name
    s.wire(t["2"], (117, 28), (109, 28))
    s.place("C24", 109, 29.5, fields="left")
    s.power(s.g(113, 28), "+1V8")
    s.wire(t["19"], (119, 28), (127, 28))
    s.place("C25", 127, 29.5, fields="right")
    s.power(s.g(123, 28), "+3V3")
    s.place("R28", 132, 47.5, fields="right")

    s.block("Link LED", 46, 54, 96, 73)
    s.place("R29", 62, 66, rot=90, fields="above")
    s.wire(s["R29"]["1"], (54, 66))
    s.label(s.g(54, 66), "ST_LINK_STATUS", stub=0, d=(-1, 0))
    s.place("R23", 57, 67.5, fields="right")
    q1 = s.place("Q1", 67.5, 66, fields=(2.5, 0, "left"))
    s.wire(s["R29"]["2"], q1["1"])
    d = s.place("D2", 68.5, 61.5, rot=90, fields="right")
    s.wire(q1["3"], d["1"])
    s.place("R30", 68.5, 57.5, fields="right")
    s.wire(s["R30"]["2"], d["2"])

    s.text(notes(
        "After ST's X-NUCLEO-60K1A1 (B2379A): the ST60A3H1 on +1V8 through a 0 R link, the "
        "PTN3222 on its eUSB2 pair and held in reset by LINK_STATUS, an eight-channel "
        "auto-direction translator to 3.3 V (TXS0108E here, ST2378E there), RF_EN by "
        "divider, the link LED off an NPN.",
        "The translator is off (LS_OE low) until the RP2350 enables it, so the ST60 powers "
        "up with only its own straps on its pins. No pull-ups are fitted on the "
        "configuration bus or the tunnel pins: ST leaves its own unfitted. A tunnelled I2C "
        "bus wants pull-ups on J2/J3, at 3.3 V.",
        "Configuration bus: ST60A3H1 at 0x60, PTN3222 at 0x43 (ADDR on +1V8)."),
        100, 57, size=1.27)


# ---------------------------------------------------------- USB and power ---
def usb_power(s):
    s.block("USB-C, device", 8, 26, 58, 60)
    j = s.place("J1", 20, 40, fields=(-6, -11, "left"))
    s.wire(j["A4"], (31, 34))
    s.power(s.g(31, 34), "VBUS")
    s.flag(s.g(29, 34), "VBUS", stub=1)
    # each data pad appears twice on the connector (A and B rows)
    s.wire(j["A7"], (29, 39))
    s.wire(j["B7"], (28, 40), (28, 39))
    s.label(s.g(29, 39), "USB_CONN_DM", stub=0, d=(1, 0))
    s.wire(j["A6"], (29, 41))
    s.wire(j["B6"], (28, 42), (28, 41))
    s.label(s.g(29, 41), "USB_CONN_DP", stub=0, d=(1, 0))
    s.label(j["A5"], stub=1)
    s.label(j["B5"], stub=1)
    s.wire(j["S1"], (17, 50), (23, 50))
    s.wire(j["A1"], (20, 50))
    s.power(s.g(20, 50), "GND")
    s.flag(s.g(23, 50), "GND", stub=1)
    s.place("R10", 33, 53.5, fields="right")
    s.place("R11", 38, 53.5, fields="right")
    e = s.place("U8", 49, 41, fields=(2.5, -3.6, "left"))
    for n in ("1", "3", "4", "6"):
        s.label(e[n], stub=1)

    for ref, cap, pd, x, title in (("U9", "C30", "R12", 80, "Switch: connector side"),
                                   ("U10", "C31", "R13", 120, "Switch: RP2350 side")):
        s.block(title, x - 16, 26, x + 20, 60)
        u = s.place(ref, x, 40, fields=(1, 5.2, "left"))
        for n in ("8", "7", "9", "1", "2", "3", "4"):
            s.label(u[n], stub=1)
        s.power(u["6"], "GND", stub=1)
        s.wire(u["10"], (x, 31), (x + 5, 31))
        s.power(s.g(x, 31), "+3V3")
        s.place(cap, x + 5, 32.5, fields="right")
        s.place(pd, x + 12, 51.5, fields="right")

    s.block("3.3 V", 8, 66, 66, 88)
    r = s.place("U2", 40, 75, fields="above")
    s.wire(r["3"], (30, 75))
    s.place("C1", 32, 76.5, fields="left")
    s.power(s.g(30, 75), "VBUS")
    s.wire(r["2"], (58, 75))
    s.place("C5", 46, 76.5, fields="right")
    s.place("C19", 51, 76.5, fields="right")
    s.power(s.g(54, 75), "+3V3")
    s.place("R14", 58, 76.5, fields="right")
    d = s.place("D1", 58, 81.5, rot=90, fields="right")
    s.wire(s["R14"]["2"], d["2"])

    s.block("1.8 V, switchable", 72, 66, 142, 88)
    v = s.place("U7", 104, 75, fields="above")
    s.wire(v["1"], (86, 74))
    s.power(s.g(86, 74), "+3V3")
    s.place("C32", 90, 75.5, fields="left")
    s.place("R15", 95, 75.5, fields="right")
    s.wire(s["R15"]["2"], (99, 77), (99, 75), v["3"])
    s.label(s.g(95, 77), "ST_PWR_EN", stub=1, d=(0, 1), text_dir=(1, 0))
    s.wire(v["5"], (116, 74))
    s.place("C33", 112, 75.5, fields="right")
    s.power(s.g(116, 74), "+1V8")

    s.text(notes(
        "Three things want the USB pair: the connector, the RP2350, the eUSB2 repeater. "
        "The two switches join any two through the node USB_X.",
        "USB_SEL_CONN low, USB_SEL_MCU low: connector to RP2350 -- the board as it powers "
        "up, both selects pulled down.",
        "CONN high: connector to repeater -- a host's USB goes over the air.",
        "MCU high: RP2350 to repeater -- the RP2350 is the device at the far end.",
        "Both high joins all three and is not a state to use.",
        "ST_PWR_EN low turns the 1.8 V regulator off; it discharges its output, which is "
        "a power-on reset for the ST60A3H1."), 8, 93, size=1.27)


SHEETS = {"01_mcu": mcu, "02_link": link, "03_usb_power": usb_power}
FLAGS = {}


def draw(name, comps, glob):
    s = schdraw.Sheet(name, comps, glob)
    SHEETS[name](s)
    auto = s.finish()
    return s, auto


def root_sheet(project, title):
    uid = CIR._uid
    o = ['(kicad_sch', '\t(version 20250114)', '\t(generator "eeschema")',
         '\t(generator_version "9.0")', f'\t(uuid "{uid(project, "sch")}")', '\t(paper "A4")',
         f'\t(title_block (title "{title}") (date "2026-10-02") (rev "A")\n'
         f'\t\t(company "Sequoia Hope Alexander")\n'
         f'\t\t(comment 1 "Drawn by tools/schlayout.py from the netlist in tools/circuit.py")\n'
         f'\t\t(comment 2 "CERN-OHL-P"))',
         '\t(lib_symbols)']
    x, y = 25.0, 40.0
    for i, (nm, desc) in enumerate(CIR.SHEETS):
        su = uid(project, "sheet", nm)
        o.append(f'''	(sheet (at {x} {y}) (size 70 18)
		(fields_autoplaced yes)
		(stroke (width 0.1524) (type solid))
		(fill (color 0 0 0 0.0000))
		(uuid "{su}")
		(property "Sheetname" "{nm}" (at {x} {y - 0.79} 0)
			(effects (font (size 1.27 1.27)) (justify left bottom)))
		(property "Sheetfile" "{nm}.kicad_sch" (at {x} {y + 18.6} 0)
			(effects (font (size 1.27 1.27)) (justify left top)))
		(instances (project "{project}" (path "/{uid(project, "sch")}" (page "{i + 2}"))))
	)''')
        o.append(f'\t(text "{desc}" (exclude_from_sim no) (at {x + 1.5} {y + 5} 0)\n'
                 f'\t\t(effects (font (size 1.0 1.0)) (justify left top)) '
                 f'(uuid "{uid(project, "sheetdesc", nm)}"))')
        y += 28.0
    note = ("comms rev A: an RP2350A and an ST60A3H1 60 GHz contactless transceiver.\\n"
            "Two boards face each other and tunnel UART, GPIO, I2C or USB 2.0 between them.")
    o.append(f'\t(text "{note}" (exclude_from_sim no) (at 25 22 0)\n'
             f'\t\t(effects (font (size 1.6 1.6) (bold yes)) (justify left top)) '
             f'(uuid "{uid(project, "note")}"))')
    o.append(f'\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)')
    o.append('\t(embedded_fonts no)')
    o.append(')')
    return "\n".join(o) + "\n"


def emit(hw, force=True, project=CIR.PROJECT):
    """Write the root sheet and the three drawn sheets into `hw`."""
    uid = CIR._uid
    title = "comms — RP2350A + ST60A3H1 60 GHz contactless link"
    glob = global_nets()
    comps = CIR.board()
    out = {f"{project}.kicad_sch": root_sheet(project, title)}
    for i, (name, desc) in enumerate(CIR.SHEETS):
        s, _ = draw(name, [c for c in comps if c.sheet == name], glob)
        bad, _ = s.check()
        if bad:
            raise RuntimeError(f"{name}: the drawing disagrees with the netlist:\n  " + "\n  ".join(bad))
        out[f"{name}.kicad_sch"] = s.emit(project, uid(project, "subsch", name),
                                          uid(project, "sheet", name), f"{title} — {name}",
                                          sheet_no=i + 2, root_uuid=uid(project, "sch"))
    for fn, text in out.items():
        path = Path(hw) / fn
        if path.exists() and not force:
            print(f"keep   {path.name} (exists)")
            continue
        path.write_text(text)
        print(f"wrote  hardware/comms/{fn}")


if __name__ == "__main__":
    glob = global_nets()
    comps = CIR.board()
    fail = False
    for name in SHEETS:
        s, auto = draw(name, [c for c in comps if c.sheet == name], glob)
        bad, lint = s.check()
        print(f"{name}: {len(s.parts)} parts, {len(s.split())} wires, "
              f"{len(s.labels)} labels, {len(s.powers)} power symbols")
        for b in bad:
            print("  !", b)
        for l in lint:
            print("  ~", l)
        fail |= bool(bad)
    sys.exit(1 if fail else 0)
