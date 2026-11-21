"""Metric-space polyline maths for GTFS shapes.

All distances are metres. Geographic coordinates are projected onto a local equirectangular plane centred on the
polyline; at Delhi scale (< 100 km) the distortion is far below the 5 m simplification tolerance. Epsilons are
**never** applied in degrees.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_008.8
_DEG = math.pi / 180.0

Point = tuple[float, float]  # (x, y) metres in the local plane


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = lat1 * _DEG, lat2 * _DEG
    dp, dl = p2 - p1, (lon2 - lon1) * _DEG
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True)
class Plane:
    """Local equirectangular plane around (lat0, lon0)."""
    lat0: float
    lon0: float

    @property
    def _kx(self) -> float:
        return EARTH_RADIUS_M * _DEG * math.cos(self.lat0 * _DEG)

    def to_xy(self, lon: float, lat: float) -> Point:
        return ((lon - self.lon0) * self._kx, (lat - self.lat0) * EARTH_RADIUS_M * _DEG)

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return (self.lon0 + x / self._kx, self.lat0 + y / (EARTH_RADIUS_M * _DEG))

    @staticmethod
    def around(lonlat: list[tuple[float, float]]) -> "Plane":
        lons = [p[0] for p in lonlat]; lats = [p[1] for p in lonlat]
        return Plane((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)


def _point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """(distance, t in [0,1]) from point to segment AB."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / seg2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def distance_to_polyline(p: Point, line: list[Point]) -> float:
    if len(line) == 1:
        return math.hypot(p[0] - line[0][0], p[1] - line[0][1])
    return min(_point_segment(p[0], p[1], *line[i], *line[i + 1])[0] for i in range(len(line) - 1))


def polyline_length(line: list[Point]) -> float:
    return sum(math.hypot(line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1]) for i in range(len(line) - 1))


def rdp(line: list[Point], epsilon_m: float) -> list[int]:
    """Indices kept by Ramer-Douglas-Peucker (iterative; first and last are always kept)."""
    n = len(line)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = line[lo]; bx, by = line[hi]
        worst, idx = -1.0, -1
        for i in range(lo + 1, hi):
            d, _ = _point_segment(line[i][0], line[i][1], ax, ay, bx, by)
            if d > worst:
                worst, idx = d, i
        if worst > epsilon_m:
            keep[idx] = True
            stack.append((lo, idx)); stack.append((idx, hi))
    return [i for i, k in enumerate(keep) if k]


@dataclass(frozen=True)
class Candidate:
    """A possible projection of one stop onto the polyline."""
    seg: int          # segment index i  (between vertex i and i+1)
    t: float          # fraction along the segment
    along_m: float    # cumulative distance from polyline start
    dist_m: float     # distance from the stop to the polyline at this point


class PolylineIndex:
    """Uniform-grid index over polyline segments for fast 'segments near this point' queries."""

    def __init__(self, line: list[Point], reach_m: float, cell_m: float = 200.0) -> None:
        self.line, self.reach, self.cell = line, reach_m, cell_m
        self.cum = [0.0]
        for i in range(len(line) - 1):
            self.cum.append(self.cum[-1] + math.hypot(line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1]))
        self.grid: dict[tuple[int, int], list[int]] = {}
        for i in range(len(line) - 1):
            (ax, ay), (bx, by) = line[i], line[i + 1]
            x0, x1 = sorted((ax, bx)); y0, y1 = sorted((ay, by))
            for cx in range(int((x0 - reach_m) // cell_m), int((x1 + reach_m) // cell_m) + 1):
                for cy in range(int((y0 - reach_m) // cell_m), int((y1 + reach_m) // cell_m) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)

    def candidates(self, p: Point, threshold_m: float) -> list[Candidate]:
        """Best projection per nearby segment within ``threshold_m``; local minima only (adjacent-segment duplicates removed)."""
        cell = (int(p[0] // self.cell), int(p[1] // self.cell))
        found: dict[int, Candidate] = {}
        for i in self.grid.get(cell, ()):
            d, t = _point_segment(p[0], p[1], *self.line[i], *self.line[i + 1])
            if d <= threshold_m:
                seg_len = self.cum[i + 1] - self.cum[i]
                found[i] = Candidate(i, t, self.cum[i] + t * seg_len, d)
        out: list[Candidate] = []
        for i in sorted(found):  # drop a candidate if an adjacent segment has a closer-or-equal one (same physical crossing)
            c = found[i]
            nb = [found[j] for j in (i - 1, i + 1) if j in found]
            if all(c.dist_m < o.dist_m or (c.dist_m == o.dist_m and c.along_m <= o.along_m) for o in nb):
                out.append(c)
        return out


def monotone_match(index: PolylineIndex, stops: list[Point], threshold_m: float, slack_m: float = 1.0
                   ) -> list[Candidate | None]:
    """Assign each stop (in trip order) a candidate so that ``along_m`` never decreases (beyond ``slack_m``).

    Viterbi over candidates minimising the summed stop-to-line distance. A stop with no candidate within the
    threshold is left ``None`` (it does not break the chain). Handles loops and out-and-back geometry because the
    choice between two passes of the same point is made by the *whole* sequence, not by the nearest point alone.
    """
    layers: list[tuple[int, list[Candidate]]] = []
    for k, p in enumerate(stops):
        cands = index.candidates(p, threshold_m)
        if cands:
            layers.append((k, cands))
    result: list[Candidate | None] = [None] * len(stops)
    if not layers:
        return result
    cost = [[c.dist_m for c in layers[0][1]]]
    back: list[list[int]] = [[-1] * len(layers[0][1])]
    for li in range(1, len(layers)):
        prev_c, cur_c = layers[li - 1][1], layers[li][1]
        row, brow = [], []
        for c in cur_c:
            best, bj = math.inf, -1
            for j, pc in enumerate(prev_c):
                if pc.along_m <= c.along_m + slack_m and cost[li - 1][j] < best:
                    best, bj = cost[li - 1][j], j
            if bj < 0:  # no predecessor is consistent: allow the chain to restart here with a heavy penalty
                best = min(cost[li - 1]) + 10_000.0
                bj = cost[li - 1].index(min(cost[li - 1]))
            row.append(best + c.dist_m); brow.append(bj)
        cost.append(row); back.append(brow)
    j = min(range(len(cost[-1])), key=lambda x: (cost[-1][x], layers[-1][1][x].along_m))
    for li in range(len(layers) - 1, -1, -1):
        result[layers[li][0]] = layers[li][1][j]
        j = back[li][j]
    return result


def slice_polyline(line: list[Point], cum: list[float], a: Candidate, b: Candidate) -> list[Point]:
    """Points from projection ``a`` to projection ``b`` (a before b), with interpolated end points."""
    def at(c: Candidate) -> Point:
        (ax, ay), (bx, by) = line[c.seg], line[c.seg + 1]
        return (ax + c.t * (bx - ax), ay + c.t * (by - ay))
    pts = [at(a)]
    pts.extend(line[a.seg + 1: b.seg + 1])
    pts.append(at(b))
    dedup = [pts[0]]
    for p in pts[1:]:
        if p != dedup[-1]:
            dedup.append(p)
    return dedup
