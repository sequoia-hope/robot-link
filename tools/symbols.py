#!/usr/bin/env python3
"""symbols.py -- hardware/parts/comms.kicad_sym, the project's own symbols.

    python3 tools/symbols.py

Five parts KiCad 9's library does not have, or has under another footprint:

  RP2350_60QFN   Raspberry Pi's own symbol, from the RP2350A minimal design
                 (RP-006440), by way of servodrive's library
  W25Q16JV       the reference's flash in the USON 2x3 it is bought in
  ST60A3H1       drawn here from DS14598 rev 4, table 42
  PTN3222        drawn here from NXP's data sheet rev 1.2, table 5 (QFN pins)
  TS3USB221A     drawn here from TI's SCDS263, table 4-1 (RSE pins)

Each drawn symbol is a box, its pins on the side they are wired from on the
sheets (the ST60 between the repeater on its left and the translator on its
right), supplies on top, ground underneath.
"""
from pathlib import Path

import sexp

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware/parts/comms.kicad_sym"
SERVODRIVE = Path("/home/sequoia/pcb/servodrive/hardware/parts/servodrive.kicad_sym")

U = 2.54
F = "(effects (font (size 1.27 1.27)))"
FH = "(effects (font (size 1.27 1.27)) (hide yes))"


def _pin(etype, name, number, x, y, ang, hide=False):
    h = " hide" if hide else ""
    return (f'\t\t\t(pin {etype} line (at {x:.2f} {y:.2f} {ang}) (length 2.54){h}\n'
            f'\t\t\t\t(name "{name}" {F})\n'
            f'\t\t\t\t(number "{number}" {F}))')


