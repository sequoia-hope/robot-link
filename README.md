# robot-link (comms)

### ▶ [Project page: schematic, PCB and 3D viewer](https://sequoia-hope.github.io/robot-link/)

A dev board for ST's 60 GHz contactless link: an **RP2350A** beside an
**ST60A3H1** (antenna in the package), 28 × 63 mm, four layers. Two boards
face each other a few centimetres apart and tunnel UART, GPIO, I²C or
USB 2.0 between them. The same board is either end.

**Status: rev A captured, placed and routed. 78 parts, 80 nets; KiCad's DRC
and ERC report nothing, and KiCad's own netlist of the drawn schematic matches
`tools/circuit.py` net for net. Not reviewed, not fabricated.** Still to do
before ordering: LCSC numbers for every part, assembly drawings, a review
pass over the layout, and the firmware that would prove the pin map.

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
| Translator | TXS0108E, 1.8 V ↔ 3.3 V, on the configuration bus, the four tunnel pins, MODE_INT and LINK_STATUS; off until the RP2350 enables it |
| USB | PTN3222 eUSB2 repeater and two TS3USB221A switches: connector, RP2350 and the 60 GHz link, any two joined |
| Power | USB-C 5 V → AMS1117-3.3 → TLV75518P (1.8 V, switchable: dropping it is the ST60's power-on reset) |
| I/O | two 1 × 16 headers 0.9 in apart, SWD on JST-SH, BOOTSEL, RUN, power / link / user LEDs |
| Mechanical | four M2.5 holes mirrored about the antenna's axis: a second board turned over on standoffs puts the two antennas on one line |

GPIO map (`tools/circuit.py` has the reasons): 0–7 right-hand header · 8/9 USB
path selects · 10 RF_EN · 11 1.8 V enable · 12/13 tunnelled SDA/SCL (I2C0) ·
14 LINK_STATUS · 15 MODE_INT · 16/17 tunnelled TXD/RXD (UART0) · 18/19
configuration bus (I2C1; ST60A3H1 at 0x60, PTN3222 at 0x43) · 20 translator
enable · 21–24, 26–29 left-hand header · 25 LED.

## Board rules

Four layers, JLCPCB's JLC04161H-7628 stack: F.Cu parts and signals, In1 solid
ground, In2 supplies (+3V3, with +1V8 and the ST60's own rail as islands),
B.Cu signals and ground. Routed signals are 0.125 mm track and clearance
(JLCPCB's four-layer floor is 0.09); everything laid by the generator is 0.15
or wider. Vias 0.46 / 0.2 mm. All parts on the front.

## The tools

```
python3 tools/circuit.py        # the netlist, as data, and its checks
python3 tools/symbols.py        # hardware/parts/comms.kicad_sym
python3 tools/footprints.py     # hardware/parts/comms.pretty
python3 tools/placement.py      # where every part sits, and its checks
python3 tools/gen_board.py --force   # project, schematic and the unrouted board (DISCARDS routing)
python3 tools/route.py          # freerouting on a stripped copy, results copied back, stitching
python3 tools/schdraw.py --check     # KiCad's netlist of the schematic against circuit.py
~/Software/pcbview/bin/pcbview build pcbview.toml    # the viewer on index.html
```

`gen_board.py` lays the copper that is decided rather than routed: Raspberry
Pi's tracks and pours round the RP2350, the ST60's ball field and antenna
ground, the 480 Mbit/s USB pair, a via beside every pad on a plane net.
`route.py` hands the remaining ~60 signals to freerouting 2.2.4
(`~/Software/magnet/route`); it is not deterministic, so it makes several
attempts and keeps the first that closes everything.

## Not yet verified

- Nothing has been built. The ST60A3H1 land and the PTN3222 land are drawn
  from the manufacturers' drawings, not from a part in hand.
- The USB pair's 0.2 / 0.16 mm geometry is an estimate of 90 Ω on this stack,
  not a field-solver result.
- The antenna island copies ST's dimensions off their Gerbers; the pattern
  on this board has not been simulated or measured.
- JLCPCB capability figures quoted here are from memory; check them at order
  time.

## Next

Rev A review, then an OV2640 camera interface to the RP2350.

CERN-OHL-P.
