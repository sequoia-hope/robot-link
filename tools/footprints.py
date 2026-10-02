#!/usr/bin/env python3
"""footprints.py -- hardware/parts/comms.pretty, the project's own lands.

    python3 tools/footprints.py

Two are drawn here, from the manufacturers' drawings:

  ST_VFBGA-23_AiP_2.95x4.07mm_P0.4mm    ST60A3H1. Ball positions are DS14598
      rev 4 table 38, which is the BOTTOM view; the top view has column 1 on
      the left and row A at the top, and ST's own board (X-NUCLEO-60K1A1,
      B2379A) names its pads the same way. 0.25 mm pads, as that board has.
      The antenna patch is drawn on the fab layer: centred across the
      package, 1.184 mm toward row N from the centre (fig. 31).
  NXP_XQFN-12_1.75x2.2mm_P0.4mm         PTN3222GM, SOT2074-1, from the PCB
      design guideline sheet of the outline drawing (98ASA01665D).

Three are copied from servodrive's library, where they came from Raspberry
Pi's RP2350A minimal design: the QFN-60 with its thermal vias, the polarised
2016 inductor and the small-pad 0402.
"""
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware/parts/comms.pretty"
SERVODRIVE = Path("/home/sequoia/pcb/servodrive/hardware/parts")
NS = uuid.UUID("5c0e60a3-0000-4000-8000-00000000f00d")
def uid(*p): return str(uuid.uuid5(NS, "/".join(str(x) for x in p)))

# ST60A3H1, DS14598 table 38 (bottom view, y up) -> the land (top view, y
# down): the same numbers, because turning the part over about its long...
# its X axis and KiCad's downward y are the same flip.
ST60_BALLS = {
    "K1": (-1.175, 1.2), "J1": (-1.175, 0.8), "H1": (-1.175, 0.4), "G1": (-1.175, 0.0),
    "F1": (-1.175, -0.4), "E1": (-1.175, -0.8), "D1": (-1.175, -1.2),
    "M2": (-0.975, 1.6), "B2": (-0.975, -1.6),
    "N3": (-0.185, 1.73), "L3": (-0.185, 1.33), "C3": (-0.185, -1.33), "A3": (-0.185, -1.73),
    "N4": (0.215, 1.73), "L4": (0.215, 1.33), "C4": (0.215, -1.33), "A4": (0.215, -1.73),
    "N5": (0.615, 1.73), "L5": (0.615, 1.33), "C5": (0.615, -1.33), "A5": (0.615, -1.73),
    "L6": (1.015, 1.33), "C6": (1.015, -1.33),
}
ST60_BODY = (2.95, 4.07)
ST60_PATCH = (0.0, 2.035 - 0.225 - 0.885 * 2 ** 0.5 / 2)   # centre, toward row N
ST60_PATCH_SIDE = 0.885


def _head(name, descr, tags):
    return (f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "footprints.py")\n'
            f'\t(generator_version "9.0")\n\t(layer "F.Cu")\n'
            f'\t(descr "{descr}")\n\t(tags "{tags}")\n')


def _props(name, ref_y, val_y):
    return (f'\t(property "Reference" "REF**" (at 0 {ref_y} 0) (layer "F.SilkS") (uuid "{uid(name, "ref")}")\n'
            f'\t\t(effects (font (size 0.8 0.8) (thickness 0.12))))\n'
            f'\t(property "Value" "{name}" (at 0 {val_y} 0) (layer "F.Fab") (uuid "{uid(name, "val")}")\n'
            f'\t\t(effects (font (size 0.8 0.8) (thickness 0.12))))\n'
            f'\t(attr smd)\n')


def _line(name, k, x1, y1, x2, y2, layer, w):
    return (f'\t(fp_line (start {x1:.4f} {y1:.4f}) (end {x2:.4f} {y2:.4f})\n'
            f'\t\t(stroke (width {w}) (type solid)) (layer "{layer}") (uuid "{uid(name, layer, k)}"))\n')


def _rect(name, k, x, y, layer, w):
    return (f'\t(fp_rect (start {-x:.4f} {-y:.4f}) (end {x:.4f} {y:.4f})\n'
            f'\t\t(stroke (width {w}) (type solid)) (fill no) (layer "{layer}") (uuid "{uid(name, layer, k)}"))\n')


