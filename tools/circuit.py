#!/usr/bin/env python3
"""circuit.py -- the comms board's netlist, as data.

The circuit is DATA here, not drawing: every component is a reference, a
symbol, a value, a footprint and a pin-to-net map. The schematic
(tools/schlayout.py) is drawn from it and the board (tools/gen_board.py) is
built from it, so the two cannot disagree; KiCad's own netlist export is
compared with it net by net (tools/check.py).

    python3 tools/circuit.py          # the netlist report and the checks

What the board is: an RP2350A beside an ST60A3H1, ST's 60 GHz contactless
transceiver with the antenna in the package. Two of these boards face each
other a few centimetres apart and tunnel UART, GPIO, I2C or eUSB2 between
them. The same board is either end: which is Local and which Remote is the
ST60's configuration, written by the RP2350 over I2C.

Where each block comes from:

  - the RP2350A, its core regulator, crystal, flash and decoupling:
    Raspberry Pi's RP2350A minimal design (RP-006440), part for part
  - the ST60A3H1, its supply, the eUSB2 repeater and the 1.8 V translator:
    ST's X-NUCLEO-60K1A1 (boards B2379A, schematic rev 1), with a TXS0108E
    where ST has its own ST2378E
  - sourcing and the passives' values: servodrive's hardware/parts/lcsc.csv
"""
import os
import uuid
from pathlib import Path

import sexp

ROOT = Path(__file__).resolve().parent.parent
KSYM = Path("/usr/share/kicad/symbols")
PROJ_SYM = ROOT / "hardware/parts/comms.kicad_sym"
PROJECT = "comms"

# Deterministic UUIDs, so re-running produces byte-identical files.
NS = uuid.UUID("5c0e60a3-0000-4000-8000-000000000000")
def _uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))

# ------------------------------------------------------------- libraries ----
_LIBS, _SYMS, _PINS = {}, {}, {}

def _lib(nick):
    if nick not in _LIBS:
        path = PROJ_SYM if nick == PROJECT else KSYM / f"{nick}.kicad_sym"
        _LIBS[nick] = sexp.parse(path.read_text())
    return _LIBS[nick]

def symbol(lib_id):
    """The symbol definition, with any `extends` resolved into it.

    A schematic carries its own copy of every symbol it uses, and a derived
    symbol whose base is not also present will not load. Flattening is simpler
    than shipping both and hoping KiCad resolves the bare base name.
    """
    if lib_id in _SYMS:
        return _SYMS[lib_id]
    nick, name = lib_id.split(":", 1)
    root = _lib(nick)
    src = next((s for s in sexp.findall(root, "symbol")
                if sexp.unq(s[1]) == name), None)
    if src is None:
        raise KeyError(f"no symbol {lib_id}")
    ext = sexp.find(src, "extends")
    if ext:
        base = next(s for s in sexp.findall(root, "symbol")
                    if sexp.unq(s[1]) == sexp.unq(ext[1]))
        out = ["symbol", sexp.q(lib_id)]
        for c in base[2:]:                      # graphics, pins, base flags
            if isinstance(c, list) and c[0] in ("property", "extends"):
                continue
            out.append(_rename_units(c, sexp.unq(base[1]), name))
        for c in src[2:]:                       # the derived part's own fields
            if isinstance(c, list) and c[0] == "property":
                out.append(c)
        for c in base[2:]:                      # anything the derived one lacks
            if isinstance(c, list) and c[0] == "property":
                nm = sexp.unq(c[1])
                if not any(sexp.unq(d[1]) == nm
                           for d in sexp.findall(out, "property")):
                    out.append(c)
    else:
        out = ["symbol", sexp.q(lib_id)] + [
            _rename_units(c, name, name) for c in src[2:]]
    _SYMS[lib_id] = out
    return out

def _rename_units(node, old, new):
    """Sub-symbols are named "<parent>_<unit>_<style>", and the parent there is
    the UNQUALIFIED name even when the symbol itself is stored as "Lib:Name"."""
    if isinstance(node, list) and node and node[0] == "symbol":
        nm = sexp.unq(node[1])
        if nm.startswith(old + "_"):
            node = ["symbol", sexp.q(new + nm[len(old):])] + node[2:]
    return node

def pins(lib_id):
    """{number: (x, y, rot, name, etype)} in library coordinates."""
    if lib_id in _PINS:
        return _PINS[lib_id]
    out = {}
    for p in sexp.walk(symbol(lib_id), "pin"):
        at = sexp.find(p, "at")
        nb, nm = sexp.find(p, "number"), sexp.find(p, "name")
        if not (at and nb):
            continue
        out[sexp.unq(nb[1])] = (float(at[1]), float(at[2]), float(at[3]),
                                sexp.unq(nm[1]) if nm else "", p[1])
    _PINS[lib_id] = out
    return out

# ---------------------------------------------------------------- netlist ---
class Comp:
    __slots__ = ("ref", "lib_id", "value", "fp", "nets", "sheet", "group",
                 "dnp", "note")

    def __init__(self, ref, lib_id, value, fp, nets, sheet, group, dnp=False,
                 note=""):
        self.ref, self.lib_id, self.value, self.fp = ref, lib_id, value, fp
        self.nets, self.sheet, self.group, self.dnp = nets, sheet, group, dnp
        self.note = note

