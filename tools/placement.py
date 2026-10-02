#!/usr/bin/env python3
"""placement.py -- where every part on the comms board sits, and why.

Board coordinates: millimetres, x to the right, y DOWN (KiCad's sense), the
origin at the middle of the top edge. The top edge is the antenna's edge.

    python3 tools/placement.py        # the table, and the checks

The board from the top:

      y = 0  +---------------- antenna edge -----------------+
             | H1      [  ST60A3H1 on its ground island  ]   H2 |
        7    |   ST60 caps   moat        RF_EN divider          |
             | LED  PTN3222      TXS0108E (A side up)           |
       17    | 1V8 LDO                                          |
             |              crystal                             |
             | J2          RP2350A (turned 180)             J3  |
             | (left)    core regulator   flash           (right)|
             |                                                   |
             |            USB switches     BOOTSEL  RUN          |
             | 3V3 LDO        ESD                          SWD > |
             | H3           [ USB-C ]                        H4  |
      y = 63 +---------------------------------------------------+

Three things fix everything else:

  1. The ST60A3H1's patch antenna sits on the board's centre line, x = 0,
     and the four mounting holes are mirror images about that line. Turn a
     second board over, face to face on standoffs, and the two patches are
     on one axis -- which is how the part is meant to be used (DS14598
     fig. 29, +/-2 mm of alignment at 30 mm).
  2. The ST60's surroundings are ST's: the package 3.5 mm in from the board
     edge with row N (the patch end) toward the edge, a 5 x 6 mm grounded
     island under it and a 0.5 mm copper-free moat round the island, as on
     the X-NUCLEO-60K1A1 (B2379A) whose radiation pattern the data sheet
     quotes. See gen_board.py, antenna_ground().
  3. The RP2350A is turned half round from the reference design, so that the
     side with USB, the core regulator and QSPI faces the USB-C connector
     and the side with GPIO12-19 faces the translator. Every part of the
     reference's cluster keeps its place in the chip's own frame.
"""
from math import cos, sin, radians

W, H = 28.0, 63.0              # board outline
CORNER_R = 2.0

# ------------------------------------------------------------- the ST60 ----
ST60 = (0.0, 3.5)              # package centre; 3.5 mm from the edge, as B2379A
ISLAND = (2.5, 3.0)            # half-extents of the grounded island under it
MOAT = 0.5                     # copper-free ring round the island (F.Cu)
PATCH = (0.0, 3.5 - 1.184)     # the antenna patch's centre on the board

# -------------------------------------------------------------- the MCU ----
U1 = (0.0, 30.3)
U1_ROT = 180

def in_chip(dx, dy, rot=0):
    """A position given in the RP2350's own (reference-design) frame."""
    a = radians(U1_ROT)
    x = U1[0] + dx * cos(a) + dy * sin(a)
    y = U1[1] - dx * sin(a) + dy * cos(a)
    return (round(x, 4), round(y, 4), (rot + U1_ROT) % 360)

# The reference's cluster, in its own coordinates relative to U1 (the
# reference board has U1 at 100, 100 and is not turned): reference
# designator, our designator, dx, dy, rotation.
REFERENCE = [
    # ref   ours    dx      dy     rot
    ("L1",  "L1",   2.0,   -7.2,    0),
    ("C6",  "C6",   2.0,   -4.6,    0),
    ("C7",  "C7",   2.0,   -5.55,   0),
    ("C9",  "C9",   4.2,   -5.05, -90),
    ("R5",  "R5",   4.2,   -6.9,  -90),
    ("R7",  "R7",  -1.1,   -7.4,  -90),
    ("R8",  "R8",  -0.1,   -7.4,  -90),
    ("C12", "C12", -2.1,   -7.4,   90),
    ("C13", "C13", -6.485, -3.4,  180),
    ("C8",  "C8",  -6.48,  -1.0,  180),
    ("C15", "C15", -6.485,  1.4,  180),
    ("C18", "C18", -1.8,    6.08, -90),
    ("R2",  "R2",  -0.4,    6.9,  -90),
    ("C10", "C10",  0.8,    6.88, -90),
    ("C16", "C16",  5.685,  4.0,    0),
    ("C14", "C14",  7.085,  0.4,    0),
    ("C11", "C11",  7.08,  -0.6,    0),
    ("C17", "C17",  6.485, -3.0,    0),
    # the crystal's caps keep their places; the crystal itself comes in
    # closer than the reference's 3225 did, being a 2520
    ("C3",  "C3",  -1.4,    9.0,  180),
    ("C4",  "C4",   1.58,   9.0,    0),
    ("Y1",  "Y1",   0.0,   11.05,   0),
]

