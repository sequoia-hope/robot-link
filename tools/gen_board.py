#!/usr/bin/env python3
"""gen_board.py -- emit the comms KiCad project from the netlist and the placement.

    python3 tools/gen_board.py            # create anything missing
    python3 tools/gen_board.py --force    # overwrite, DESTROYS routing

What it writes, in hardware/comms/:

  comms.kicad_pro     design rules and net classes
  comms.kicad_pcb     the board: outline, parts, planes, and the copper that
                      is decided rather than routed (below)
  comms.kicad_sch + three sheets      (tools/schlayout.py draws them)
  fp-lib-table, sym-lib-table

The copper this file lays, all of it locked so the router leaves it alone:

  - round the RP2350, Raspberry Pi's: every track, via and pour that the
    RP2350A minimal design (RP-006440) has on the core regulator, the 1V1
    and 3V3 rings under the chip, the decoupling and the USB series
    resistors, read out of that board file and turned with the chip
  - under the ST60A3H1, ST's: the grounded island and the moat round it
    (antenna_ground), the eUSB2 pair tied TX to RX inside the ball field and
    taken out on the back, the supply balls into the ST_VDD plane
  - a via beside every surface-mount pad on a net that lives on a plane
    (GND, +3V3, +1V8, ST_VDD), so those nets never reach the router

What is left -- the signals -- tools/route.py hands to freerouting.

Refuses to overwrite an existing .kicad_pcb without --force: once the board
is routed, this script is no longer the source of truth for that file.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit as CIR
import placement as PL
import copper as CU

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "comms"
NAME = "comms"
PCB = HW / f"{NAME}.kicad_pcb"
PRO = HW / f"{NAME}.kicad_pro"
KFP = Path("/usr/share/kicad/footprints")
PROJ_FP = ROOT / "hardware/parts/comms.pretty"
RPI_REF = Path("/home/sequoia/pcb/RP-006440-DD-2-RP2350A Minimal Board Kicad archive"
               "/RP2350_60QFN_minimal.kicad_pcb")
uid = CIR._uid

# The board's origin (middle of the top edge) on the KiCad page.
OX, OY = 100.0, 40.0
mm = pcbnew.FromMM
def V(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))

TITLE = "comms — RP2350A + ST60A3H1 60 GHz contactless link"
REV, DATE = "A", "2026-10-01"

# ------------------------------------------------------------ the stack ----
# JLCPCB's four-layer JLC04161H-7628: 0.21 mm of 7628 prepreg under each
# outer layer, a 1.065 mm core. F.Cu and B.Cu carry the signals; In1 is solid
# ground, directly under the parts and the antenna; In2 is the supplies.
COPPER = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
LAYER_IDS = {"F.Cu": 0, "B.Cu": 2, "In1.Cu": 4, "In2.Cu": 6}
LAYER_TYPE = {"F.Cu": "signal", "In1.Cu": "power", "In2.Cu": "power", "B.Cu": "signal"}
PREPREG, CORE, CU_OUT, CU_IN, MASK = 0.2104, 1.065, 0.035, 0.0152, 0.01
USER_LAYERS = '''		(9 "F.Adhes" user "F.Adhesive")
		(11 "B.Adhes" user "B.Adhesive")
		(13 "F.Paste" user)
		(15 "B.Paste" user)
		(5 "F.SilkS" user "F.Silkscreen")
		(7 "B.SilkS" user "B.Silkscreen")
		(1 "F.Mask" user)
		(3 "B.Mask" user)
		(17 "Dwgs.User" user "User.Drawings")
		(19 "Cmts.User" user "User.Comments")
		(21 "Eco1.User" user "User.Eco1")
		(23 "Eco2.User" user "User.Eco2")
		(25 "Edge.Cuts" user)
		(27 "Margin" user)
		(31 "F.CrtYd" user "F.Courtyard")
		(29 "B.CrtYd" user "B.Courtyard")
		(35 "F.Fab" user)
		(33 "B.Fab" user)'''

def stackup():
    out = ['\t\t(stackup',
           '\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))',
           '\t\t\t(layer "F.Paste" (type "Top Solder Paste"))',
           f'\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness {MASK}))']
    diel = [("prepreg", PREPREG), ("core", CORE), ("prepreg", PREPREG)]
    for i, cu in enumerate(COPPER):
        th = CU_OUT if cu in ("F.Cu", "B.Cu") else CU_IN
        out.append(f'\t\t\t(layer "{cu}" (type "copper") (thickness {th}))')
        if i < len(diel):
            kind, t = diel[i]
            out.append(f'\t\t\t(layer "dielectric {i + 1}" (type "{kind}") (thickness {t}) '
                       f'(material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))')
    out += [f'\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (thickness {MASK}))',
            '\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))',
            '\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))',
            '\t\t\t(copper_finish "ENIG")',
            '\t\t\t(dielectric_constraints no)',
            '\t\t)']
    return "\n".join(out)

def skeleton():
    """An empty board with the layers, the stack and the title block: the
    part of a board file pcbnew's API does not write."""
    o = ['(kicad_pcb', '\t(version 20241229)', '\t(generator "pcbnew")',
         '\t(generator_version "9.0")',
         '\t(general (thickness 1.6) (legacy_teardrops no))', '\t(paper "A4")',
         f'\t(title_block (title "{TITLE}") (date "{DATE}") (rev "{REV}")\n'
         f'\t\t(company "Sequoia Hope Alexander")\n'
         f'\t\t(comment 1 "Generated by tools/gen_board.py from tools/circuit.py and tools/placement.py")\n'
         f'\t\t(comment 2 "CERN-OHL-P"))',
         '\t(layers']
    for cu in COPPER:
        o.append(f'\t\t({LAYER_IDS[cu]} "{cu}" {LAYER_TYPE[cu]})')
    o += [USER_LAYERS, '\t)', '\t(setup', stackup(),
          '\t\t(pad_to_mask_clearance 0)',
          '\t\t(allow_soldermask_bridges_in_footprints yes)',
          '\t\t(tenting front back)',
          f'\t\t(aux_axis_origin {OX} {OY})', f'\t\t(grid_origin {OX} {OY})',
          '\t)', '\t(net 0 "")', '\t(embedded_fonts no)', ')']
    return "\n".join(o) + "\n"