R = "Device:R"
C = "Device:C"
L = "Device:L"
LED = "Device:LED"

FP_R = {"0402": "Resistor_SMD:R_0402_1005Metric"}
FP_C = {"0402": "Capacitor_SMD:C_0402_1005Metric",
        "0402s": "comms:C_0402_1005Metric_small_pads",   # the reference's, at the core regulator
        "0805": "Capacitor_SMD:C_0805_2012Metric"}
FP_LED = "LED_SMD:LED_0603_1608Metric"
FP_SW = "Button_Switch_SMD:SW_SPST_B3U-1000P"
FP_HDR = "Connector_PinHeader_2.54mm:PinHeader_1x16_P2.54mm_Vertical"

# Supplies. VBUS is the USB-C connector's 5 V; ST_VDD is +1V8 after the 0 R
# link that lets the ST60's current be measured on its own.
PWR = {"GND", "VBUS", "+3V3", "+1V8", "+1V1"}

# The RP2350's GPIO. The chip sits turned half round, so that its USB and
# QSPI side faces the USB-C connector at the bottom edge and the side with
# GPIO12-18 faces the translator. Every signal leaves the chip on the side
# it is wanted: what goes to the ST60 from the top, what goes to the bottom
# of the board from the bottom of a side, the rest straight out to a header.
#
#   0..7     the right-hand header
#   8..11    USB path selects, RF_EN, the 1.8 V regulator's enable: the four
#            pins at the open top-right corner, where each has room for the
#            via it needs (lower down the side the decoupling capacitors
#            leave four pins a gap four tracks wide, and no more)
#   12..19   the ST60, through the translator
#   20       the translator's enable
#   21..24, 26..29 (the ADC pins)   the left-hand header;  25 the LED
#
# An OV2640 camera, when one is plugged in, takes 0..7, 21..24 and 26..28
# off the headers (see CAM, below).
#
# Every tunnelling mode the ST60 offers lands on a hardware peripheral, and
# the configuration bus has one to itself:
#
#   16/17   UART0 TX/RX      GPIO[0] is the tunnel's TXD, GPIO[1] its RXD
#   12/13   I2C0 SDA/SCL     GPIO[3]/GPIO[2], the tunnelled SDA/SCL
#   18/19   I2C1 SDA/SCL     the configuration bus
#
# (0/1 on the header are UART0 TX/RX as well, the usual place; 4/5 are UART1.)
GP = {
    8: "USB_SEL_MCU",    # high: the RP2350's own USB goes to the repeater
    9: "USB_SEL_CONN",   # high: the USB-C connector goes to the eUSB2 repeater
    10: "RF_EN_GP",      # RF_EN, through the divider to 1.8 V
    11: "ST_PWR_EN",     # high: the 1.8 V regulator on. Low, or not driven: off (a cold reset of the ST60)
    12: "TUN_G3",        # I2C0 SDA <-> ST60 GPIO[3], the tunnelled SDA
    13: "TUN_G2",        # I2C0 SCL <-> ST60 GPIO[2], the tunnelled SCL
    14: "ST_LINK",       # LINK_STATUS
    15: "ST_INT",        # MODE_INT
    16: "TUN_G0",        # UART0 TX -> ST60 GPIO[0], the tunnelled TXD
    17: "TUN_G1",        # UART0 RX <- ST60 GPIO[1], the tunnelled RXD
    18: "CFG_SDA",       # I2C1: the ST60's configuration port (0x60) and the
    19: "CFG_SCL",       #   PTN3222's (0x43)
    20: "LS_OE",         # the translator's output enable
    25: "LED",
}
HEADER_GPIO = list(range(0, 8)) + [21, 22, 23, 24, 26, 27, 28, 29]
for _g in HEADER_GPIO:
    GP[_g] = f"GP{_g}"

SHEETS = [
    ("01_mcu", "RP2350A, core regulator, crystal, QSPI flash, SWD, buttons, headers"),
    ("02_link", "ST60A3H1, 1.8 V translator, eUSB2 repeater, link LED"),
    ("03_usb_power", "USB-C, USB path switches, 3.3 V and 1.8 V regulators"),
    ("04_camera", "OV2640 camera module connector, its 2.8 V and 1.3 V supplies"),
]
REV = "B"


