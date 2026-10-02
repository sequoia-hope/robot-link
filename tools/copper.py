#!/usr/bin/env python3
"""copper.py -- the copper that is decided by rule: plane taps and stitching.

Two jobs, one test.

  plane_taps   A via beside every surface-mount pad whose net lives on a
               plane (GND on In1, +3V3 and ST_VDD on In2, +1V8 on its pour
               on the back), with a short track to it. A router handed
               those nets would join their pads with wire; with the taps in
               place it is never handed them at all.
  stitch       Ground vias: the fence each side of the antenna's moat, as on
               ST's board, and a grid across the rest of the board joining
               the front and back pours to the In1 plane.

The test (Model.via_ok, Model.track_ok) is geometry, in shapely: every pad,
track, via and hole on the board as a shape with its net, and a candidate is
legal if it keeps the board's clearance from every shape on another net, its
hole stays 0.5 mm from every other hole, and it is inside the board, outside
the antenna's ring and clear of the mounting holes.
"""
import math

import pcbnew
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

import placement as PL

CLEAR = 0.15 + 0.01            # the board's clearance, and a margin for rounding
HOLE_HOLE = 0.35 + 0.01        # what these tools keep; the board rule is 0.25
HOLE_CLEAR = 0.25 + 0.01       # copper of another net to a hole
EDGE = 0.3 + 0.02
VIA = (0.46, 0.2)
MOUNT_KEEP = 2.9               # radius kept clear round an M2.5 hole (the screw head)

# Where a net's plane is: a via for that net has to land on it. In2 is +3V3
# except under the antenna island, where it is the ST60's own supply, and
# over the 1.8 V parts of the link section: the translator's A side, the
# regulator's output on its right, the repeater's 1.8 V pins on its left
# (but not the repeater's 3V3 capacitors below it), R20 and J2's pin 1.
PLANE = {"GND": "In1.Cu", "+3V3": "In2.Cu", "ST_VDD": "In2.Cu", "+1V8": "In2.Cu"}
ST_VDD_RECT = (-10.0, 0.0, 3.6, PL.ST60[1] + PL.ISLAND[1] + PL.MOAT)
V18_POLY = [(-13.2, 7.5), (7.2, 7.5), (7.2, 12.9), (-5.0, 12.9), (-5.0, 9.8), (-10.4, 9.8),
            (-10.4, 10.6), (-13.2, 10.6)]
CU_LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
LID = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}


def ring_rect():
    """The antenna island and its moat: (x0, y0, x1, y1)."""
    cx, cy = PL.ST60
    hx, hy, m = PL.ISLAND[0], PL.ISLAND[1], PL.MOAT
    return (cx - hx - m, cy - hy - m, cx + hx + m, cy + hy + m)