# ------------------------------------------------------------ everything ---
# ref: (x, y, rotation). Rotation is KiCad's, counter-clockwise positive.
PLACE = {
    "U4": (*ST60, 180),            # row N toward the board edge, column 1 to the right
    "U1": (*U1, U1_ROT),

    # -- the ST60's supply, left of the island, outside the moat
    "C21": (-4.3, 5.0, 90),        # 100 n, VDD_1V8
    "C22": (-4.3, 2.0, 90),        # 100 n, VDD_IO
    "C23": (-5.6, 3.5, 90),        # 1 u
    "R20": (-8.0, 7.15, 90),       # the 0 R link: +1V8 below it, ST_VDD above

    # -- RF_EN divider, right of the island where the bundle opens out
    "R21": (6.4, 5.6, 0),
    "R22": (6.4, 4.4, 0),

    # -- translator, A side (1.8 V) toward the ST60, B side toward the RP2350
    "U6": (0.3, 13.6, 270),
    "C24": (4.4, 11.3, 90),        # VCCA
    "C25": (4.4, 16.3, 90),        # VCCB
    "R28": (-3.85, 12.7, 90),      # OE pull-down

    # -- eUSB2 repeater, left of the translator; eDP/eDN on its top edge
    "U5": (-6.6, 9.9, 270),
    "C26": (-4.1, 8.9, 90),        # VDD1V8 1 u
    "C27": (-4.1, 10.8, 270),      # VDD1V8 100 p, its 1.8 V pad beside ADDR
    "C28": (-5.3, 12.5, 0),        # VDD3V3 1 u; the USB pair comes up between these two
    "C29": (-8.5, 12.5, 180),      # VDD3V3 100 p
    "R23": (-8.9, 9.6, 90),        # LINK_STATUS pull-down, by RST_N

    # -- link LED and its driver, below the repeater (LINK_STATUS is there anyway)
    "R29": (-7.2, 13.5, 180),
    "Q1": (-7.3, 15.8, 0),
    "D2": (-4.6, 16.0, 90),
    "R30": (-4.6, 18.6, 90),

    # -- 1.8 V regulator, right of the translator: output toward the +1V8
    #    zone on In2, input over the +3V3 plane
    "U7": (7.0, 9.6, 180),
    "C33": (5.9, 12.4, 270),
    "C32": (8.6, 12.4, 270),
    "R15": (8.0, 6.9, 270),

    # -- flash, below and right of the RP2350, pads in the order the chip's
    #    QSPI pins come off its edge
    "U3": (6.4, 38.8, 270),
    "C2": (6.4, 41.5, 0),
    "R6": (7.6, 35.9, 0),

    # -- USB: connector, ESD, the two switches
    "J1": (0.0, H - 3.15, 0),
    "U8": (0.0, 52.3, 270),
    "R10": (-2.4, 53.4, 90),
    "R11": (2.4, 53.4, 90),
    "U9": (0.0, 48.9, 270),        # connector side: D+/D- on its bottom edge
    "C30": (2.1, 48.9, 90),
    "R12": (3.3, 48.9, 90),
    "U10": (0.6, 43.0, 90),        # RP2350 side: D+/D- on its top edge, under R7/R8
    "C31": (-1.45, 43.0, 90),
    "R13": (-1.45, 41.0, 90),

    # -- 3.3 V regulator, left of the switches: input pin toward the connector
    "U2": (-5.6, 44.6, 90),
    "C1": (-3.6, 50.4, 0),
    "C5": (-6.5, 38.6, 0),
    "C19": (-7.3, 36.0, 0),
    "D1": (-7.8, 51.0, 0),
    "R14": (-7.8, 52.7, 0),

    # -- buttons, user LED, debug connector: bottom right
    "SW1": (6.9, 43.9, 0),
    "SW2": (6.9, 47.7, 0),
    "R4": (3.9, 46.4, 90),
    "D3": (-7.8, 54.6, 0),
    "R9": (-7.8, 56.2, 0),
    "J4": (10.8, 52.9, 90),

    # -- headers, 0.9 inch apart, pin 1 at the top
    "J2": (-11.43, 9.5, 0),
    "J3": (11.43, 9.5, 0),

    # -- mounting holes, mirror images about the antenna's axis
    "H1": (-11.0, 3.8, 0),
    "H2": (11.0, 3.8, 0),
    "H3": (-11.0, 59.6, 0),
    "H4": (11.0, 59.6, 0),
}
for _ref, ours, dx, dy, rot in REFERENCE:
    PLACE[ours] = in_chip(dx, dy, rot)


def table():
    for ref in sorted(PLACE, key=lambda r: (r.rstrip("0123456789"), int("".join(c for c in r if c.isdigit()) or 0))):
        x, y, a = PLACE[ref]
        print(f"  {ref:5s} {x:8.3f} {y:8.3f} {a:5.0f}")


def check():
    import circuit
    bad = []
    refs = {c.ref for c in circuit.board()}
    for r in sorted(refs - set(PLACE)):
        bad.append(f"{r} is in the netlist but is not placed")
    for r in sorted(set(PLACE) - refs):
        bad.append(f"{r} is placed but is not in the netlist")
    for r, (x, y, a) in PLACE.items():
        if not (-W / 2 <= x <= W / 2 and 0 <= y <= H):
            bad.append(f"{r} at ({x}, {y}) is off the board")
    # the antenna axis: patch on the centre line, holes mirrored about it
    if PATCH[0] != 0:
        bad.append("the antenna patch is off the centre line")
    for a, b in (("H1", "H2"), ("H3", "H4")):
        if (PLACE[a][0], PLACE[a][1]) != (-PLACE[b][0], PLACE[b][1]):
            bad.append(f"{a} and {b} are not mirror images about x = 0")
    return bad


if __name__ == "__main__":
    import sys
    table()
    bad = check()
    print("\n".join("  ! " + b for b in bad) if bad else
          "\nclean: every part placed once, on the board; antenna on the centre line, holes mirrored")
    sys.exit(1 if bad else 0)