def mcu():
    """01_mcu: the RP2350A and everything it cannot run without, as
    Raspberry Pi's minimal design has it."""
    sh, out = "01_mcu", []
    def add(ref, lib_id, value, fp, nets, group, note="", dnp=False):
        out.append(Comp(ref, lib_id, value, fp, nets, sh, group, dnp, note))

    cpu = {}
    for pin, name in (("1", "+3V3"), ("11", "+3V3"), ("20", "+3V3"),
                      ("30", "+3V3"), ("38", "+3V3"), ("45", "+3V3"),
                      ("6", "+1V1"), ("23", "+1V1"), ("39", "+1V1"),
                      ("61", "GND"), ("21", "XIN"), ("22", "XOUT"),
                      ("24", "SWCLK"), ("25", "SWDIO"), ("26", "RUN"),
                      # 44 ADC_AVDD and 45 IOVDD on +3V3, as the reference;
                      # 46 VREG_AVDD through 33 R; 47 VREG_PGND; 48 VREG_LX;
                      # 49 VREG_VIN; 50 VREG_FB; 53 USB_OTP_VDD; 54 QSPI_IOVDD
                      ("44", "+3V3"), ("46", "VREG_AVDD"), ("47", "GND"),
                      ("48", "VREG_LX"), ("49", "+3V3"), ("50", "+1V1"),
                      ("51", "USB_DM_C"), ("52", "USB_DP_C"),
                      ("53", "+3V3"), ("54", "+3V3"),
                      ("55", "QSPI_SD3"), ("56", "QSPI_SCLK"),
                      ("57", "QSPI_SD0"), ("58", "QSPI_SD2"),
                      ("59", "QSPI_SD1"), ("60", "QSPI_SS")):
        cpu[pin] = name
    # GPIO0..29 land on pins 2..5, 7..10, 12..19, 27..29, 31..37, 40..43
    order = [2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19,
             27, 28, 29, 31, 32, 33, 34, 35, 36, 37, 40, 41, 42, 43]
    for g, pin in zip(range(30), order):
        cpu[str(pin)] = GP[g]
    add("U1", "comms:RP2350_60QFN", "RP2350A",
        "comms:RP2350-QFN-60-1EP_7x7_P0.4mm_EP3.4x3.4mm_ThermalVias",
        cpu, "CPU", "QFN-60; turned so USB and QSPI face the connector")

    # The core regulator, the reference's references in brackets: 3.3 uH
    # from VREG_LX (L1), 4.7 u on its output beside it (C7) and on VREG_VIN
    # (C6), VREG_AVDD through 33 R (R5) with its own 4.7 u (C9), 4.7 u more
    # on DVDD at pin 23 (C10). The inductor's pad 1 is the output.
    add("L1", L, "3u3", "comms:L_pol_2016",
        {"1": "+1V1", "2": "VREG_LX"}, "core rail",
        "core buck: VREG_LX -> DVDD. 3.3 uH 2016, polarised, as the reference")
    add("C6", C, "4u7", FP_C["0402s"], {"1": "+3V3", "2": "GND"}, "core rail",
        "VREG_VIN, at pin 49")
    add("C7", C, "4u7", FP_C["0402s"], {"1": "+1V1", "2": "GND"}, "core rail",
        "DVDD, at the inductor")
    add("C9", C, "4u7", FP_C["0402"], {"1": "VREG_AVDD", "2": "GND"}, "core rail",
        "VREG_AVDD")
    add("R5", R, "33R", FP_R["0402"], {"1": "+3V3", "2": "VREG_AVDD"}, "core rail",
        "+3V3 -> VREG_AVDD")
    add("C10", C, "4u7", FP_C["0402"], {"1": "+1V1", "2": "GND"}, "core rail",
        "DVDD, at pin 23")
    # 100 n as the reference has them: two on DVDD (pins 6 and 39; pin 23
    # has the 4.7 u), seven on the 3V3 pins
    for ref, pin in (("C8", 6), ("C11", 39)):
        add(ref, C, "100n", FP_C["0402"], {"1": "+1V1", "2": "GND"}, "decoupling",
            f"DVDD, pin {pin}")
    for ref, pin in (("C12", "53/54"), ("C13", "1"), ("C14", "38"), ("C15", "11"),
                     ("C16", "30"), ("C17", "44/45"), ("C18", "20")):
        add(ref, C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "decoupling",
            f"IOVDD, pin {pin}")
    add("R7", R, "27R", FP_R["0402"], {"1": "USB_DP", "2": "USB_DP_C"}, "USB",
        "USB_DP series")
    add("R8", R, "27R", FP_R["0402"], {"1": "USB_DM", "2": "USB_DM_C"}, "USB",
        "USB_DM series")

    # Crystal: servodrive's part (CL 20 pF, 2520) and its 27 p, where the
    # reference has an ABM8-272 and 15 p; the 1 k on XOUT is the reference's.
    add("Y1", "Device:Crystal_GND24", "12MHz",
        "Crystal:Crystal_SMD_2520-4Pin_2.5x2.0mm",
        {"1": "XIN", "2": "GND", "3": "XTAL2", "4": "GND"}, "clock",
        "12 MHz 2520, CL 20 pF")
    add("R2", R, "1k", FP_R["0402"], {"1": "XOUT", "2": "XTAL2"}, "clock",
        "crystal series, on XOUT")
    add("C3", C, "27p", FP_C["0402"], {"1": "XIN", "2": "GND"}, "clock", "crystal load")
    add("C4", C, "27p", FP_C["0402"], {"1": "XTAL2", "2": "GND"}, "clock", "crystal load")

    add("U3", "comms:W25Q16JV", "W25Q16JVUXIQ",
        "Package_SON:Winbond_USON-8-1EP_3x2mm_P0.5mm_EP0.2x1.6mm",
        {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND",
         "5": "QSPI_SD0", "6": "QSPI_SCLK", "7": "QSPI_SD3", "8": "+3V3"},
        "QSPI flash", "16 Mbit QSPI flash")
    add("C2", C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "QSPI flash",
        "flash decoupling")
    add("R6", R, "1k", FP_R["0402"], {"1": "QSPI_SS", "2": "BOOTSEL"},
        "QSPI flash", "BOOTSEL series")
    add("SW1", "Switch:SW_Push", "BOOTSEL", FP_SW,
        {"1": "GND", "2": "BOOTSEL"}, "buttons", "hold while resetting: USB boot")
    add("SW2", "Switch:SW_Push", "RUN", FP_SW,
        {"1": "RUN_SW", "2": "RUN"}, "buttons", "reset")
    add("R4", R, "1k", FP_R["0402"], {"1": "RUN_SW", "2": "GND"}, "buttons",
        "RUN button series")

    add("J4", "Connector_Generic_MountingPin:Conn_01x03_MountingPin", "SWD",
        "Connector_JST:JST_SH_SM03B-SRSS-TB_1x03-1MP_P1.00mm_Horizontal",
        {"1": "SWCLK", "2": "GND", "3": "SWDIO", "MP": "GND"}, "debug",
        "Raspberry Pi debug connector: SWCLK, GND, SWDIO")

    add("D3", LED, "blue", FP_LED, {"1": "GND", "2": "LED_A"}, "LED", "user LED, GPIO25")
    add("R9", R, "220R", FP_R["0402"], {"1": "LED", "2": "LED_A"}, "LED", "LED series (Vf 3.1 V)")

    # The headers, 0.9 inch apart. Each runs in the order the chip's pins
    # come off that side, so nothing crosses on the way out. Besides GPIO
    # they carry the 3.3 V side of everything the ST60 needs from a host --
    # the four tunnelled lines, the configuration bus, RF_EN, the interrupt
    # and the link status -- so a host that is not the RP2350 can run the
    # link: the RP2350 enables the translator and lets go of those pins.
    j2 = ["+1V8", "GND", "TUN_G0", "TUN_G1", "CFG_SDA", "CFG_SCL", "GP21", "GP22",
          "GP23", "GP24", "GP26", "GP27", "GP28", "GP29", "+3V3", "VBUS"]
    j3 = ["ST_INT", "ST_LINK", "TUN_G2", "TUN_G3", "RF_EN_GP", "GP7", "GP6", "GP5",
          "GP4", "GP3", "GP2", "GP1", "GP0", "GND", "+3V3", "VBUS"]
    add("J2", "Connector_Generic:Conn_01x16", "LEFT", FP_HDR,
        {str(i + 1): n for i, n in enumerate(j2)}, "headers",
        "tunnelled UART, configuration bus, GPIO21-24 and the ADC pins, rails")
    add("J3", "Connector_Generic:Conn_01x16", "RIGHT", FP_HDR,
        {str(i + 1): n for i, n in enumerate(j3)}, "headers",
        "link status and interrupt, tunnelled I2C, RF_EN, GPIO0-7, rails")
    return out