# ------------------------------------------------------------- .kicad_pro ---
# Design rules. Routed signals are 0.125 mm (5 mil) track and clearance:
# round the RP2350 the reference design's capacitors leave each group of
# four GPIO pins a 1.4 mm gap, which at 0.15/0.15 is four tracks with 0.05 mm
# to spare and at 0.125/0.125 has room. JLCPCB's four-layer floor is 0.09.
# Everything this file lays by hand stays at 0.15 or wider. Vias are
# 0.46/0.2 at the smallest (annular ring 0.13).
VIA = (0.46, 0.2)              # plane taps, the ST60's ball field, stitching
VIA_REF = (0.6, 0.25)          # the reference design's own, round the RP2350
CLASSES = {
    "Power": ("VBUS", "+3V3", "+1V8", "+1V1", "ST_VDD", "VREG_LX", "VREG_AVDD"),
    "USB": ("USB_*", "RPT_*", "EUSB_*"),
}

def project():
    nets = [
        dict(name="Default", clearance=0.125, track_width=0.125, via_diameter=0.46,
             via_drill=0.2, microvia_diameter=0.3, microvia_drill=0.1,
             diff_pair_width=0.2, diff_pair_gap=0.15, diff_pair_via_gap=0.25,
             wire_width=6, bus_width=12, line_style=0, priority=2147483647,
             schematic_color="rgba(0, 0, 0, 0.000)", pcb_color="rgba(0, 0, 0, 0.000)"),
        dict(name="Power", track_width=0.3, via_diameter=0.6, via_drill=0.3),
        # 0.2 / 0.15 on 0.21 mm of 7628 over a solid plane is close to
        # 90 ohm differential; the runs are short.
        dict(name="USB", track_width=0.2, diff_pair_width=0.2, diff_pair_gap=0.15),
    ]
    base = nets[0]
    for i, n in enumerate(nets[1:]):
        for k, v in base.items():
            n.setdefault(k, v)
        n["priority"] = i
    return {
        "board": {
            "3dviewports": [], "design_settings": {
                "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2,
                             "copper_text_size_h": 1.0, "copper_text_size_v": 1.0,
                             "copper_text_thickness": 0.15, "other_line_width": 0.15,
                             "silk_line_width": 0.12, "silk_text_size_h": 0.8,
                             "silk_text_size_v": 0.8, "silk_text_thickness": 0.12},
                "diff_pair_dimensions": [], "drc_exclusions": [],
                # J1, J2 and J3 have their library silk taken off (silk()), and
                # that is all the difference this check would find
                "rule_severities": {"lib_footprint_mismatch": "ignore"},
                "rules": {
                    "allow_blind_buried_vias": False,
                    "allow_microvias": False,
                    "max_error": 0.005,
                    "min_clearance": 0.12,        # the floor; the net classes say 0.15 (see RULES)
                    "min_copper_edge_clearance": 0.3,
                    "min_hole_clearance": 0.25,
                    "min_hole_to_hole": 0.25,       # the reference design has vias 0.35 mm apart, hole to hole
                    "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1,
                    "min_resolved_spokes": 1, "min_silk_clearance": 0.0,
                    "min_text_height": 0.6, "min_text_thickness": 0.08,
                    "min_through_hole_diameter": 0.2,
                    "min_track_width": 0.125,
                    "min_via_annular_width": 0.13, "min_via_diameter": 0.45,
                    "solder_mask_to_copper_clearance": 0.0,
                },
                "track_widths": [0.0, 0.125, 0.15, 0.2, 0.25, 0.3, 0.5],
                "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                                   {"diameter": 0.46, "drill": 0.2},
                                   {"diameter": 0.6, "drill": 0.25},
                                   {"diameter": 0.6, "drill": 0.3}],
            },
            "layer_presets": [], "viewports": [],
        },
        "boards": [], "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": NAME + ".kicad_pro", "version": 3},
        "net_settings": {"classes": nets, "meta": {"version": 4}, "net_colors": None,
                         "netclass_assignments": None,
                         "netclass_patterns":
                             [{"netclass": k, "pattern": q}
                              for k, pats in CLASSES.items() for q in pats]},
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"annotate_start_num": 0, "legacy_lib_dir": "", "legacy_lib_list": [],
                      "meta": {"version": 1},
                      "page_layout_descr_file": "", "plot_directory": "",
                      "spice_current_sheet_as_root": False, "spice_external_command": "",
                      "spice_model_current_sheet_as_root": True, "spice_save_all_currents": False,
                      "spice_save_all_dissipations": False, "spice_save_all_voltages": False,
                      "subpart_first_id": 65, "subpart_id_separator": 0},
        "sheets": [[uid(NAME, "rootsheet"), "Root"]]
                  + [[uid(NAME, "sheet", s), s] for s, _ in CIR.SHEETS],
        "text_variables": {},
    }

# The custom rules. Raspberry Pi's own copper round the RP2350 keeps
# 0.127 mm in one place; the rule says so where it applies.
RULES = """(version 1)

(rule "RP2350 reference copper keeps its own clearance"
  (condition "A.intersectsArea('RP2350 reference') && B.intersectsArea('RP2350 reference')")
  (constraint clearance (min 0.12mm)))
"""

SYM_TABLE = '''(sym_lib_table
  (version 7)
  (lib (name "comms")(type "KiCad")(uri "${KIPRJMOD}/../parts/comms.kicad_sym")(options "")(descr "comms: the project's own symbols"))
)
'''
FP_TABLE = '''(fp_lib_table
  (version 7)
  (lib (name "comms")(type "KiCad")(uri "${KIPRJMOD}/../parts/comms.pretty")(options "")(descr "comms: the project's own footprints"))
)
'''

# ------------------------------------------------------------ primitives ---
LAYER = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu,
         "B.Cu": pcbnew.B_Cu, "Edge.Cuts": pcbnew.Edge_Cuts, "F.SilkS": pcbnew.F_SilkS,
         "B.SilkS": pcbnew.B_SilkS, "Dwgs.User": pcbnew.Dwgs_User,
         "Cmts.User": pcbnew.Cmts_User, "F.Fab": pcbnew.F_Fab, "F.Mask": pcbnew.F_Mask}