class Model:
    """Every piece of copper and every hole on the board, as shapes."""

    def __init__(self, board, ox, oy):
        self.b, self.ox, self.oy = board, ox, oy
        self.shapes = {l: [] for l in CU_LAYERS}     # layer -> [(geom, net, kind)]
        self.holes = []                              # (x, y, r, net)
        self.trees = {}
        w, h, r = PL.W / 2, PL.H, PL.CORNER_R
        self.inside = box(-w, 0, w, h).buffer(-r).buffer(r)      # the rounded outline
        self.mounts = [(PL.PLACE[k][0], PL.PLACE[k][1]) for k in PL.PLACE if k.startswith("H")]
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                self.add_pad(pad)
        for t in board.GetTracks():
            self.add_track(t)
        # the small pours on the front (the reference's, round the RP2350):
        # copper like any other. The board-wide pours and planes are not in
        # the model -- they give way to everything.
        for z in board.Zones():
            if z.GetIsRuleArea() or not z.GetZoneName().startswith("RP2350 reference"):
                continue
            o = z.Outline()
            pts = [self.xy(o.CVertex(i)) for i in range(o.TotalVertices())]
            self._add("F.Cu", Polygon(pts), z.GetNetname(), "zone")

    def xy(self, p):
        return (pcbnew.ToMM(p.x) - self.ox, pcbnew.ToMM(p.y) - self.oy)

    def _poly(self, pad, layer):
        ps = pad.GetEffectivePolygon(LID[layer], pcbnew.ERROR_OUTSIDE)
        out = []
        for i in range(ps.OutlineCount()):
            o = ps.Outline(i)
            pts = [self.xy(o.CPoint(k)) for k in range(o.PointCount())]
            if len(pts) >= 3:
                out.append(Polygon(pts))
        return unary_union(out) if out else None

    def add_pad(self, pad):
        net = pad.GetNetname()
        for layer in CU_LAYERS:
            if pad.IsOnLayer(LID[layer]):
                g = self._poly(pad, layer)
                if g is not None and not g.is_empty:
                    self._add(layer, g, net, "pad")
        d = pad.GetDrillSize()
        if d.x > 0:
            x, y = self.xy(pad.GetPosition())
            self.holes.append((x, y, pcbnew.ToMM(max(d.x, d.y)) / 2, net))

    def add_track(self, t):
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            x, y = self.xy(t.GetPosition())
            self.add_via(net, x, y, pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), pcbnew.ToMM(t.GetDrill()))
        else:
            layer = self.b.GetLayerName(t.GetLayer())
            a, b = self.xy(t.GetStart()), self.xy(t.GetEnd())
            self._add(layer, LineString([a, b]).buffer(pcbnew.ToMM(t.GetWidth()) / 2), net, "track")

    def add_via(self, net, x, y, dia, drill):
        g = Point(x, y).buffer(dia / 2)
        for layer in CU_LAYERS:
            self._add(layer, g, net, "via")
        self.holes.append((x, y, drill / 2, net))

    def _add(self, layer, g, net, kind):
        self.shapes[layer].append((g, net, kind))
        self.trees.pop(layer, None)

    def _near(self, layer, g, reach):
        if layer not in self.trees:
            self.trees[layer] = STRtree([s[0] for s in self.shapes[layer]])
        for i in self.trees[layer].query(g.buffer(reach)):
            yield self.shapes[layer][i]

    # ---------------------------------------------------------------- tests
    def clear_of_others(self, layer, g, net, clearance=CLEAR):
        for s, n, _ in self._near(layer, g, clearance):
            if n != net and s.distance(g) < clearance:
                return False
        return True

    def on_plane(self, net):
        """The front-layer copper of one net that already reaches its plane:
        every shape joined, through touching shapes, to a via. Returned as
        one geometry (possibly empty)."""
        shapes = [(s, k) for s, n, k in self.shapes["F.Cu"] if n == net]
        parent = list(range(len(shapes)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        tree = STRtree([s for s, _ in shapes])
        for i, (s, _) in enumerate(shapes):
            for j in tree.query(s):
                if j > i and shapes[j][0].intersects(s):
                    parent[find(i)] = find(j)
        good = {find(i) for i, (_, k) in enumerate(shapes) if k == "via"}
        return unary_union([s for i, (s, _) in enumerate(shapes) if find(i) in good])

    def off_pads(self, g, gap=0.1):
        """No via in or against a pad, whatever its net: solder goes there."""
        return all(k != "pad" or s.distance(g) >= gap for s, n, k in self._near("F.Cu", g, gap))

    def on_board(self, g, margin=EDGE):
        return self.inside.buffer(-margin).contains(g)

    def off_ring(self, g):
        return not box(*ring_rect()).intersects(g)

    def off_mounts(self, x, y, r):
        return all(math.hypot(x - mx, y - my) >= MOUNT_KEEP + r for mx, my in self.mounts)

    def via_ok(self, net, x, y, size=VIA, ring_ok=False):
        dia, drill = size
        g = Point(x, y).buffer(dia / 2)
        if not self.on_board(g) or not self.off_mounts(x, y, dia / 2):
            return False
        if not ring_ok and not self.off_ring(g):
            return False
        for hx, hy, hr, hn in self.holes:
            d = math.hypot(x - hx, y - hy)
            if d - hr - drill / 2 < HOLE_HOLE:
                return False
            if hn != net and d - hr - dia / 2 < HOLE_CLEAR:
                return False
        hole = Point(x, y).buffer(drill / 2)
        for layer in CU_LAYERS:
            for s, n, _ in self._near(layer, g, max(CLEAR, HOLE_CLEAR)):
                if n != net and (s.distance(g) < CLEAR or s.distance(hole) < HOLE_CLEAR):
                    return False
        return self.off_pads(g)

    def track_ok(self, net, layer, a, b, w):
        g = LineString([a, b]).buffer(w / 2)
        return self.on_board(g) and self.clear_of_others(layer, g, net)


def in_rect(x, y, r, margin):
    return r[0] + margin <= x <= r[2] - margin and r[1] + margin <= y <= r[3] - margin


def plane_ok(net, x, y):
    """Is (x, y) over this net's plane, far enough in to be joined to it?"""
    pt = Point(x, y)
    v18 = Polygon(V18_POLY)
    if net == "ST_VDD":
        return in_rect(x, y, ST_VDD_RECT, 0.5)
    if net == "+1V8":
        return v18.buffer(-0.45).contains(pt)
    if net == "+3V3":
        return not in_rect(x, y, ST_VDD_RECT, -0.6) and not v18.buffer(0.6).contains(pt)
    return True


# The parts whose plane pads are never tapped themselves: the ST60 (the island
# and st60_copper see to them) and the RP2350, whose supply pins reach their
# capacitors on the reference's tracks -- the capacitor gets the tap.
NO_TAP = {"U4", "U1"}
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def plane_taps(B, ox, oy):
    """Tap every SMD pad on a plane net. Returns the number of vias added."""
    M = Model(B.b, ox, oy)
    vias = {}                          # net -> [(x, y)] taps made here
    joined = {}                        # net -> the front copper already on its plane
    made = 0
    failed = []
    pads = []
    for fp in B.b.GetFootprints():
        ref = fp.GetReference()
        if ref in NO_TAP:
            continue
        fx, fy = M.xy(fp.GetPosition())
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net not in PLANE or pad.GetDrillSize().x > 0 or not pad.IsOnLayer(pcbnew.F_Cu):
                continue
            x, y = M.xy(pad.GetPosition())
            pads.append((ref, pad, net, x, y, fx, fy))
    # the hardest first: the smallest pads have the fewest ways out
    pads.sort(key=lambda t: (t[1].GetSize().x * t[1].GetSize().y, t[0], t[1].GetNumber()))
    def tap(ref, pad, net, x, y, fx, fy):
        nonlocal made
        g = M._poly(pad, "F.Cu")
        if net not in joined:
            joined[net] = M.on_plane(net)
        if joined[net].intersects(g):
            return True                # already joined to a via, perhaps through its neighbours
        bb = g.bounds
        w = max(0.15, min(0.3, bb[2] - bb[0], bb[3] - bb[1]))
        # outward from the part first
        out = (x - fx, y - fy)
        dirs = sorted(DIRS, key=lambda d: -(d[0] * out[0] + d[1] * out[1]) / math.hypot(*d))
        best = None
        # a tap already made for this net, close enough to share
        for vx, vy in sorted(vias.get(net, []), key=lambda v: math.hypot(v[0] - x, v[1] - y)):
            if math.hypot(vx - x, vy - y) > 1.8:
                break
            if M.track_ok(net, "F.Cu", (x, y), (vx, vy), w):
                best = (vx, vy, False)
                break
        if best is None:
            for step in range(0, 22):
                for dx, dy in dirs:
                    n = math.hypot(dx, dy)
                    ux, uy = dx / n, dy / n
                    # from the pad's edge in that direction, then outward
                    reach = (abs(ux) * (bb[2] - bb[0]) + abs(uy) * (bb[3] - bb[1])) / 2
                    d = reach + VIA[0] / 2 + 0.12 + step * 0.1
                    vx, vy = round(x + ux * d, 3), round(y + uy * d, 3)
                    if not plane_ok(net, vx, vy):
                        continue
                    if M.via_ok(net, vx, vy) and M.track_ok(net, "F.Cu", (x, y), (vx, vy), w):
                        best = (vx, vy, True)
                        break
                if best:
                    break
        if best is None:
            # no room for a via: a track straight to a neighbour's pad on the
            # same net, which has or will have one (the repeater's 1.8 V pins
            # to the capacitors beside them)
            for d, px, py in sorted((math.hypot(px - x, py - y), px, py)
                                    for r2, p2, n2, px, py, _, _ in pads
                                    if n2 == net and p2 is not pad):
                if d > 2.0:
                    break
                if d > 0.05 and M.track_ok(net, "F.Cu", (x, y), (px, py), w):
                    B.track(net, "F.Cu", [(x, y), (px, py)], w)
                    M._add("F.Cu", LineString([(x, y), (px, py)]).buffer(w / 2), net, "track")
                    joined.pop(net, None)
                    return None        # joined to a neighbour: checked at the end
            return False
        vx, vy, new = best
        B.track(net, "F.Cu", [(x, y), (vx, vy)], w)
        M._add("F.Cu", LineString([(x, y), (vx, vy)]).buffer(w / 2), net, "track")
        if new:
            B.via(net, vx, vy)
            M.add_via(net, vx, vy, *VIA)
            vias.setdefault(net, []).append((vx, vy))
            made += 1
        joined.pop(net, None)
        return True

    # A pad with no room for a via of its own may still be joined through a
    # neighbour that gets one (C6 on the 3V3 ring under the RP2350): those
    # are asked again once everything else is done.
    later = [t for t in pads if tap(*t) is False]
    for t in later:
        if tap(*t) is False:
            failed.append(f"{t[0]}.{t[1].GetNumber()} ({t[2]})")
    # and the check: every one of those pads is now joined to a via
    for ref, pad, net, x, y, fx, fy in pads:
        if not M.on_plane(net).intersects(M._poly(pad, "F.Cu")):
            failed.append(f"{ref}.{pad.GetNumber()} ({net}) not joined")
    if failed:
        print("  ! no tap found for: " + ", ".join(failed))
    return made


# ------------------------------------------------------------- stitching ---
FENCE_PITCH = 0.9
GRID = 2.5


def stitch(board, ox, oy, add_via):
    """Ground vias on the routed board; add_via(x, y) makes one. Returns
    (fence, grid): how many went in round the antenna and across the board.

    Round the antenna, what ST's board has: a row just outside the moat and
    a row just inside the island's edge, wherever a via is legal -- which on
    the side the ST60's signals leave by, and where the translator's bundle
    passes underneath, is not everywhere. Elsewhere a 2.5 mm grid, to tie
    the front and back pours to the In1 plane.
    """
    M = Model(board, ox, oy)
    x0, y0, x1, y1 = ring_rect()
    cx, cy = PL.ST60
    hx, hy = PL.ISLAND
    spots = []
    def row(ax, ay, bx, by):
        n = max(1, int(round(math.hypot(bx - ax, by - ay) / FENCE_PITCH)))
        return [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)]
    out = 0.45                                  # outside the moat
    spots += row(x0 - out, 0.75, x0 - out, y1 + out) + row(x0 - out, y1 + out, x1 + out, y1 + out) \
           + row(x1 + out, y1 + out, x1 + out, 0.75)
    ins = 0.4                                   # inside the island's edge
    spots += row(cx - hx + ins, cy - hy + ins, cx - hx + ins, cy + hy - ins) \
           + row(cx - hx + ins, cy + hy - ins, cx + hx - ins, cy + hy - ins) \
           + row(cx + hx - ins, cy + hy - ins, cx + hx - ins, cy - hy + ins) \
           + row(cx + hx - ins, cy - hy + ins, cx - hx + ins, cy - hy + ins)
    fence = 0
    for x, y in spots:
        x, y = round(x, 3), round(y, 3)
        if M.via_ok("GND", x, y, ring_ok=True) and _spaced(M, x, y, 0.75):
            add_via(x, y)
            M.add_via("GND", x, y, *VIA)
            fence += 1
    grid = 0
    w, h = PL.W / 2, PL.H
    ny, nx = int(h / GRID), int(2 * w / GRID)
    for j in range(ny + 1):
        for i in range(nx + 1):
            x = round(-w + 1.5 + i * (2 * w - 3.0) / nx, 3)
            y = round(1.5 + j * (h - 3.0) / ny, 3)
            if M.via_ok("GND", x, y) and _spaced(M, x, y, 1.2):
                add_via(x, y)
                M.add_via("GND", x, y, *VIA)
                grid += 1
    return fence, grid


def _spaced(M, x, y, gap):
    """No other hole of any net within `gap`: stitching does not crowd."""
    return all(math.hypot(x - hx, y - hy) >= gap for hx, hy, _, _ in M.holes)