def link():
    """02_link: the ST60A3H1 and what stands between it and 3.3 V logic --
    ST's X-NUCLEO-60K1A1, sheet 1, with the Nucleo's place taken by the
    RP2350."""
    sh, out = "02_link", []
    def add(ref, lib_id, value, fp, nets, group, note="", dnp=False):
        out.append(Comp(ref, lib_id, value, fp, nets, sh, group, dnp, note))

    st = {"A3": "GND", "A4": "GND", "A5": "GND", "C6": "GND", "L6": "GND",
          "N3": "GND", "N4": "GND", "N5": "GND",
          "C3": "ST_VDD", "L3": "ST_VDD",          # VDD_1V8 and VDD_IO, tied on the board (DS 2.7.1.1)
          "B2": "ST_G0", "D1": "ST_G1", "K1": "ST_G2", "M2": "ST_G3",
          "E1": "ST_SCL", "F1": "ST_SDA",
          "G1": "ST_MODE_INT", "H1": "ST_RF_EN", "J1": "ST_LINK_STATUS",
          # eUSB2: TX_IP with RX_OP and TX_IN with RX_ON, tied on the board
          # (DS fig. 4, note 1)
          "C4": "EUSB_P", "L4": "EUSB_P", "C5": "EUSB_N", "L5": "EUSB_N"}
    add("U4", "comms:ST60A3H1", "ST60A3H1",
        "comms:ST_VFBGA-23_AiP_2.95x4.07mm_P0.4mm", st, "ST60",
        "60 GHz transceiver, antenna in package; the patch is 1.18 mm toward row N from the centre")
    add("R20", R, "0R", FP_R["0402"], {"1": "+1V8", "2": "ST_VDD"}, "ST60",
        "the ST60's supply link: lift it to measure the current")
    add("C21", C, "100n", FP_C["0402"], {"1": "ST_VDD", "2": "GND"}, "ST60", "VDD_1V8, ball C3")
    add("C22", C, "100n", FP_C["0402"], {"1": "ST_VDD", "2": "GND"}, "ST60", "VDD_IO, ball L3")
    # No bulk here: the ST60 wants its supply to rise and fall in 50 us to
    # 1 ms (DS table 8), and the regulator's 120 R discharge has to empty
    # everything on the rail in that time. 1 u at the regulator, 470 n at the
    # repeater and three 100 n make 1.8 uF, about 0.5 ms from 90 % to 10 %.

    # RF_EN: 3.3 V to 1.8 V by divider, as ST does (1k5/1k8). The 1k8 also
    # holds RF_EN low against the ST60's internal pull-up until the RP2350
    # drives it, so the radio stays in RF_IDLE through a reset.
    add("R21", R, "1k5", FP_R["0402"], {"1": "RF_EN_GP", "2": "ST_RF_EN"}, "ST60", "RF_EN divider, top")
    add("R22", R, "1k8", FP_R["0402"], {"1": "ST_RF_EN", "2": "GND"}, "ST60", "RF_EN divider, bottom")
    # LINK_STATUS is an input with a weak pull-down until the ST60 has
    # booted, and the repeater's RST_N pulls up through 10 k: 1 k holds it low.
    add("R23", R, "1k", FP_R["0402"], {"1": "ST_LINK_STATUS", "2": "GND"}, "ST60",
        "LINK_STATUS pull-down, against the PTN3222's RST_N pull-up")
    # Pull-ups on the 1.8 V side of the configuration bus and of GPIO[2]/[3]
    # (the tunnelled SCL/SDA). The ST60 and the PTN3222 both ask for external
    # ones (DS14598 table 3, notes 1 and 4; PTN3222 table 5), and without
    # them GPIO[2]/[3] -- inputs with a 20-120 k pull-down after reset --
    # would sit mid-rail against the translator's 40 k pull-ups. 4k7 is as
    # low as the translator's pass gate lets the far side pull down cleanly;
    # anything added on the 3.3 V side (J2, J3) should be 8k2 or more.
    for ref, net in (("R24", "ST_SCL"), ("R25", "ST_SDA"), ("R26", "ST_G2"), ("R27", "ST_G3")):
        add(ref, R, "4k7", FP_R["0402"], {"1": net, "2": "+1V8"}, "ST60", f"{net} pull-up")
    # MODE_INT is a boot strap, read as 0 on the ST60's internal pull-down
    # alone. If the 1.8 V rail is cycled with the translator enabled, the
    # translator's 40 k pull-up would be pulling against it: 4k7 settles it.
    add("R31", R, "4k7", FP_R["0402"], {"1": "ST_MODE_INT", "2": "GND"}, "ST60",
        "MODE_INT strap: 0 at power-up, whatever the translator is doing")

    # The translator. A side at 1.8 V, B at 3.3 V; OE is referenced to VCCA
    # but takes 5.5 V, so the GPIO drives it directly. Pulled low: the ST60
    # boots with nothing but its own internal straps on its pins.
    # Channels in the order the ST60's balls come round to the A side:
    # nothing crosses between the island and the translator.
    ls = {"2": "+1V8", "19": "+3V3", "11": "GND", "10": "LS_OE",
          "9": "ST_G0", "12": "TUN_G0",                 # A8 / B8
          "8": "ST_G1", "13": "TUN_G1",                 # A7 / B7
          "7": "ST_SCL", "14": "CFG_SCL",               # A6 / B6
          "6": "ST_SDA", "15": "CFG_SDA",               # A5 / B5
          "5": "ST_MODE_INT", "16": "ST_INT",           # A4 / B4
          "4": "ST_LINK_STATUS", "17": "ST_LINK",       # A3 / B3
          "3": "ST_G2", "18": "TUN_G2",                 # A2 / B2
          "1": "ST_G3", "20": "TUN_G3"}                 # A1 / B1
    add("U6", "Logic_LevelTranslator:TXS0108EPW", "TXS0108E",
        "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm", ls, "translator",
        "1.8 V <-> 3.3 V, auto-direction, push-pull or open-drain")
    add("C24", C, "100n", FP_C["0402"], {"1": "+1V8", "2": "GND"}, "translator", "VCCA")
    add("C25", C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "translator", "VCCB")
    add("R28", R, "4k7", FP_R["0402"], {"1": "LS_OE", "2": "GND"}, "translator",
        "OE pull-down: translator off until the RP2350 says so")

    # The eUSB2 repeater, as ST has it: held in reset until the RF link is
    # up, on the configuration bus at 0x43 (ADDR on 1.8 V), though it needs
    # no configuration to work.
    add("U5", "comms:PTN3222", "PTN3222GM",
        "comms:NXP_XQFN-12_1.75x2.2mm_P0.4mm",
        {"1": "GND", "4": "GND", "2": "EUSB_P", "3": "EUSB_N",
         "5": "ST_LINK_STATUS", "6": "ST_SDA", "7": "ST_SCL",
         "8": "RPT_DM", "9": "RPT_DP", "10": "+3V3", "11": "+1V8", "12": "+1V8"},
        "repeater", "eUSB2 <-> USB 2.0 repeater, host or device side")
    add("C26", C, "470n", FP_C["0402"], {"1": "+1V8", "2": "GND"}, "repeater", "VDD1V8 (NXP's value)")
    add("C27", C, "100p", FP_C["0402"], {"1": "+1V8", "2": "GND"}, "repeater", "VDD1V8")
    add("C28", C, "1u", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "repeater", "VDD3V3")
    add("C29", C, "100p", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "repeater", "VDD3V3")

    # Link LED, off the 1.8 V LINK_STATUS through an NPN as ST does it.
    add("Q1", "Transistor_BJT:MMBT3904", "MMBT3904", "Package_TO_SOT_SMD:SOT-23",
        {"1": "LINK_B", "2": "GND", "3": "LINK_K"}, "link LED", "link LED driver")
    add("R29", R, "10k", FP_R["0402"], {"1": "ST_LINK_STATUS", "2": "LINK_B"},
        "link LED", "base resistor")
    add("D2", LED, "green", FP_LED, {"1": "LINK_K", "2": "LINK_A"}, "link LED",
        "lit while the RF link is up")
    add("R30", R, "220R", FP_R["0402"], {"1": "+3V3", "2": "LINK_A"}, "link LED",
        "LED series")
    return out