class Build:
    def __init__(self, board):
        self.b = board
        self.nets = {}
        self.fps = {}

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    # ---- parts
    def footprint(self, comp, x, y, rot):
        lib, name = comp.fp.split(":")
        path = PROJ_FP if lib == "comms" else KFP / f"{lib}.pretty"
        fp = pcbnew.FootprintLoad(str(path), name)
        if fp is None:
            raise KeyError(comp.fp)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(comp.ref)
        fp.SetValue(comp.value)
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = comp.nets.get(pad.GetNumber())
            if n:
                pad.SetNet(self.net(n))
        if comp.dnp:
            fp.SetDNP(True)
        if comp.note:
            fp.SetField("comms_role", comp.note)
            fp.GetFieldByName("comms_role").SetVisible(False)
        if comp.ref.startswith("H"):
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        # The board is too dense for designators in silk: they go to the fab
        # layer, and the silk carries only what a user of the board reads.
        r = fp.Reference()
        r.SetLayer(pcbnew.F_Fab)
        r.SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5))); r.SetTextThickness(mm(0.08))
        r.SetPosition(V(x, y))
        fp.Value().SetVisible(False)
        self.b.Add(fp)
        self.fps[comp.ref] = fp
        return fp

    def pad(self, ref, num):
        """(x, y) of a pad, board coordinates."""
        for p in self.fps[ref].Pads():
            if p.GetNumber() == str(num):
                c = p.GetPosition()
                return (pcbnew.ToMM(c.x) - OX, pcbnew.ToMM(c.y) - OY)
        raise KeyError((ref, num))

    # ---- copper
    def track(self, net, layer, pts, w, lock=True):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
                continue
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(V(x1, y1)); t.SetEnd(V(x2, y2))
            t.SetWidth(mm(w)); t.SetLayer(LAYER[layer]); t.SetNet(self.net(net))
            t.SetLocked(lock)
            self.b.Add(t)

    def via(self, net, x, y, size=VIA, lock=True):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetWidth(pcbnew.F_Cu, mm(size[0])); v.SetDrill(mm(size[1]))
        v.SetNet(self.net(net)); v.SetLocked(lock)
        self.b.Add(v)
        return v

    def zone(self, net, name, layers, pts, priority=0, solid=False, clearance=0.2,
             min_thickness=0.2, islands="keep"):
        z = pcbnew.ZONE(self.b)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(LAYER[l])
        z.SetLayerSet(ls)
        if net:
            z.SetNet(self.net(net))
        z.SetZoneName(name)
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_thickness))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid
                           else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.2)); z.SetThermalReliefSpokeWidth(mm(0.3))
        z.SetIslandRemovalMode({"keep": pcbnew.ISLAND_REMOVAL_MODE_NEVER,
                                "drop": pcbnew.ISLAND_REMOVAL_MODE_ALWAYS}[islands])
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(mm(OX + x), mm(OY + y))
        z.SetBorderDisplayStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_DIAGONAL_EDGE, mm(0.5), True)
        self.b.Add(z)
        return z

    def keepout(self, name, layers, pts, pour=True, tracks=False, vias=False):
        """A rule area. By default it keeps poured copper out and lets
        tracks and vias through."""
        z = self.zone(None, name, layers, pts)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowCopperPour(pour)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        return z

    # ---- drawing
    def line(self, layer, x1, y1, x2, y2, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2))
        s.SetLayer(LAYER[layer]); s.SetWidth(mm(w))
        self.b.Add(s)

    def arc(self, layer, cx, cy, r, a0, a1, w=0.1):
        """a0 to a1 in degrees, KiCad's sense (y down), a1 - a0 = 90."""
        s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_ARC)
        p = lambda a: V(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        s.SetArcGeometry(p(a0), p((a0 + a1) / 2), p(a1))
        s.SetLayer(LAYER[layer]); s.SetWidth(mm(w))
        self.b.Add(s)

    def circle(self, layer, cx, cy, r, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(V(cx, cy)); s.SetEnd(V(cx + r, cy))
        s.SetLayer(LAYER[layer]); s.SetWidth(mm(w))
        self.b.Add(s)

    def text(self, layer, s, x, y, size=0.8, rot=0, just=None, thick=None, mirror=False):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s); t.SetPosition(V(x, y)); t.SetLayer(LAYER[layer])
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(thick or max(0.1, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        if just == "left":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        elif just == "right":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
        if mirror:
            t.SetMirrored(True)
        self.b.Add(t)
        return t


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# -------------------------------------------------------------- outline ----
def outline(B):
    w, h, r = PL.W / 2, PL.H, PL.CORNER_R
    B.line("Edge.Cuts", -w + r, 0, w - r, 0)
    B.line("Edge.Cuts", w, r, w, h - r)
    B.line("Edge.Cuts", w - r, h, -w + r, h)
    B.line("Edge.Cuts", -w, h - r, -w, r)
    B.arc("Edge.Cuts", w - r, r, r, 270, 360)
    B.arc("Edge.Cuts", w - r, h - r, r, 0, 90)
    B.arc("Edge.Cuts", -w + r, h - r, r, 90, 180)
    B.arc("Edge.Cuts", -w + r, r, r, 180, 270)


# ----------------------------------------------------- the ST60's ground ----
def antenna_ground(B):
    """The copper ST puts round the ST60A3H1 on the X-NUCLEO-60K1A1.

    Measured off that board's top-copper Gerber (B2379A.GTL): a ground island
    5.0 x 6.0 mm centred on the package, a ring 0.5 mm wide with no copper
    round it, the ring's outer edge on the board edge at the patch end, and
    ground vias fencing both sides of the ring. The inner layers are solid
    under all of it. The data sheet's pattern and link budget are measured on
    that board ("the antenna radiated performance can vary for different PCB
    implementations", DS14598 sec. 6), so it is copied rather than improved.
    """
    cx, cy = PL.ST60
    hx, hy = PL.ISLAND
    m = PL.MOAT
    B.zone("GND", "antenna island", ["F.Cu"],
           rect(cx - hx, cy - hy, cx + hx, cy + hy), priority=20, solid=True,
           clearance=0.15, min_thickness=0.15, islands="drop")
    # the moat: three sides (the fourth is the board edge's own clearance)
    for k, r in enumerate((rect(cx - hx - m, cy - hy - m, cx - hx, cy + hy + m),
                           rect(cx + hx, cy - hy - m, cx + hx + m, cy + hy + m),
                           rect(cx - hx - m, cy + hy, cx + hx + m, cy + hy + m),
                           rect(cx - hx - m, cy - hy - m, cx + hx + m, cy - hy))):
        B.keepout(f"antenna moat {k + 1}", ["F.Cu"], r)
    # the island's own vias to In1: down its far side and along its ends,
    # wherever one is legal (the pair on the back passes under one corner)
    M = CU.Model(B.b, OX, OY)
    spots = [(cx - 2.0, cy - 2.5 + k) for k in range(6)] \
          + [(cx + x, cy + s * 2.5) for s in (-1, 1) for x in (-1.0, 0.0, 1.0, 2.0)]
    for x, y in spots:
        if M.via_ok("GND", x, y, ring_ok=True):
            B.via("GND", x, y)
            M.add_via("GND", x, y, *VIA)
    # nothing but the ST60 stands inside the ring, and nothing tall near it
    B.circle("Dwgs.User", PL.PATCH[0], PL.PATCH[1], 1.0, 0.08)
    B.line("Dwgs.User", PL.PATCH[0] - 1.6, PL.PATCH[1], PL.PATCH[0] + 1.6, PL.PATCH[1], 0.08)
    B.line("Dwgs.User", PL.PATCH[0], PL.PATCH[1] - 1.6, PL.PATCH[0], PL.PATCH[1] + 1.6, 0.08)


def st60_copper(B):
    """What cannot be left to a router inside a 0.4 mm ball field.

    The ST60's inner balls face a gap in the middle of the package (rows D
    to K exist only in column 1), and everything here happens in that gap:

      - eUSB2: TX_IP is tied to RX_OP and TX_IN to RX_ON (DS fig. 4, note 1).
        C4/L4 and C5/L5 are in line, so each tie is one straight track across
        the gap, with a via in it to take the pair out on the back.
      - VDD_1V8 (C3) and VDD_IO (L3): a via each into the ST_VDD plane on In2.

    The pair then runs on B.Cu, under the island and out to the repeater.
    """
    P = lambda n: B.pad("U4", n)
    w = 0.15
    # N: C5 - L5, straight, the via on the line
    (xn, y5c), (_, y5l) = P("C5"), P("L5")
    yv = PL.ST60[1]
    B.track("EUSB_N", "F.Cu", [(xn, y5l), (xn, y5c)], w)
    B.via("EUSB_N", xn, yv)
    # P: C4 - L4, stepping 0.315 mm aside round the N via
    (xp, y4c), (_, y4l) = P("C4"), P("L4")
    xv = xp + 0.315
    lo, hi = min(y4c, y4l), max(y4c, y4l)
    B.track("EUSB_P", "F.Cu", [(xp, lo), (xp, yv - 0.55), (xv, yv - 0.235), (xv, yv + 0.235),
                               (xp, yv + 0.55), (xp, hi)], w)
    B.via("EUSB_P", xv, yv)
    # supply balls: up into the gap, 45 degrees to a via by column 1
    for ball in ("C3", "L3"):
        x, y = P(ball)
        s = 1 if y < yv else -1                 # toward the middle of the package
        vx, vy = x + 0.465, y + s * 0.58
        B.track("ST_VDD", "F.Cu", [(x, y), (x, y + s * 0.115), (vx, vy)], w)
        B.via("ST_VDD", vx, vy)

    # the pair on the back: down from the vias, left under the island, down
    # the left of the moat to the repeater's eDP/eDN (on U5's top edge)
    gap, tw = 0.15, 0.2
    pitch = gap + tw
    ex_n, ey = B.pad("U5", "3")                 # eDN
    ex_p, _ = B.pad("U5", "2")                  # eDP
    y_run = PL.ST60[1] + PL.ISLAND[1] - 0.35    # the westward run, under the island's edge
    vn, vp = (ex_n - 0.3, ey - 1.075), (ex_p + 0.1, ey - 1.075)   # where it comes back up
    # N is the inside track of both turns ...
    B.track("EUSB_N", "B.Cu", [(xn, yv), (xn, y_run - 0.75), (xn - 0.75, y_run),
                               (vn[0] + (vn[1] - 0.9 - y_run), y_run),
                               (vn[0], vn[1] - 0.9), vn], tw)
    # ... and P runs one pitch outside it, leaving a little early for its via
    xp1 = xn + pitch
    a = (xp1, y_run - 0.75 + pitch * (2 ** 0.5 - 1))          # end of its southward leg
    b = (a[0] - (y_run + pitch - a[1]), y_run + pitch)        # start of its westward leg
    c_x = vp[0] + ((vp[1] - 0.9) - (y_run + pitch))           # where it turns south-west
    B.track("EUSB_P", "B.Cu", [(xv, yv), (xv, yv + 0.8), (xp1, yv + 0.8 + (xv - xp1)), a, b,
                               (c_x, y_run + pitch), (vp[0], vp[1] - 0.9), vp], tw)
    B.via("EUSB_N", *vn)
    B.via("EUSB_P", *vp)
    B.track("EUSB_N", "F.Cu", [vn, (ex_n, vn[1] + 0.3), (ex_n, ey)], w)
    B.track("EUSB_P", "F.Cu", [vp, (ex_p, vp[1] + 0.1), (ex_p, ey)], w)


# ------------------------------------------------------------- USB pairs ----
TW, GAP = 0.2, 0.16            # the USB class: about 90 ohm differential on this stack (0.01 over the clearance, for rounding)
RPT_X = -9.3                   # where the repeater's USB pair comes down to it, on the back

def usb_copper(B):
    """The one path on the board that carries 480 Mbit/s USB, by hand.

    Connector -> ESD -> the connector-side switch (U9) -> the repeater (U5).
    Everything else on the USB nets is full speed at most -- the RP2350's own
    port, through U10 -- and is laid here too (the last block), because of
    the order its pins come in.

    At the connector the four data pads are interleaved (B7 D-, A6 D+, A7 D-,
    B6 D+). The two D- pads are joined under the connector's shell, on the
    side away from the board; D+ leaves on the board side and picks up its
    second pad there. That is planar, so the pair needs no via before the
    switch. Through the USBLC6 each line enters one pin and leaves by the
    other under the package.

    From U9 the pair drops to the back and runs up the left side of the
    board between the header and the RP2350's ground vias, over the solid
    +3V3 plane on In2, to come up between the repeater's two 3V3 capacitors.
    """
    P = B.pad
    w = TW
    # -- connector to ESD
    b7, a6, a7, b6 = P("J1", "B7"), P("J1", "A6"), P("J1", "A7"), P("J1", "B6")
    y_pad = a6[1]
    top, bot = y_pad - 0.725, y_pad + 0.725        # the pads' ends (1.45 long)
    u4, u3, u6, u1 = P("U8", "4"), P("U8", "3"), P("U8", "6"), P("U8", "1")
    B.track("USB_CONN_DM", "F.Cu", [a7, (a7[0], bot + 0.45), (b7[0], bot + 0.45), b7], w)
    B.track("USB_CONN_DM", "F.Cu", [b7, (b7[0], top - 0.75), (u4[0], top - 0.95), u4, u3], w)
    y_join = top - 0.5
    B.track("USB_CONN_DP", "F.Cu", [a6, (a6[0], y_join), (b6[0], y_join)], w)
    B.track("USB_CONN_DP", "F.Cu", [b6, (b6[0], y_join), (u6[0], y_join - 0.2), u6, u1], w)
    # -- ESD to the switch's D-/D+ (its bottom edge)
    d_m, d_p = P("U9", "7"), P("U9", "8")
    for net, a, d in (("USB_CONN_DM", u3, d_m), ("USB_CONN_DP", u1, d_p)):
        dx = abs(a[0] - d[0])
        B.track(net, "F.Cu", [a, (a[0], d[1] + 0.3 + dx), (d[0], d[1] + 0.3), d], w)

    # The pair shuts the ESD part's VBUS pin (5) in on three sides and its
    # own ground pin shuts the fourth: a via on the end of that pad is the
    # only way in, and VBUS reaches it on the back.
    v5 = P("U8", "5")
    B.via("VBUS", v5[0], v5[1] - 0.6)

    # -- the switch's 2D-/2D+ (top edge) to the repeater's DN/DP (bottom edge)
    s_m, s_p = P("U9", "4"), P("U9", "3")
    r_m, r_p = P("U5", "8"), P("U5", "9")
    pitch = TW + GAP
    v_m, v_p = (s_m[0] - 0.25, s_m[1] - 0.975), (s_p[0] + 0.15, s_p[1] - 0.975)
    B.track("RPT_DM", "F.Cu", [s_m, (s_m[0], s_m[1] - 0.475), (v_m[0], v_m[1] + 0.3), v_m], w)
    B.track("RPT_DP", "F.Cu", [s_p, (s_p[0], s_p[1] - 0.475), (v_p[0], v_p[1] + 0.3), v_p], w)
    B.via("RPT_DM", *v_m)
    B.via("RPT_DP", *v_p)
    e_m, e_p = (r_m[0] - 0.48, r_m[1] + 1.475), (r_p[0] - 0.12, r_p[1] + 1.475)   # the vias by U5
    # On the back the pair goes round the OUTSIDE of the left-hand header:
    # west from U9, down past the header's last pin, up the board's edge,
    # in above its first pin, and down to come at U5 from the left. Inside
    # the header it would wall the header off from the back layer, and the
    # RP2350's left side has nowhere else to send what the front cannot take.
    # The centre line, with 45-degree corners; D+ runs on its right, D- on
    # its left, which is the order both ends want.
    hx, hy0, _ = PL.PLACE["J2"]
    hy1 = hy0 + 15 * 2.54
    c = 0.35
    x0 = (v_m[0] + v_p[0]) / 2
    ya = v_p[1] - 0.65                                      # westward, above the last pin
    xb = RPT_X + 0.55                                       # down, inside the header
    yc = hy1 + 1.5                                          # westward, below the last pin
    xd = hx - 1.72                                          # up the edge
    ye = hy0 - 1.45                                         # eastward, above the first pin
    xf = RPT_X                                              # down to U5
    yg = (e_m[1] + 0.95) + pitch / 2                        # eastward to the vias
    xe = (e_m[0] + e_p[0]) / 2
    centre = [(x0, v_p[1] - 0.275), (x0, ya + c), (x0 - c, ya), (xb + c, ya), (xb, ya + c),
              (xb, yc - c), (xb - c, yc), (xd + c, yc), (xd, yc - c), (xd, ye + c),
              (xd + c, ye), (xf - c, ye), (xf, ye + c), (xf, yg - c), (xf + c, yg), (xe - 1.0, yg)]
    line = CU.LineString(centre)
    # (shapely's "left" is for y up; on a board, y down, it is the right)
    for net, side, via0, via1 in (("RPT_DP", 1, v_p, e_p), ("RPT_DM", -1, v_m, e_m)):
        lane = list(line.offset_curve(side * pitch / 2, join_style=2, mitre_limit=5).coords)
        if not _near(lane[0], centre[0]):
            lane = lane[::-1]
        # into the lanes from U9's vias, out of them to U5's
        y_lane = lane[-1][1]
        tail = [(via1[0] - (y_lane - via1[1] - 0.6), y_lane), (via1[0], via1[1] + 0.6), via1]
        B.track(net, "B.Cu", [via0] + lane[:-1] + tail, w)
    B.via("RPT_DM", *e_m)
    B.via("RPT_DP", *e_p)
    B.track("RPT_DM", "F.Cu", [e_m, (r_m[0], e_m[1] - 0.48), r_m], w)
    B.track("RPT_DP", "F.Cu", [e_p, (r_p[0], e_p[1] - 0.12), r_p], w)


    # -- between the two switches, and from U10 up to the RP2350's series
    # resistors: full speed only, but four lines that arrive at U9 in exactly
    # the reverse of the order they leave U10, with the pair's two vias in the
    # middle. A router ties itself in a knot here; the knot is undone once:
    #
    #   X- (1D-)   straight down the front
    #   X+ (1D+)   under it on the back: a via by U10, east, down, a via by U9
    #   the pair's taps (2D+/2D-): a via each below U10, down the back to the
    #   pair's own vias -- D+ from the north-east, D- round underneath
    #   USB_DM     up the front to R8;  USB_DP under it on the back to R7
    n = 0.15                                                # full speed: plain tracks
    t = {k: P("U10", k) for k in "123478"}
    u92, u91 = P("U9", "2"), P("U9", "1")
    yb = t["1"][1] + 0.3                                    # U10's lower pads' ends
    # X-
    B.track("USB_X_DM", "F.Cu", [t["2"], (t["2"][0], yb + 0.275), (t["2"][0] - 0.15, yb + 0.425),
                                 (t["2"][0] - 0.15, u92[1] - 2.025), (u92[0] + 0.23, u92[1] - 1.745),
                                 (u92[0] + 0.23, u92[1] - 0.805), (u92[0], u92[1] - 0.575), u92], n)
    # X+
    xa, xb = (t["1"][0] - 0.2, yb + 0.925), (u91[0] + 0.5, u91[1] - 0.875)
    B.track("USB_X_DP", "F.Cu", [t["1"], (t["1"][0], yb + 0.425), (xa[0], yb + 0.625), xa], n)
    B.via("USB_X_DP", *xa)
    B.track("USB_X_DP", "B.Cu", [xa, (xa[0] + 0.25, xa[1] - 0.25), (xb[0] - 0.35, xa[1] - 0.25),
                                 (xb[0], xa[1] + 0.1), xb], n)
    B.via("USB_X_DP", *xb)
    B.track("USB_X_DP", "F.Cu", [xb, (u91[0], xb[1] + 0.5), u91], n)
    # the pair's taps
    tp, tm = (t["3"][0] - 0.1, yb + 1.325), (t["4"][0] + 0.4, yb + 0.775)
    B.track("RPT_DP", "F.Cu", [t["3"], (t["3"][0], tp[1] - 0.3), (tp[0], tp[1] - 0.2), tp], n)
    B.track("RPT_DM", "F.Cu", [t["4"], (t["4"][0], yb + 0.225), (tm[0], yb + 0.625), tm], n)
    B.via("RPT_DP", *tp)
    B.via("RPT_DM", *tm)
    d = tp[0] - v_p[0]
    B.track("RPT_DP", "B.Cu", [tp, (tp[0], v_p[1] - d), v_p], n)
    ys = v_m[1] + 0.65                                      # under the pair's vias
    B.track("RPT_DM", "B.Cu", [tm, (tm[0], ys - 0.3), (tm[0] - 0.3, ys), (v_m[0] + 0.45, ys),
                               (v_m[0], ys - 0.45), v_m], n)
    # up to R7/R8
    r7, r8 = P("R7", "1"), P("R8", "1")
    yt = t["7"][1] - 0.3                                    # U10's upper pads' ends
    B.track("USB_DM", "F.Cu", [t["7"], (t["7"][0], yt - 0.825), (r8[0], yt - 0.825 - (t["7"][0] - r8[0])), r8], n)
    da, db = (t["8"][0], yt - 0.275), (r7[0], r7[1] + 1.0)
    B.track("USB_DP", "F.Cu", [t["8"], da], n)
    B.via("USB_DP", *da)
    B.track("USB_DP", "B.Cu", [da, (da[0], db[1] + 0.35 + (db[0] - da[0])), (db[0], db[1] + 0.35), db], n)
    B.via("USB_DP", *db)
    B.track("USB_DP", "F.Cu", [db, r7], n)


def select_copper(B):
    """The two USB path selects, from GPIO8 and GPIO9 at the RP2350's upper
    right to the switches at the bottom of the board. Between lie the
    right-hand header's fan-out and the QSPI bus, all on the front; so both
    go on the back: a via each in the open corner above C15, down the board
    between the chip's ground vias and the header, and across."""
    P = B.pad
    w = 0.15
    p_m, p_c = P("U1", "12"), P("U1", "13")                 # GPIO8, GPIO9
    r13, s_m = P("R13", "1"), P("U10", "9")
    r12, s_c = P("R12", "1"), P("U9", "9")
    xm, xc = 8.4, 8.8                                       # the two lanes down the back
    va_m, va_c = (p_m[0] + 2.8625, p_m[1] - 0.95), (p_c[0] + 2.8625, p_c[1] - 1.3)
    B.track("USB_SEL_MCU", "F.Cu", [p_m, (p_m[0] + 1.4625, p_m[1]), (va_m[0] - 0.45, va_m[1]), va_m], w)
    B.track("USB_SEL_CONN", "F.Cu", [p_c, (p_c[0] + 1.2625, p_c[1]),
                                     (va_c[0] - 0.3, va_c[1]), va_c], w)
    B.via("USB_SEL_MCU", *va_m)
    B.via("USB_SEL_CONN", *va_c)
    # USB_SEL_MCU: down the inner lane, west under U10 to a via by R13
    vb_m = (r13[0] + 0.7, r13[1] + 0.12)
    y = s_m[1] + 0.125
    B.track("USB_SEL_MCU", "B.Cu", [va_m, (xm - 0.8, va_m[1]), (xm, va_m[1] + 0.8), (xm, y - 0.4),
                                    (xm - 0.4, y), (vb_m[0] + 0.55, y), (vb_m[0], y - 0.55), vb_m], w)
    B.via("USB_SEL_MCU", *vb_m)
    B.track("USB_SEL_MCU", "F.Cu", [vb_m, r13], w)
    B.track("USB_SEL_MCU", "F.Cu", [vb_m, (vb_m[0] + 0.25, vb_m[1] + 0.25),
                                    (s_m[0] - 0.35, s_m[1] - 0.125), (s_m[0], s_m[1] - 0.125), s_m], w)
    # USB_SEL_CONN: down the outer lane to a via by R12, on to U9's S
    vb_c = (r12[0] + 0.9, r12[1] + 0.37)
    B.track("USB_SEL_CONN", "B.Cu", [va_c, (xc - 0.8, va_c[1]), (xc, va_c[1] + 0.8),
                                     (xc, vb_c[1] - (xc - vb_c[0])), vb_c], w)
    B.via("USB_SEL_CONN", *vb_c)
    B.track("USB_SEL_CONN", "F.Cu", [vb_c, (r12[0] + 0.45, vb_c[1]), r12], w)
    y = r12[1] + 0.62
    B.track("USB_SEL_CONN", "F.Cu", [r12, (r12[0], y - 0.15), (r12[0] - 0.15, y), (s_c[0] + 0.85, y),
                                     (s_c[0] + 0.425, s_c[1]), s_c], w)


def _near(a, b, tol=0.6):
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


# ------------------------------------------------- the RP2350's surroundings
REF_NETS = {"+1V1": "+1V1", "+3V3": "+3V3", "GND": "GND",
            "/VREG_AVDD": "VREG_AVDD", "/VREG_LX": "VREG_LX", "/XOUT": "XOUT",
            "Net-(U1-USB_DP)": "USB_DP_C", "Net-(U1-USB_DM)": "USB_DM_C"}
REF_BOX = (-8.6, -9.2, 8.6, 9.5)      # round U1, the reference's frame

def reference_copper(B):
    """Raspberry Pi's copper round the RP2350A, out of their board file.

    Everything on the nets in REF_NETS that lies wholly inside REF_BOX, the
    reference's frame centred on its U1: the 1V1 ring under the chip and the
    3V3 ring round it, the four pours of the core regulator, the tracks from
    each supply pin to its capacitor, the capacitors' ground vias, the 1V1
    runs on the back and the USB pair to its series resistors. Turned with
    the chip (placement.U1_ROT) and locked.
    """
    ref = pcbnew.LoadBoard(str(RPI_REF))
    u1 = next(f for f in ref.GetFootprints() if f.GetReference() == "U1")
    c = u1.GetPosition()
    def rel(p):
        return (pcbnew.ToMM(p.x - c.x), pcbnew.ToMM(p.y - c.y))
    def inside(q):
        return REF_BOX[0] <= q[0] <= REF_BOX[2] and REF_BOX[1] <= q[1] <= REF_BOX[3]
    def here(q):
        x, y, _ = PL.in_chip(q[0], q[1])
        return (x, y)
    n = {"track": 0, "via": 0, "zone": 0}
    for t in ref.GetTracks():
        net = REF_NETS.get(t.GetNetname())
        if not net:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            q = rel(t.GetPosition())
            if inside(q):
                B.via(net, *here(q), size=(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)),
                                           pcbnew.ToMM(t.GetDrill())))
                n["via"] += 1
        else:
            a, b = rel(t.GetStart()), rel(t.GetEnd())
            if inside(a) and inside(b):
                B.track(net, ref.GetLayerName(t.GetLayer()), [here(a), here(b)],
                        pcbnew.ToMM(t.GetWidth()))
                n["track"] += 1
    for z in ref.Zones():
        net = REF_NETS.get(z.GetNetname())
        o = z.Outline()
        pts = [rel(o.CVertex(i)) for i in range(o.TotalVertices())]
        if not net or not all(inside(q) for q in pts) or ref.GetLayerName(z.GetLayer()) != "F.Cu":
            continue
        B.zone(net, f"RP2350 reference: {net} #{n['zone'] + 1}", ["F.Cu"],
               [here(q) for q in pts], priority=10 + z.GetAssignedPriority(), solid=True,
               clearance=0.15, min_thickness=0.15, islands="drop")
        n["zone"] += 1
    # The reference's 3V3 is a pour on the front, and a few of its tracks do
    # nothing but reach into that pour. Here 3V3 is a plane, and those ends
    # would hang in the air: take away every track with an end on nothing.
    n["pruned"] = 0
    while True:
        M = CU.Model(B.b, OX, OY)
        tracks = [t for t in B.b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T
                  and B.b.GetLayerName(t.GetLayer()) == "F.Cu"]
        ends = {}
        for t in tracks:
            for end in (t.GetStart(), t.GetEnd()):
                ends[(t.GetNetname(), end.x, end.y)] = ends.get((t.GetNetname(), end.x, end.y), 0) + 1
        def attached(t, end):
            if ends[(t.GetNetname(), end.x, end.y)] > 1:        # another track ends here
                return True
            pt = CU.Point(*M.xy(end))
            return any(n_ == t.GetNetname() and k_ != "track" and s_.buffer(0.002).contains(pt)
                       for s_, n_, k_ in M._near("F.Cu", pt, 0.01))
        dead = [t for t in tracks if not (attached(t, t.GetStart()) and attached(t, t.GetEnd()))]
        if not dead:
            break
        for t in dead:
            B.b.Remove(t)
        n["pruned"] += len(dead)
    # ... and the two supply pins that pour alone reached, IOVDD at pins 1 and
    # 45: 45 to its neighbour 44 (which has a track to C17), 1 to C13 the way
    # 44 goes to C17, mirrored.
    for pts in ([(3.4375, -2.8), (3.4375, -2.4)],
                [(-3.4375, -2.8), (-4.6, -2.8), (-5.2, -3.4), (-6.005, -3.4)]):
        B.track("+3V3", "F.Cu", [here(q) for q in pts], 0.2)
        n["track"] += len(pts) - 1
    # the reference keeps 0.127 mm between a 1V1 track and C6's 3V3 pad; the
    # rule file allows its copper its own clearance inside this area
    x0, y0, _ = PL.in_chip(REF_BOX[0], REF_BOX[1])
    x1, y1, _ = PL.in_chip(REF_BOX[2], REF_BOX[3])
    z = B.keepout("RP2350 reference", ["F.Cu", "B.Cu"],
                  rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), pour=False)
    return n