def box(name, ref, footprint, datasheet, descr, left, right, top=(), bottom=(),
        width=None):
    """A box symbol. Each side is a list of (name, number, type) or None for
    a gap; a number may be a tuple, and then the pins are stacked on one point
    (the first shown, the rest hidden and passive) -- eight ground balls are
    one ground on the sheet."""
    rows = max(len(left), len(right))
    longest = max([len(p[0]) for p in left + right if p] + [4])
    w = width or max(8, 2 * ((longest * 2 + 6) // 4 + 1), 2 * max(len(top), len(bottom)) + 4)
    hw = w / 2 * U
    h = (rows + 1) * U
    y_top = h / 2
    y0 = round((y_top - U) / 1.27) * 1.27          # first row
    y_top = y0 + U
    y_bot = y0 - (rows - 1) * U - U
    pins = []

    def side(items, fx, ang, x=None):
        for i, it in enumerate(items):
            if not it:
                continue
            nm, nums, et = it
            nums = nums if isinstance(nums, tuple) else (nums,)
            px, py = fx(i)
            for k, n in enumerate(nums):
                pins.append(_pin(et if k == 0 else "passive", nm, n, px, py, ang, hide=k > 0))

    side(left, lambda i: (-hw - U, y0 - i * U), 0)
    side(right, lambda i: (hw + U, y0 - i * U), 180)
    tx0 = -((len(top) - 1) / 2) * U
    side(top, lambda i: (round((tx0 + i * U) / 1.27) * 1.27, y_top + U), 270)
    bx0 = -((len(bottom) - 1) / 2) * U
    side(bottom, lambda i: (round((bx0 + i * U) / 1.27) * 1.27, y_bot - U), 90)
    return (f'\t(symbol "{name}" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
            f'\t\t(property "Reference" "{ref}" (at {-hw:.2f} {y_top + 1.27:.2f} 0)\n'
            f'\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom)))\n'
            f'\t\t(property "Value" "{name}" (at {-hw:.2f} {y_bot - 1.27:.2f} 0)\n'
            f'\t\t\t(effects (font (size 1.27 1.27)) (justify left top)))\n'
            f'\t\t(property "Footprint" "{footprint}" (at 0 0 0) {FH})\n'
            f'\t\t(property "Datasheet" "{datasheet}" (at 0 0 0) {FH})\n'
            f'\t\t(property "Description" "{descr}" (at 0 0 0) {FH})\n'
            f'\t\t(symbol "{name}_0_1"\n'
            f'\t\t\t(rectangle (start {-hw:.2f} {y_top:.2f}) (end {hw:.2f} {y_bot:.2f})\n'
            f'\t\t\t\t(stroke (width 0.254) (type default)) (fill (type background))))\n'
            f'\t\t(symbol "{name}_1_1"\n' + "\n".join(pins) + '\n\t\t)\n\t)')


def copied(name, footprint=None):
    """A symbol out of servodrive's library, as it stands there."""
    root = sexp.parse(SERVODRIVE.read_text())
    s = next(s for s in sexp.findall(root, "symbol") if sexp.unq(s[1]) == name)
    if footprint:
        for p in sexp.findall(s, "property"):
            if sexp.unq(p[1]) == "Footprint":
                p[2] = sexp.q(footprint)
    return "\t" + sexp.dump(s, indent=1)


B, I, O, P, PW = "bidirectional", "input", "output", "passive", "power_in"

ST60 = box(
    "ST60A3H1", "U", "comms:ST_VFBGA-23_AiP_2.95x4.07mm_P0.4mm",
    "https://www.st.com/resource/en/datasheet/st60a3h1.pdf",
    "60 GHz V-band contactless transceiver, antenna in package; eUSB2, UART, GPIO or I2C tunnelling",
    left=[("TX_IP", "C4", I), ("TX_IN", "C5", I), None,
          ("RX_OP", "L4", O), ("RX_ON", "L5", O)],
    right=[("CFG_SCL", "E1", I), ("CFG_SDA", "F1", B), None,
           ("RF_EN", "H1", I), ("MODE_INT", "G1", B), ("LINK_STATUS", "J1", B), None,
           ("GPIO[0]", "B2", B), ("GPIO[1]", "D1", B), ("GPIO[2]", "K1", B), ("GPIO[3]", "M2", B)],
    top=[("VDD_1V8", "C3", PW), ("VDD_IO", "L3", PW)],
    bottom=[("GND", ("A3", "A4", "A5", "C6", "L6", "N3", "N4", "N5"), PW)],
    width=14)

PTN = box(
    "PTN3222", "U", "comms:NXP_XQFN-12_1.75x2.2mm_P0.4mm",
    "https://www.nxp.com/docs/en/data-sheet/PTN3222.pdf",
    "1-port eUSB2 to USB 2.0 repeater, host, device or dual role; XQFN12",
    left=[("DP", "9", B), ("DN", "8", B), None,
          ("RST_N", "5", I), ("SCL", "7", I), ("SDA", "6", B), ("ADDR", "11", I)],
    right=[("eDP", "2", B), ("eDN", "3", B)],
    top=[("VDD1V8", "12", PW), ("VDD3V3", "10", PW)],
    bottom=[("DGND", "1", PW), ("AGND", "4", PW)],
    width=10)

SW = box(
    "TS3USB221A", "U", "Package_DFN_QFN:Texas_UQFN-10_1.5x2mm_P0.5mm",
    "https://www.ti.com/lit/ds/symlink/ts3usb221a.pdf",
    "High-speed USB 2.0 1:2 multiplexer / demultiplexer switch, RSE (UQFN-10)",
    left=[("D+", "8", P), ("D-", "7", P), None, ("S", "9", I), ("~{OE}", "6", I)],
    right=[("1D+", "1", P), ("1D-", "2", P), None, ("2D+", "3", P), ("2D-", "4", P)],
    top=[("VCC", "10", PW)],
    bottom=[("GND", "5", PW)],
    width=8)


def main():
    text = ('(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "symbols.py")\n'
            '\t(generator_version "9.0")\n'
            + copied("RP2350_60QFN",
                     "comms:RP2350-QFN-60-1EP_7x7_P0.4mm_EP3.4x3.4mm_ThermalVias") + "\n"
            + copied("W25Q16JV") + "\n"
            + ST60 + "\n" + PTN + "\n" + SW + "\n)\n")
    sexp.parse(text)                      # balanced, or it does not get written
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