def usb_power():
    """03_usb_power: the connector, the two switches that decide what its
    data pair reaches, and the regulators."""
    sh, out = "03_usb_power", []
    def add(ref, lib_id, value, fp, nets, group, note="", dnp=False):
        out.append(Comp(ref, lib_id, value, fp, nets, sh, group, dnp, note))

    add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
        "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
        {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "S1": "GND",
         "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
         "A5": "CC1", "B5": "CC2",
         "A6": "USB_CONN_DP", "B6": "USB_CONN_DP",
         "A7": "USB_CONN_DM", "B7": "USB_CONN_DM",
         "A8": "", "B8": ""}, "USB-C", "USB 2.0 Type-C, device")
    add("R10", R, "5k1", FP_R["0402"], {"1": "CC1", "2": "GND"}, "USB-C", "CC1 Rd")
    add("R11", R, "5k1", FP_R["0402"], {"1": "CC2", "2": "GND"}, "USB-C", "CC2 Rd")
    add("U8", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6",
        "Package_TO_SOT_SMD:SOT-23-6",
        {"1": "USB_CONN_DP", "6": "USB_CONN_DP", "3": "USB_CONN_DM",
         "4": "USB_CONN_DM", "2": "GND", "5": "VBUS"}, "USB-C", "USB ESD")

    # Three things want the USB pair: the connector, the RP2350, the
    # repeater. Two 2:1 switches join any two of them through the node X:
    #
    #   CONN  MCU   connector --X-- RP2350      the board as shipped: USB to the RP2350
    #    1     0    connector ----- repeater    a PC's USB goes over the air
    #    0     1    RP2350 -------- repeater    the RP2350 is the device at the far end
    #
    # Both high joins all three and is not a state to use. The selects are
    # pulled down, so a reset always lands in the first row and the board can
    # be reached over its own connector whatever the firmware did.
    for ref, com, sel, why in (
            ("U9", ("USB_CONN_DP", "USB_CONN_DM"), "USB_SEL_CONN", "connector side"),
            ("U10", ("USB_DP", "USB_DM"), "USB_SEL_MCU", "RP2350 side")):
        add(ref, "comms:TS3USB221A", "TS3USB221A",
            "Package_DFN_QFN:Texas_UQFN-10_1.5x2mm_P0.5mm",
            {"8": com[0], "7": com[1], "1": "USB_X_DP", "2": "USB_X_DM",
             "3": "RPT_DP", "4": "RPT_DM", "5": "GND", "6": "GND",
             "9": sel, "10": "+3V3"}, "USB switches",
            f"USB 2.0 2:1 switch, {why}")
    add("C30", C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "USB switches", "U9 VCC")
    add("C31", C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "USB switches", "U10 VCC")
    # 4k7, not 10 k: RP2350 erratum E9 wants 8.2 k or less to hold a pin low
    add("R12", R, "4k7", FP_R["0402"], {"1": "USB_SEL_CONN", "2": "GND"},
        "USB switches", "select pull-down (E9: <= 8k2)")
    add("R13", R, "4k7", FP_R["0402"], {"1": "USB_SEL_MCU", "2": "GND"},
        "USB switches", "select pull-down (E9: <= 8k2)")

    # 3.3 V as the reference has it (an 1117 in SOT-223, 10 u each side).
    add("U2", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
        "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
        {"1": "GND", "2": "+3V3", "3": "VBUS"}, "3V3", "3.3 V LDO")
    add("C1", C, "10u", FP_C["0805"], {"1": "VBUS", "2": "GND"}, "3V3", "LDO input")
    add("C5", C, "10u", FP_C["0805"], {"1": "+3V3", "2": "GND"}, "3V3", "LDO output")
    add("C19", C, "10u", FP_C["0805"], {"1": "+3V3", "2": "GND"}, "3V3", "3V3 bulk")
    add("D1", LED, "green", FP_LED, {"1": "GND", "2": "PWR_A"}, "3V3", "power LED")
    add("R14", R, "220R", FP_R["0402"], {"1": "+3V3", "2": "PWR_A"}, "3V3", "LED series (Vf 3.1 V)")

    # 1.8 V for the ST60, the repeater and the translator's A side. The
    # TLV755P discharges its output when disabled, which is what makes
    # dropping EN a real power-on reset for the ST60 (supply fall 50 us-1 ms,
    # DS table 8).
    add("U7", "Regulator_Linear:TLV75518PDBV", "TLV75518P",
        "Package_TO_SOT_SMD:SOT-23-5",
        {"1": "+3V3", "2": "GND", "3": "ST_PWR_EN", "4": "", "5": "+1V8"},
        "1V8", "1.8 V LDO with output discharge")
    add("C32", C, "1u", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "1V8", "LDO input")
    add("C33", C, "1u", FP_C["0402"], {"1": "+1V8", "2": "GND"}, "1V8", "LDO output")
    # Off until the RP2350 raises EN: the rail then always rises with 3V3
    # settled, at the regulator's own controlled rate (4k7: erratum E9).
    add("R15", R, "4k7", FP_R["0402"], {"1": "GND", "2": "ST_PWR_EN"}, "1V8",
        "EN pull-down: 1.8 V off until the RP2350 turns it on")
    return out