def st60():
    name = "ST_VFBGA-23_AiP_2.95x4.07mm_P0.4mm"
    hx, hy = ST60_BODY[0] / 2, ST60_BODY[1] / 2
    o = [_head(name, "ST60A3H1, VFBGA-23 antenna in package, 2.95x4.07x0.8 mm, 0.4 mm pitch, "
                     "DS14598 rev 4 table 38; pads as ST's X-NUCLEO-60K1A1",
               "BGA 23 0.4 ST60A3H1 AiP 60GHz"),
         _props(name, -hy - 1.0, hy + 1.0)]
    o.append(_rect(name, "body", hx, hy, "F.Fab", 0.1))
    # A1 corner, top left
    o.append(_line(name, "a1", -hx, -hy + 0.6, -hx + 0.6, -hy, "F.Fab", 0.1))
    # silk: corner ticks only, so nothing prints over the island or the patch
    t, g = 0.5, 0.12
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * (hx + g), sy * (hy + g)
            if (sx, sy) == (-1, -1):
                continue
            o.append(_line(name, f"s{sx}{sy}h", cx, cy, cx - sx * t, cy, "F.SilkS", 0.12))
            o.append(_line(name, f"s{sx}{sy}v", cx, cy, cx, cy - sy * t, "F.SilkS", 0.12))
    # A1 mark: a dot outside the corner
    o.append(f'\t(fp_circle (center {-hx - 0.35:.4f} {-hy - 0.35:.4f}) (end {-hx - 0.25:.4f} {-hy - 0.35:.4f})\n'
             f'\t\t(stroke (width 0.12) (type solid)) (fill yes) (layer "F.SilkS") (uuid "{uid(name, "a1dot")}"))\n')
    o.append(_rect(name, "crt", hx + 0.25, hy + 0.25, "F.CrtYd", 0.05))
    # the patch: a square on its corner
    px, py = ST60_PATCH
    d = ST60_PATCH_SIDE * 2 ** 0.5 / 2
    pts = [(px, py - d), (px + d, py), (px, py + d), (px - d, py)]
    for layer in ("F.Fab", "Dwgs.User"):
        for k, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
            o.append(_line(name, f"patch{k}", a[0], a[1], b[0], b[1], layer, 0.08))
    for k, (dx, dy) in enumerate(((0.3, 0), (0, 0.3))):
        o.append(_line(name, f"cross{k}", px - dx, py - dy, px + dx, py + dy, "Dwgs.User", 0.05))
    for num, (x, y) in sorted(ST60_BALLS.items()):
        o.append(f'\t(pad "{num}" smd circle (at {x:.4f} {y:.4f}) (size 0.25 0.25)\n'
                 f'\t\t(layers "F.Cu" "F.Mask" "F.Paste") (solder_mask_margin 0.0375)\n'
                 f'\t\t(uuid "{uid(name, "pad", num)}"))\n')
    o.append('\t(embedded_fonts no)\n)\n')
    return name, "".join(o)


def ptn3222():
    name = "NXP_XQFN-12_1.75x2.2mm_P0.4mm"
    hx, hy = 1.75 / 2, 2.2 / 2
    o = [_head(name, "PTN3222GM, XQFN12, SOT2074-1, 1.75x2.2x0.5 mm, 0.4 mm pitch, "
                     "NXP 98ASA01665D PCB design guideline",
               "XQFN 12 0.4 PTN3222 SOT2074-1"),
         _props(name, -2.4, 2.4)]
    o.append(_rect(name, "body", hx, hy, "F.Fab", 0.1))
    o.append(_line(name, "p1", -hx, -hy + 0.4, -hx + 0.4, -hy, "F.Fab", 0.1))
    o.append(_rect(name, "crt", 1.6, 1.8, "F.CrtYd", 0.05))
    # silk: the two corners with room, and a dot at pin 1
    for sx, sy in ((1, 1), (-1, 1), (1, -1)):
        cx, cy = sx * (hx + 0.12), sy * (hy + 0.12)
        o.append(_line(name, f"s{sx}{sy}h", cx, cy, cx - sx * 0.3, cy, "F.SilkS", 0.12))
        o.append(_line(name, f"s{sx}{sy}v", cx, cy, cx, cy - sy * 0.15, "F.SilkS", 0.12))
    o.append(f'\t(fp_circle (center -1.55 -1.0) (end -1.45 -1.0)\n'
             f'\t\t(stroke (width 0.12) (type solid)) (fill yes) (layer "F.SilkS") (uuid "{uid(name, "p1dot")}"))\n')
    pads = {}
    for i, y in enumerate((-0.6, -0.2, 0.2, 0.6)):
        pads[str(1 + i)] = (-0.925, y, 0.8, 0.2)          # left, 1..4 downward
        pads[str(10 - i)] = (0.925, y, 0.8, 0.2)          # right, 10..7 downward
    pads["5"], pads["6"] = (-0.2, 1.15, 0.2, 0.8), (0.2, 1.15, 0.2, 0.8)
    pads["12"], pads["11"] = (-0.2, -1.15, 0.2, 0.8), (0.2, -1.15, 0.2, 0.8)
    for num in sorted(pads, key=int):
        x, y, w, h = pads[num]
        o.append(f'\t(pad "{num}" smd roundrect (at {x:.4f} {y:.4f}) (size {w} {h})\n'
                 f'\t\t(layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.5)\n'
                 f'\t\t(uuid "{uid(name, "pad", num)}"))\n')
    o.append('\t(embedded_fonts no)\n)\n')
    return name, "".join(o)


COPIED = ["RP2350-QFN-60-1EP_7x7_P0.4mm_EP3.4x3.4mm_ThermalVias", "L_pol_2016",
          "C_0402_1005Metric_small_pads"]
MODELS = ["HRO_TYPE-C-31-M-12.step", "AOTA-B201610SR47MT.STEP"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in (st60(), ptn3222()):
        (OUT / f"{name}.kicad_mod").write_text(text)
        print(f"drew   {name}")
    for name in COPIED:
        shutil.copyfile(SERVODRIVE / "servodrive.pretty" / f"{name}.kicad_mod",
                        OUT / f"{name}.kicad_mod")
        print(f"copied {name}")
    md = ROOT / "hardware/parts/3dmodels"
    md.mkdir(parents=True, exist_ok=True)
    for m in MODELS:
        shutil.copyfile(SERVODRIVE / "3dmodels" / m, md / m)
        print(f"copied 3dmodels/{m}")


if __name__ == "__main__":
    main()