# ---------------------------------------------------------------- planes ----
def planes(B):
    w, h = PL.W / 2, PL.H
    full = rect(-w, 0, w, h)
    B.zone("GND", "ground plane In1", ["In1.Cu"], full, clearance=0.2)
    B.zone("GND", "ground pour F.Cu", ["F.Cu"], full, clearance=0.2, islands="drop")
    B.zone("GND", "ground pour B.Cu", ["B.Cu"], full, clearance=0.2, islands="drop")
    # In2: +3V3 everywhere but under the antenna island, where it is the
    # ST60's own supply (ST_VDD, +1V8 after the 0 R link), and over the
    # 1.8 V parts of the link section (copper.V18_POLY)
    B.zone("+3V3", "+3V3 plane In2", ["In2.Cu"], full, clearance=0.2, islands="drop")
    B.zone("ST_VDD", "ST_VDD plane In2", ["In2.Cu"], rect(*CU.ST_VDD_RECT), priority=5,
           clearance=0.2, islands="drop")
    B.zone("+1V8", "+1V8 plane In2", ["In2.Cu"], CU.V18_POLY, priority=5, clearance=0.2,
           islands="drop")


# ------------------------------------------------------------- silkscreen ---
SILK_NAME = {"VBUS": "5V", "+3V3": "3V3", "+1V8": "1V8", "CFG_SDA": "SDA", "CFG_SCL": "SCL",
             "RF_EN_GP": "RFEN", "ST_INT": "INT", "ST_LINK": "LINK"}