# The OV2640's signals, on the header GPIO: when no camera is plugged in they
# are the header's pins and nothing else.
#
#   0..7    Y2..Y9, the eight data bits, in order (one PIO `in pins, 8`)
#   21      VSYNC
#   22/23   SIOD/SIOC   I2C1 SDA/SCL. I2C1 is the configuration bus's too, on
#                   18/19: one peripheral, moved between two pairs of pins,
#                   and the two buses never share a wire
#   24      PWDN    pulled up: the camera sleeps until the RP2350 wakes it
#   26      HREF
#   27      XCLK    the camera's clock, from PWM slice 5 (channel B) or PIO
#   28      PCLK
#                   26..28 are the ADC pins: no resistor is put on them, so
#                   they are still ADC inputs when no camera is fitted. 29
#                   is left alone.
#
# Which signal has which of 21..28 is decided by the copper: taken in the
# order the header's pins stand, the tracks reach the connector's pads side
# by side on one layer with none crossing (gen_board.camera_copper).
#
# RESET has no pin: 10 k and 1 u hold it low through power-up, and the
# sensor has a software reset (COM7 bit 7).
CAM = {"Y2": "GP0", "Y3": "GP1", "Y4": "GP2", "Y5": "GP3", "Y6": "GP4", "Y7": "GP5",
       "Y8": "GP6", "Y9": "GP7", "VSYNC": "GP21", "SIOD": "GP22", "SIOC": "GP23",
       "PWDN": "GP24", "HREF": "GP26", "XCLK": "GP27", "PCLK": "GP28",
       "RESET": "CAM_RST", "DOVDD": "+3V3", "DVDD": "CAM_1V3", "AVDD": "CAM_2V8",
       "DGND": "GND", "AGND": "GND", "NC": "", "Y0": "", "Y1": ""}
