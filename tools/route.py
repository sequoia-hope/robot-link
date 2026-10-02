#!/usr/bin/env python3
"""route.py -- hand the comms board's signals to freerouting and bring them back.

    python3 tools/route.py                  # route hardware/comms/comms.kicad_pcb
    python3 tools/route.py --pcb copy.kicad_pcb --passes 30

The board gen_board.py writes is placed and poured, and every net that is
decided rather than routed is already copper: the supplies on their planes
with a via at every pad, the reference design's tracks round the RP2350, the
ST60's ball field, the 480 Mbit/s USB pair. What is left is about seventy
ordinary signals, and those go to freerouting 2.2.4.

freerouting is given a board with nothing on it but the problem:

  - the nets that are already complete are taken out altogether. Their pads
    stay, as copper with no net; their tracks, vias and pours become
    keepouts. (A router shown finished copper as "protected wiring" tries to
    join it up again, and cannot tee into a protected track -- measured on
    servodrive, whose route.py this follows.)
  - a net that is part copper, part open (RPT_DP/DM: the pair is laid, U10's
    tap onto it is not) keeps one via, the one nearest the open pad, as the
    thing to route to; the rest of its copper is keepout like the others.
  - no pours, and no rule areas except the ones that really forbid tracks:
    KiCad's Specctra export writes every rule area as a keepout.
  - In1 and In2 are `power` layers in the board file, which the export
    passes on and the router does not route on.

The session comes back into that same scratch board, and the new tracks and
vias are copied from there onto the real one by net name. KiCad's own
session import would throw away every track the real board already has.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import circuit as CIR

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware" / "comms"
BOARD = HW / "comms.kicad_pcb"
WORK = HW / ".route"
JAR = Path("/home/sequoia/Software/magnet/route/freerouting-2.2.4.jar")
mm = pcbnew.FromMM

FR_CONFIG = """{
  "profile": { "id": "00000000-0000-4000-8000-000000000000", "email": "",
               "allow_telemetry": false, "allow_contact": false },
  "gui": { "enabled": false, "input_directory": "",
           "dialog_confirmation_timeout": 0 },
  "usage_and_diagnostic_data": { "disable_analytics": true },
  "feature_flags": { "multi_threading": true }
}
"""


def drc(path, report):
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
                    "--all-track-errors", "-o", str(report), str(path)],
                   capture_output=True, text=True)
    return json.loads(Path(report).read_text())


def open_nets(report):
    """{net: [(x, y), ...]} -- the nets with something unconnected, and where."""
    out = {}
    for it in report.get("unconnected_items", ()):
        for item in it["items"]:
            m = re.search(r"\[([^\]]*)\]", item["description"])
            if m:
                out.setdefault(m.group(1), []).append((item["pos"]["x"], item["pos"]["y"]))
    return out


def fill(board):
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def save(board, path):
    path = Path(path)
    tmp = path.with_name(path.stem + ".saving" + path.suffix)
    pcbnew.SaveBoard(str(tmp), board)
    os.replace(tmp, path)


def _keepout(board, layers, pts, vias=True):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowCopperPour(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(int(x), int(y))
    board.Add(z)


def _ring(geom):
    return [(x, y) for x, y in list(geom.exterior.coords)[:-1]]


def blockers(pcb, reach=7.0, step=0.05):
    """The nets that fence in what is still open.

    freerouting leaves a connection open when a pin's way out is shut by
    tracks it laid earlier for the pin's neighbours -- a QFN pin between two
    tracks that fan apart only after a capacitor, a ball whose neighbours left
    at 45 degrees across its front. It does not come back for them. For each
    open pad this floods the free copper on the front from the pad and names
    the router's nets standing round the pocket it fills; those are what has
    to come up with it.
    """
    import numpy as np
    from collections import deque
    from shapely import contains_xy
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union
    import copper as CU
    import gen_board as GB
    report = drc(pcb, WORK / "pre.json")
    opens = open_nets(report)
    board = pcbnew.LoadBoard(str(pcb))
    M = CU.Model(board, GB.OX, GB.OY)
    routed = {t.GetNetname() for t in board.GetTracks() if not t.IsLocked()}
    out = set(opens)
    for net, pts in opens.items():
        obs = unary_union([s_.buffer(0.15 + 0.075 + 0.01) for s_, n_, _ in M.shapes["F.Cu"] if n_ != net])
        for px, py in pts:
            x, y = px - GB.OX, py - GB.OY
            xs = np.arange(x - reach, x + reach, step)
            ys = np.arange(y - reach, y + reach, step)
            X, Y = np.meshgrid(xs, ys)
            free = ~contains_xy(obs, X, Y)
            n = len(xs) // 2
            start = (len(ys) // 2, n)
            free[start] = True
            seen = np.zeros_like(free)
            seen[start] = True
            q = deque([start])
            while q:
                i, j = q.popleft()
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a_, b_ = i + di, j + dj
                    if 0 <= a_ < free.shape[0] and 0 <= b_ < free.shape[1] \
                            and free[a_, b_] and not seen[a_, b_]:
                        seen[a_, b_] = True
                        q.append((a_, b_))
            ii, jj = np.where(seen)
            if ii.min() == 0 or jj.min() == 0 or ii.max() == free.shape[0] - 1 \
                    or jj.max() == free.shape[1] - 1:
                continue                   # the flood reached open country: not fenced in
            pocket = MultiPoint([(xs[j], ys[i]) for i, j in zip(ii[::7], jj[::7])]).buffer(0.5)
            for s_, n_, k_ in M.shapes["F.Cu"]:
                if n_ != net and n_ in routed and k_ in ("track", "via") and s_.intersects(pocket):
                    out.add(n_)
    return sorted(out), sorted(opens)


# The way out of the two fine-pitch parts, given to the router as wiring it
# may keep or move (unlocked, so the Specctra export marks it `route` and
# not `protect`). Round the RP2350 the reference design's decoupling
# capacitors leave each group of four GPIO pins a gap exactly four tracks
# wide; the router finds that arrangement some runs and not others, and when
# it does not, a pin is fenced in by its neighbours and stays open. So the
# arrangement is laid for it: (first pin, last pin, the y of the first
# track once through the gap, pitch there, how far out the stub runs).
QFN_GROUPS = [
    # right-hand side of the board (the chip is turned): pins 2-5 between C13 and C8,
    # 7-10 between C8 and C15
    (5, 2, 31.85, 0.3, 8.3), (10, 7, None, 0.4, 8.3),
    # left-hand side: 31-37 above C14, 40-43 between C11 and C17
    (31, 37, 27.5, 0.3, -8.8), (40, 43, 31.45, 0.3, -8.8),
]
BGA_OUT = 3.4                  # x where the ST60's balls' stubs end, past the moat


def escapes(board, opens):
    """[(net, [(x, y), ...])] in board millimetres (KiCad page coordinates)."""
    pads = {(f.GetReference(), p.GetNumber()): p for f in board.GetFootprints() for p in f.Pads()}
    def at(ref, num):
        q = pads[(ref, str(num))].GetPosition()
        return pcbnew.ToMM(q.x), pcbnew.ToMM(q.y)
    import gen_board as GB
    out = []
    for first, last, y0, pitch, x_end in QFN_GROUPS:
        step = 1 if last >= first else -1
        for k, pin in enumerate(range(first, last + step, step)):
            net = pads[("U1", str(pin))].GetNetname()
            x, y = at("U1", pin)
            sx = 1 if x_end > 0 else -1
            xe = GB.OX + x_end
            if y0 is None:
                pts = [(x, y), (xe, y)]
            else:
                yt = GB.OY + y0 + k * pitch
                x1 = x + sx * 0.6
                pts = [(x, y), (x1, y), (x1 + sx * abs(yt - y), yt), (xe, yt)]
            if net in opens:
                out.append((net, pts))
    for f in board.GetFootprints():
        if f.GetReference() != "U4":
            continue
        cx = pcbnew.ToMM(f.GetPosition().x)
        for p in f.Pads():
            net = p.GetNetname()
            x, y = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
            if net in opens and x - cx > 0.9:               # column 1 and B2/M2: the side that faces out
                out.append((net, [(x, y), (GB.OX + BGA_OUT, y)]))
    return out


def strip(src, dst, with_escapes=False):
    """The scratch board: the routing problem and nothing else. Returns
    (nets taken out, nets left with one via to route to)."""
    report = drc(src, WORK / "pre.json")
    opens = open_nets(report)
    board = pcbnew.LoadBoard(str(src))
    with_copper = {t.GetNetname() for t in board.GetTracks()} | \
                  {z.GetNetname() for z in board.Zones() if not z.GetIsRuleArea()}
    with_copper.discard("")
    complete = sorted(n for n in with_copper if n not in opens)
    partial = sorted(n for n in with_copper if n in opens)

    # the one via a partial net keeps: nearest to its open pads
    anchors = {}
    for net in partial:
        pts = opens[net]
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        vias = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == net]
        if not vias:
            raise RuntimeError(f"{net} is part routed and has no via to route to")
        v = min(vias, key=lambda v: math.hypot(pcbnew.ToMM(v.GetPosition().x) - cx,
                                               pcbnew.ToMM(v.GetPosition().y) - cy))
        anchors[net] = (v.GetPosition().x, v.GetPosition().y)     # by place: SWIG wrappers have no identity
    # pads of a partial net that its laid copper already reaches lose the
    # net too: the router is to reach the via, not them
    touched = {}
    for net in partial:
        open_xy = {(round(x, 3), round(y, 3)) for x, y in opens[net]}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == net:
                    p = pad.GetPosition()
                    if (round(pcbnew.ToMM(p.x), 3), round(pcbnew.ToMM(p.y), 3)) not in open_xy:
                        touched.setdefault(net, []).append(pad)

    stubs = escapes(board, set(opens) - set(partial)) if with_escapes else []
    # (the pads are listed now: pcbnew's footprint list does not survive the
    # removals below as Python objects)
    unnet = [pad for fp in board.GetFootprints() for pad in fp.Pads()
             if pad.GetNetname() in complete] + [p_ for ps in touched.values() for p_ in ps]

    # copper -> keepouts (the lists are taken first, for the same reason)
    tracks, zones = list(board.GetTracks()), list(board.Zones())
    for t in tracks:
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            if anchors.get(net) == (p.x, p.y):
                continue
            g = Point(p.x, p.y).buffer(t.GetWidth(pcbnew.F_Cu) / 2, 4)
            _keepout(board, [pcbnew.F_Cu, pcbnew.B_Cu], _ring(g))
        else:
            a, b = t.GetStart(), t.GetEnd()
            # a track that ends on a kept via would bury the via's centre in
            # keepout on its layer, and a wire has to end exactly there: those
            # few go without (they are the via's own net)
            if anchors.get(net) not in ((a.x, a.y), (b.x, b.y)):
                g = LineString([(a.x, a.y), (b.x, b.y)]).buffer(t.GetWidth() / 2, 3)
                _keepout(board, [t.GetLayer()], _ring(g))
        board.Remove(t)
    for z in zones:
        if z.GetIsRuleArea():
            if not (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias()):
                board.Remove(z)
            continue
        # the reference's small pours round the RP2350 are copper a track may
        # not cross; the board-wide pours and the antenna island give way to
        # tracks (the ST60's signals cross the island), so they simply go
        if z.GetZoneName().startswith("RP2350 reference"):
            o = z.Outline()
            _keepout(board, [pcbnew.F_Cu],
                     [(o.CVertex(i).x, o.CVertex(i).y) for i in range(o.TotalVertices())])
        board.Remove(z)
    for pad in unnet:
        pad.SetNetCode(0)
    for net, pts in stubs:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1))); t.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
            t.SetWidth(mm(0.15)); t.SetLayer(pcbnew.F_Cu); t.SetNet(board.FindNet(net))
            board.Add(t)
    save(board, dst)
    for ext in (".kicad_pro", ".kicad_dru"):
        shutil.copyfile(Path(src).with_suffix(ext), Path(dst).with_suffix(ext))
    return complete, partial


def export_dsn(pcb, dsn):
    board = pcbnew.LoadBoard(str(pcb))
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("Specctra export failed")
    return Path(dsn).read_text().count("(net ")


def run_freerouting(dsn, ses, passes, timeout):
    """Headless: the GUI is turned off in the JVM and in freerouting's own
    config, which lives in java.io.tmpdir -- hence that being redirected."""
    if not JAR.exists():
        raise FileNotFoundError(f"no freerouting jar at {JAR}")
    cfg = WORK / "fr"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "freerouting.json").write_text(FR_CONFIG)
    if Path(ses).exists():
        Path(ses).unlink()
    cmd = ["java", "-Djava.awt.headless=true", f"-Djava.io.tmpdir={cfg}",
           "-Xmx4g", "-jar", str(JAR),
           "-de", str(dsn), "-do", str(ses), "-mp", str(passes)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    (WORK / "freerouting.log").write_text(r.stdout + r.stderr)
    if not Path(ses).exists():
        raise RuntimeError("freerouting produced no session file")


def bring_back(scratch, ses, real, out):
    """Import the session into the scratch board, then copy what the router
    made onto the real one, each item bound to its net by name."""
    sb = pcbnew.LoadBoard(str(scratch))
    kept = [(t.GetPosition().x, t.GetPosition().y) for t in sb.GetTracks()]   # the anchor vias
    if not pcbnew.ImportSpecctraSES(sb, str(ses)):
        raise RuntimeError("Specctra session import failed")
    rb = pcbnew.LoadBoard(str(real))
    n_t = n_v = 0
    for t in sb.GetTracks():
        net = rb.FindNet(t.GetNetname())
        if net is None:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            if any(abs(p.x - x) < 30000 and abs(p.y - y) < 30000 for x, y in kept):
                continue                      # an anchor: the real board has it already
            v = pcbnew.PCB_VIA(rb)
            v.SetPosition(p)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetWidth(pcbnew.F_Cu, t.GetWidth(pcbnew.F_Cu)); v.SetDrill(t.GetDrill())
            v.SetNet(net)
            rb.Add(v)
            n_v += 1
        else:
            if t.GetStart() == t.GetEnd():
                continue
            k = pcbnew.PCB_TRACK(rb)
            k.SetStart(t.GetStart()); k.SetEnd(t.GetEnd())
            k.SetWidth(t.GetWidth()); k.SetLayer(t.GetLayer()); k.SetNet(net)
            rb.Add(k)
            n_t += 1
    fill(rb)
    save(rb, out)
    return n_t, n_v


def summarise(report):
    from collections import Counter
    c = Counter(v["type"] for v in report.get("violations", ()))
    return len(report.get("unconnected_items", ())), dict(c)


def _step(name, *args):
    """One pcbnew job in a process of its own. pcbnew does not survive
    ExportSpecctraDSN -- the next LoadBoard in the same process hands back
    raw SWIG objects -- so the strip, the export and the import each get a
    fresh interpreter."""
    r = subprocess.run([sys.executable, __file__, "--step", name, *map(str, args)],
                       capture_output=True, text=True)
    m = re.search(r"^RESULT (.*)$", r.stdout, re.M)
    if not m:                      # (pcbnew sometimes dies on the way out, after the work is done)
        raise RuntimeError(f"{name} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads(m.group(1))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--step":
        name, args = sys.argv[2], sys.argv[3:]
        if name == "reset":
            import gen_board as GB
            board = pcbnew.LoadBoard(args[0])
            gone = [t for t in board.GetTracks() if not t.IsLocked()]
            for t in gone:
                board.Remove(t)
            # ... and back come the vias the ST60's signals are handed over
            # on, where "tidy" took one out of a finished board
            have = {(t.GetPosition().x, t.GetPosition().y) for t in board.GetTracks()
                    if t.Type() == pcbnew.PCB_VIA_T}
            back = 0
            for net, x, y in GB.st_anchors():
                p = pcbnew.VECTOR2I(mm(GB.OX + x), mm(GB.OY + y))
                if (p.x, p.y) not in have:
                    v = pcbnew.PCB_VIA(board)
                    v.SetPosition(p); v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                    v.SetWidth(pcbnew.F_Cu, mm(GB.VIA[0])); v.SetDrill(mm(GB.VIA[1]))
                    v.SetNet(board.FindNet(net)); v.SetLocked(True)
                    board.Add(v)
                    back += 1
            if gone or back:
                fill(board)
                save(board, args[0])
            print("RESULT", json.dumps(len(gone)), flush=True)
        elif name == "tidy":
            # A via the router was given to start from and then left on the
            # front, never going through it, is a hole for nothing: out.
            import gen_board as GB
            spots = {(round(x, 3), round(y, 3)) for _, x, y in GB.st_anchors()}
            rep = drc(args[0], WORK / "tidy.json")
            idle = set()
            for v in rep.get("violations", ()):
                if v["type"] == "via_dangling":
                    for it in v["items"]:
                        q = (round(it["pos"]["x"] - GB.OX, 3), round(it["pos"]["y"] - GB.OY, 3))
                        if q in spots:
                            idle.add((mm(it["pos"]["x"]), mm(it["pos"]["y"])))
            board = pcbnew.LoadBoard(args[0])
            gone = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T
                    and (t.GetPosition().x, t.GetPosition().y) in idle]
            for t in gone:
                board.Remove(t)
            if gone:
                fill(board)
                save(board, args[0])
            print("RESULT", json.dumps(len(gone)), flush=True)
        elif name == "ripup":
            # the router's tracks on the nets still open and on the nets
            # that fence them in, so that those are routed again together
            nets, opens = blockers(args[0])
            board = pcbnew.LoadBoard(args[0])
            gone = [t for t in board.GetTracks() if not t.IsLocked() and t.GetNetname() in nets]
            for t in gone:
                board.Remove(t)
            if gone:
                fill(board)
                save(board, args[0])
            print("RESULT", json.dumps([opens, nets, len(gone)]), flush=True)
        elif name == "stitch":
            import copper as CU
            import gen_board as GB
            board = pcbnew.LoadBoard(args[0])
            def add(x, y):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(mm(GB.OX + x), mm(GB.OY + y)))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetWidth(pcbnew.F_Cu, mm(CU.VIA[0])); v.SetDrill(mm(CU.VIA[1]))
                v.SetNet(board.FindNet("GND"))
                board.Add(v)
            res = CU.stitch(board, GB.OX, GB.OY, add)
            fill(board)
            save(board, args[0])
            print("RESULT", json.dumps(res), flush=True)
        elif name == "strip":
            complete, partial = strip(args[0], args[1], len(args) > 2 and args[2] == "escapes")
            print("RESULT", json.dumps([complete, partial]), flush=True)
        elif name == "export":
            print("RESULT", json.dumps(export_dsn(args[0], args[1])), flush=True)
        elif name == "import":
            print("RESULT", json.dumps(bring_back(args[0], args[1], args[2], args[3])), flush=True)
        return 0

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pcb", default=str(BOARD))
    ap.add_argument("--passes", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--rounds", type=int, default=4,
                    help="how many times an attempt goes back for what it left open")
    ap.add_argument("--attempts", type=int, default=8,
                    help="how many times to route afresh, looking for a run that closes everything")
    a = ap.parse_args()
    pcb = Path(a.pcb).resolve()
    WORK.mkdir(parents=True, exist_ok=True)

    scratch = WORK / "scratch.kicad_pcb"
    dsn, ses = WORK / "comms.dsn", WORK / "comms.ses"
    best = WORK / "best.kicad_pcb"
    best_unc = None
    # freerouting is not deterministic (its passes run on several threads),
    # and on a board this full one run leaves two connections open where the
    # next leaves none. Each attempt starts again from the generator's copper;
    # the best is kept.
    for attempt in range(1, a.attempts + 1):
        gone = _step("reset", pcb, "all")
        complete, partial = _step("strip", pcb, scratch)
        if attempt == 1:
            print(f"taken out of the problem: {len(complete)} complete nets; "
                  f"part-routed, one via each to reach: {', '.join(partial) or 'none'}")
        n = _step("export", scratch, dsn)
        run_freerouting(dsn, ses, a.passes, a.timeout)
        n_t, n_v = _step("import", scratch, ses, pcb, pcb)
        unc, viol = summarise(drc(pcb, WORK / "drc.json"))
        hard = {k: v for k, v in viol.items() if not k.startswith("silk") and k != "via_dangling"}
        print(f"attempt {attempt}: {n} nets, {n_t} tracks and {n_v} vias back; "
              f"{unc} unconnected {sorted(open_nets(json.loads((WORK / 'drc.json').read_text())))}; "
              f"violations {hard or 'none'}")
        # ... then go back for what it left: the open nets and their
        # fences come up and are routed again with the rest standing
        for rnd in range(a.rounds):
            if unc == 0:
                break
            opens, nets, gone = _step("ripup", pcb)
            _step("strip", pcb, scratch)
            n2 = _step("export", scratch, dsn)
            run_freerouting(dsn, ses, a.passes, a.timeout)
            _step("import", scratch, ses, pcb, pcb)
            unc, viol = summarise(drc(pcb, WORK / "drc.json"))
            hard = {k: v for k, v in viol.items() if not k.startswith("silk") and k != "via_dangling"}
            print(f"  again, {len(opens)} open with {len(nets) - len(opens)} neighbours "
                  f"({n2} nets): {unc} unconnected "
                  f"{sorted(open_nets(json.loads((WORK / 'drc.json').read_text())))}; violations {hard or 'none'}")
        score = unc + sum(hard.values())
        if best_unc is None or score < best_unc:
            best_unc = score
            shutil.copyfile(pcb, best)
        if score == 0:
            break
    shutil.copyfile(best, pcb)
    # ground stitching goes in last, round what the router did; unlocked, so
    # the next run takes it out with the router's tracks and puts it back
    idle = _step("tidy", pcb)
    grid = _step("stitch", pcb)
    if idle:
        print(f"tidied: {idle} hand-over vias the router did not go through, removed")
    print(f"stitched: {grid} ground vias across the board")
    rep = drc(pcb, WORK / "drc.json")
    unc, viol = summarise(rep)
    print(f"DRC: {unc} unconnected; violations {viol or 'none'}")
    return 0 if unc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