def silk(B):
    comps = {c.ref: c for c in CIR.board()}
    # The connectors' own silk goes: the headers' boxes would run through
    # the pin names, the USB-C's corner marks are off the board's edge.
    for ref in ("J1", "J2", "J3"):
        for g in list(B.fps[ref].GraphicalItems()):
            if g.GetLayer() == pcbnew.F_SilkS:
                B.fps[ref].Remove(g)
    # header pin names: on the front outboard of each header, turned to fit
    # between the pads and the board edge; on the back, where nothing else
    # is, inboard and level
    for ref, side in (("J2", 1), ("J3", -1)):
        x0, y0, _ = PL.PLACE[ref]
        for i in range(16):
            net = comps[ref].nets[str(i + 1)]
            label = SILK_NAME.get(net, net).replace("TUN_", "")
            front = label[2:] if label.startswith("GP") else label
            y = y0 + i * 2.54
            B.text("F.SilkS", front, x0 - side * 1.75, y, 0.6, rot=90)
            B.text("B.SilkS", label, x0 + side * 1.5, y, 0.8,
                   just="right" if side > 0 else "left", mirror=True)
        # pin 1: a bar across the end of the row
        B.line("F.SilkS", x0 - 0.9, y0 - 1.2, x0 + 0.9, y0 - 1.2, 0.15)
    B.text("B.SilkS", "comms rev A  RP2350A + ST60A3H1", 0, 30.0, 1.0, rot=90, mirror=True)
    B.text("B.SilkS", "60 GHz ANTENNA THIS END - KEEP CLEAR", 0, 7.4, 0.7, mirror=True)
    # antenna axis: a tick each side of the moat on the front, on the patch's
    # line; on the back a target over the patch itself
    px, py = PL.PATCH
    for s in (-1, 1):
        B.line("F.SilkS", s * 3.25, py, s * 3.75, py, 0.15)
    B.circle("B.SilkS", px, py, 1.2, 0.15)
    B.line("B.SilkS", px - 1.9, py, px + 1.9, py, 0.15)
    B.line("B.SilkS", px, max(0.6, py - 1.9), px, py + 1.9, 0.15)
    for label, x, y, rot in (("BOOT", 9.9, PL.PLACE["SW1"][1], 90), ("RUN", 9.9, PL.PLACE["SW2"][1], 90),
                             ("PWR", -10.8, PL.PLACE["D1"][1], 0), ("LED", -10.8, PL.PLACE["D3"][1], 0),
                             ("LINK", -7.2, 18.3, 0), ("SWD", 6.4, 54.2, 90)):
        B.text("F.SilkS", label, x, y, 0.7, rot=rot)