# The module's 24-way tail (0.5 mm pitch), numbered the way the connector
# numbers it -- which is the way the ESP32-CAM's schematic does. The module
# makers number the other way round: their pin 1 is this list's 24. (Checked
# against a module drawing: contacts on the face away from the lens, and
# with the tail toward you and the contacts up, the maker's 24 on the left.)
CAM_PINS = ["Y0", "Y1", "Y4", "Y3", "Y5", "Y2", "Y6", "PCLK", "Y7", "DGND", "Y8", "XCLK",
            "Y9", "DOVDD", "DVDD", "HREF", "PWDN", "VSYNC", "RESET", "SIOC", "AVDD", "SIOD",
            "AGND", "NC"]


def camera():
    """04_camera: a connector for the common OV2640 module (24-way flex, DVP,
    the ESP32-CAM's), and the two supplies the sensor wants besides 3.3 V.
    All of it is on the back of the board: the lens then looks away from
    the board the 60 GHz link faces."""
    sh, out = "04_camera", []
    def add(ref, lib_id, value, fp, nets, group, note="", dnp=False):
        out.append(Comp(ref, lib_id, value, fp, nets, sh, group, dnp, note))

    j = {str(i + 1): CAM[name] for i, name in enumerate(CAM_PINS)}
    j["MP"] = "GND"
    add("J5", "Connector_Generic_MountingPin:Conn_01x24_MountingPin", "OV2640",
        "Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal", j, "camera",
        "24-way 0.5 mm flex, bottom contact; on the back, the flex leaving toward the USB end")
    # Core 1.3 V: OmniVision's data sheet from v1.8 on (1.24 to 1.36 V; the
    # older sheets said 1.2 V, which is what the ESP32-CAM gives it and is
    # now 40 mV under the minimum). Analogue 2.8 V. I/O is 3.3 V, as the
    # RP2350's. The 1.3 V part is Microne's ME6216, pin for pin an XC6206.
    add("U11", "Regulator_Linear:XC6206PxxxMR", "XC6206P282MR", "Package_TO_SOT_SMD:SOT-23",
        {"1": "GND", "2": "CAM_2V8", "3": "+3V3"}, "supplies", "2.8 V for the sensor's analogue side")
    add("U12", "Regulator_Linear:XC6206PxxxMR", "ME6216A13M3G", "Package_TO_SOT_SMD:SOT-23",
        {"1": "GND", "2": "CAM_1V3", "3": "+3V3"}, "supplies", "1.3 V for the sensor's core")
    add("C40", C, "1u", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "supplies", "2.8 V regulator input")
    add("C41", C, "1u", FP_C["0402"], {"1": "CAM_2V8", "2": "GND"}, "supplies", "2.8 V regulator output")
    add("C44", C, "1u", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "supplies", "1.3 V regulator input")
    add("C42", C, "1u", FP_C["0402"], {"1": "CAM_1V3", "2": "GND"}, "supplies", "1.3 V regulator output")
    # ... and 100 n on each rail where it meets the connector: the regulators
    # are 20 mm away, down the board
    add("C45", C, "100n", FP_C["0402"], {"1": "CAM_2V8", "2": "GND"}, "camera", "AVDD, at the connector")
    add("C46", C, "100n", FP_C["0402"], {"1": "CAM_1V3", "2": "GND"}, "camera", "DVDD, at the connector")
    add("C47", C, "100n", FP_C["0402"], {"1": "+3V3", "2": "GND"}, "camera", "DOVDD, at the connector")
    add("R40", R, "4k7", FP_R["0402"], {"1": "GP22", "2": "+3V3"}, "camera", "SIOD pull-up")
    add("R41", R, "4k7", FP_R["0402"], {"1": "GP23", "2": "+3V3"}, "camera", "SIOC pull-up")
    add("R42", R, "10k", FP_R["0402"], {"1": "CAM_RST", "2": "+3V3"}, "camera", "RESET pull-up")
    add("C43", C, "1u", FP_C["0402"], {"1": "CAM_RST", "2": "GND"}, "camera",
        "RESET held low through power-up: 10 ms, where OmniVision asks for 3")
    add("R43", R, "10k", FP_R["0402"], {"1": "GP24", "2": "+3V3"}, "camera",
        "PWDN pull-up: the camera sleeps until GPIO24 goes low")
    return out


