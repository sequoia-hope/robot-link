# robot-link (comms)

### ▶ [Project page: schematic, PCB and 3D viewer](https://sequoia-hope.github.io/robot-link/)

A dev board for ST's 60 GHz contactless link: an **RP2350A** beside an
**ST60A3H1** (antenna in the package), 28 × 63 mm, four layers. Two boards
face each other a few centimetres apart and tunnel UART, GPIO, I²C or
USB 2.0 between them. The same board is either end.

**Status: rev A captured, placed, routed and reviewed. 85 parts, 80 nets;
KiCad's DRC and ERC report nothing, KiCad's own netlist of the drawn
schematic matches `tools/circuit.py` net for net, every placed part has an
LCSC number and the assembly check passes. Not fabricated, and no firmware
yet.** The review (2026-10-02) and what it changed are [below](#review).

- `index.html` — status page with the board viewer (SCH, PCB, 3D); published
  from `main` at <https://sequoia-hope.github.io/robot-link/> by GitHub Pages, and
  served locally with `proj up comms`, address from `proj url comms`
- `hardware/comms/` — the KiCad project
- `tools/` — everything is generated; see below

## Why the ST60A3H1 and not the ST60A2G0

The board was asked for with the ST60A2G0. That part's ball map, pin
functions and the 60 GHz antenna and PCB-transition design are only in ST's
NDA package; the public data brief has the package outline and a block
diagram. The ST60A3H1 is the same family with a public data sheet
(DS14598) and the antenna in the package, so there is no 60 GHz copper to
design. It gives up speed: 480 Mbit/s (eUSB2) against the A2's 6.25 Gbit/s
SLVS.

## What is on it

| | |
|---|---|
| MCU | RP2350A with its core regulator, crystal, flash and decoupling as Raspberry Pi's minimal design (RP-006440) has them — the copper round the chip is read out of that board file |
| Link | ST60A3H1 on a grounded island with a copper-free ring round it, 3.5 mm in from the board edge, as on ST's X-NUCLEO-60K1A1 (B2379A) |
| Translator | TXS0108E, 1.8 V ↔ 3.3 V, on the configuration bus, the four tunnel pins, MODE_INT and LINK_STATUS; off until the RP2350 enables it. 4k7 pull-ups on the 1.8 V side of the configuration bus and of the tunnelled SCL/SDA |
| USB | PTN3222 eUSB2 repeater and two TS3USB221A switches: connector, RP2350 and the 60 GHz link, any two joined |
| Power | USB-C 5 V → AMS1117-3.3 → TLV75518P (1.8 V, off until GPIO11 goes high; dropping it is the ST60's power-on reset) |
| I/O | two 1 × 16 headers 0.9 in apart, SWD on JST-SH, BOOTSEL, RUN, power / link / user LEDs |
| Mechanical | four M2.5 holes mirrored about the antenna's axis: a second board turned over on standoffs puts the two antennas on one line. Three fiducials |

GPIO map (`tools/circuit.py` has the reasons): 0–7 right-hand header · 8/9 USB
path selects · 10 RF_EN · 11 1.8 V enable · 12/13 tunnelled SDA/SCL (I2C0) ·
14 LINK_STATUS · 15 MODE_INT · 16/17 tunnelled TXD/RXD (UART0) · 18/19
configuration bus (I2C1; ST60A3H1 at 0x60, PTN3222 at 0x43) · 20 translator
enable · 21–24, 26–29 left-hand header · 25 LED.

## Board rules

Four layers, JLCPCB's JLC04161H-7628 stack: F.Cu parts and signals, In1 solid
ground, In2 supplies (+3V3, with +1V8 over the link section), B.Cu signals
and ground. Routed signals are 0.125 mm track and clearance (JLCPCB's
four-layer floor is 0.09), and so are the ST60's ball escapes. The USB pairs
on the back are 0.28 mm wide and 0.16 mm apart. Vias 0.46 / 0.2 mm. All
parts on the front.

## Ordering and using it

- **JLCPCB Standard PCBA, not Economic**: the ST60A3H1 is a 0.4 mm BGA, and
  Economic stops at 0.5 mm. Standard wants edge rails (JLCPCB adds them) and
  fiducials (three are on the board). Ask for a 0.10 mm stencil.
- Green solder mask: the ST60's mask openings are 0.30 mm on 0.25 mm lands,
  which leaves 0.10 mm webs between balls, JLCPCB's minimum for green.
- Four vias sit in the gap in the ST60's ball field, tented. Plugged vias
  are the safer order.
- Fit the headers **pins down**, and use **nylon** standoffs at the antenna
  end (H1, H2): metal 11 mm from the patch is inside its beam.
- Firmware: +1V8 is off at reset. Raise GPIO11, wait 2.25 ms, then enable
  the translator (GPIO20) and RF_EN (GPIO10). Before dropping +1V8, take
  both low first. The PTN3222 is held in reset whenever the RF link is down,
  so anything written to it has to be written again after each link-up.
- VBUS on the headers is the USB-C connector's VBUS, direct: it is an
  output. Do not feed 5 V into it with a host plugged in.
- Pull-ups added on J2/J3 (the 3.3 V side of the translator) should be
  8k2 or more.

## The tools

```
python3 tools/circuit.py        # the netlist, as data, and its checks
python3 tools/symbols.py        # hardware/parts/comms.kicad_sym
python3 tools/footprints.py     # hardware/parts/comms.pretty
python3 tools/placement.py      # where every part sits, and its checks
python3 tools/gen_board.py --force   # project, schematic and the unrouted board (DISCARDS routing)
python3 tools/route.py          # freerouting on a stripped copy, results copied back, stitching
python3 tools/schdraw.py --check     # KiCad's netlist of the schematic against circuit.py
python3 tools/assembly.py       # IPC-2581, the pin-1 answers beside it, boardvis's check
python3 tools/regen.py          # every check, then the viewer and the status line on index.html
```

`gen_board.py` lays the copper that is decided rather than routed: Raspberry
Pi's tracks and pours round the RP2350, the ST60's ball field and antenna
ground (ST's own via pattern, hole for hole where it fits), the 480 Mbit/s
USB pair, a via beside every pad on a plane net.
`route.py` hands the remaining ~65 signals to freerouting 2.2.4
(`~/Software/magnet/route`); it is not deterministic, so it makes several
attempts and keeps the first that closes everything.

## Review

Two independent passes on 2026-10-02, one over the schematic against the
data sheets and one over the layout against JLCPCB's limits and ST's
reference board. Neither found anything that would stop the board working.
What they found, and what was done:

| Finding | Done |
|---|---|
| The antenna ground was a quarter of ST's: 13 vias in the island and 15 round it, where B2379A has 53 and 56; the signals crossed the island on a diagonal | The ball field is laid as ST lays it: nine signals straight out through one side of the ring, the supply along the top of them. ST's vias are taken from its drill file: 33 fit in the island and 45 round it |
| +1V8 fall time marginal against the ST60's 1 ms limit (3.3 µF on a 120 Ω discharge) | 1.8 µF on the rail; the regulator's enable is pulled down, so the rail only rises with 3V3 settled |
| MODE_INT strap undefined if +1V8 is cycled with the translator on | 4k7 to ground on MODE_INT |
| No pull-ups on the I²C lines; ST60 and PTN3222 both want external ones | 4k7 to +1V8 on the configuration bus and on GPIO[2]/[3] |
| USB pair geometry computed at 100 Ω; it crossed two plane splits and ran 2.4 mm over no plane | 0.28 / 0.16 mm (89 Ω by the reviewer's field solver); +1V8 plane redrawn so the pair has +3V3 under it throughout; its copper now 0.8 mm from the board edge, not 0.57 |
| Solder-mask webs between balls 0.075 mm | Mask opening 0.30 mm, webs 0.10 mm |
| Silkscreen under JLCPCB's 1.0 mm / 0.15 mm | Back labels 1.0 mm, front 0.8 mm (what fits a 2.54 mm pitch), all lines 0.15 mm |
| VBUS ran under the USB-C shell | Joined on the back |
| LEDs near dark at 1 kΩ (Vf 3.1 V) | 220 Ω |
| No fiducials | Three |
| Four 3V3 capacitors at the RP2350 fed only through the ring under the chip; one via pair into the plane at the regulator | A via beside each of the four capacitors; five more at the regulator's tab |

Left as it is, knowingly:

- **TXS0108E on the I²C lines.** The reviewer would rather have a pass-FET
  translator with no edge accelerators there: the ST60 has no glitch filter
  on CFG_SCL. ST's own board uses an auto-direction part (ST2378E) on the
  same lines; that part's data sheet was not read. If the configuration bus
  misbehaves with wiring on J2, this is the first place to look.
- **AMS1117 with ceramic output capacitors**, as Raspberry Pi's reference has
  an 1117: outside what the AMS data sheet characterises (22 µF tantalum).
  It needs about 1 V of headroom, so VBUS has to stay above 4.35 V.
- **The crystal** is servodrive's 2520 (CL 20 pF) with 27 pF, where Raspberry
  Pi specifies an ABM8-272 with 15 pF and says any change needs testing.
- **USB pair skew**: D− is 1.1 mm longer than D+ between the connector and
  the first switch (its two pads are joined under the shell). The long run
  to the repeater is matched to 0.05 mm.
- **The ground guard round the crystal** in the reference was not copied;
  three signals pass within 0.13 mm of the crystal nets.

## Not yet verified

- Nothing has been built. The ST60A3H1 land and the PTN3222 land are drawn
  from the manufacturers' drawings, not from a part in hand.
- The antenna island copies ST's dimensions and vias off their Gerbers; the
  pattern on this board has not been simulated or measured, and it has
  fewer vias than ST's where this board's tracks are in the way.
- The 89 Ω figure for the USB pairs is one reviewer's solver, checked
  against a textbook formula only. Confirm with JLCPCB's calculator.
- JLCPCB capability figures were read off their site on 2026-10-02 through
  a summarising tool, not from the raw pages. Check them at order time.
- Several pin-1 answers in the assembly sidecar are package convention,
  not read off that part's data sheet; the sidecar says which.

## Next

Rev A review, then an OV2640 camera interface to the RP2350.

CERN-OHL-P.