# ------------------------------------------------------------------ build ---
def build(path, taps=True):
    path.write_text(skeleton())
    board = pcbnew.LoadBoard(str(path))
    B = Build(board)
    comps = CIR.board()
    for net in sorted({n for c in comps for n in c.nets.values() if n}):
        B.net(net)
    outline(B)
    for c in comps:
        x, y, rot = PL.PLACE[c.ref]
        B.footprint(c, x, y, rot)
    planes(B)
    n_ref = reference_copper(B)
    st60_copper(B)
    usb_copper(B)
    select_copper(B)
    antenna_ground(B)
    silk(B)
    n_tap = CU.plane_taps(B, OX, OY) if taps else 0
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    return n_ref, n_tap


def write(path, text, force):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        print(f"keep   {path.relative_to(ROOT)} (exists)")
        return False
    path.write_text(text)
    print(f"wrote  {path.relative_to(ROOT)}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="overwrite the board and the sheets")
    ap.add_argument("--no-pcb", action="store_true", help="only the project file and the sheets")
    ap.add_argument("--no-sch", action="store_true", help="skip the schematic")
    ap.add_argument("--no-taps", action="store_true", help="skip the plane taps (for looking at placement)")
    ap.add_argument("--out", help="write the board somewhere else (a scratch copy)")
    a = ap.parse_args()

    bad = CIR.check() + PL.check()
    if bad:
        print("\n".join("  ! " + b for b in bad))
        sys.exit(1)
    HW.mkdir(parents=True, exist_ok=True)
    write(PRO, json.dumps(project(), indent=2) + "\n", True)
    write(HW / f"{NAME}.kicad_dru", RULES, True)
    write(HW / "sym-lib-table", SYM_TABLE, True)
    write(HW / "fp-lib-table", FP_TABLE, True)
    if not a.no_sch:
        import schlayout
        schlayout.emit(HW, a.force)
    if not a.no_pcb:
        target = Path(a.out) if a.out else PCB
        if target.exists() and not a.force:
            print(f"keep   {target} (exists; --force to regenerate, which discards the routing)")
        else:
            n_ref, n_tap = build(target, taps=not a.no_taps)
            print(f"wrote  {target}")
            print(f"       reference copper round U1: {n_ref['track']} tracks, "
                  f"{n_ref['via']} vias, {n_ref['zone']} pours; {n_tap} plane taps")


if __name__ == "__main__":
    main()