def mechanical():
    out = []
    for i in range(1, 5):
        out.append(Comp(f"H{i}", "Mechanical:MountingHole", "M2.5",
                        "MountingHole:MountingHole_2.7mm_M2.5", {}, "01_mcu",
                        "mechanical", note="M2.5; the pattern is mirror-symmetric about the antenna's axis"))
    for i in range(1, 4):
        out.append(Comp(f"FID{i}", "Mechanical:Fiducial", "Fiducial",
                        "Fiducial:Fiducial_1mm_Mask2mm", {}, "01_mcu",
                        "mechanical", note="for the placement machine; three, not symmetric"))
    return out


def board():
    return mcu() + link() + usb_power() + camera() + mechanical()


# --------------------------------------------------------------- checking ---
def nets(comps=None):
    """{net: [(ref, pin), ...]} over the whole board."""
    out = {}
    for c in (comps or board()):
        for pin, net in c.nets.items():
            if net:
                out.setdefault(net, []).append((c.ref, pin))
    return out

def check(comps=None):
    comps = comps or board()
    bad = []
    seen = set()
    for c in comps:
        if c.ref in seen:
            bad.append(f"{c.ref} appears twice")
        seen.add(c.ref)
        want = set(pins(c.lib_id))
        got = set(c.nets)
        for p in sorted(want - got):
            bad.append(f"{c.ref} ({c.lib_id}) pin {p} "
                       f"({pins(c.lib_id)[p][3]}) has no net")
        for p in sorted(got - want):
            bad.append(f"{c.ref} ({c.lib_id}) has a net on pin {p}, "
                       f"which the symbol does not have")
    for net, conns in nets(comps).items():
        if len(conns) < 2:
            bad.append(f"net {net} has one connection: {conns}")
    used = {n for c in comps if c.ref == "U1" for n in c.nets.values()}
    for g, name in GP.items():
        if name not in used:
            bad.append(f"GPIO{g} ({name}) is not on U1")
    return bad

def report():
    comps = board()
    n = nets(comps)
    print(f"comms netlist: {len(comps)} components, {len(n)} nets, "
          f"{sum(len(v) for v in n.values())} pin connections")
    for sh, _ in SHEETS:
        cs = [c for c in comps if c.sheet == sh]
        print(f"  {sh:14s} {len(cs):3d} components")
    big = sorted(n.items(), key=lambda kv: -len(kv[1]))[:6]
    print("  busiest nets: " + ", ".join(f"{k} ({len(v)})" for k, v in big))
    bad = check(comps)
    if bad:
        print(f"\n{len(bad)} PROBLEM(S):")
        for b in bad:
            print("  !", b)
    else:
        print("\nclean: every symbol pin has a net or is marked unused, "
              "every net has at least two connections.")
    return bad

if __name__ == "__main__":
    import sys
    sys.exit(1 if report() else 0)
