#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.9"
# dependencies = ["pymongo>=4"]
# ///
"""
tiks_stats.py — TIKS Ultimate RSVP app retrospective stats.

Subcommands:
    stats    overall numbers + HTML card
    wa       WhatsApp scrolling avoided
    dow      practice sessions by day of week (year-by-year heatmap)
    monthly  events/attendance by month, with clock-face view
    special  multi-day events and top single-day events by attendance
    all      run every subcommand in sequence

Usage:
    uv run tiks_stats.py <subcommand> [options]
    uv run tiks_stats.py --help
    uv run tiks_stats.py stats --out card.html --top 15
    uv run tiks_stats.py wa --lines-per-screen 18 --header-lines 2
    uv run tiks_stats.py dow --max-hours 20
    uv run tiks_stats.py special --max-hours 24 --top 30
    uv run tiks_stats.py all
"""

import argparse
import datetime as dt
import html as html_lib
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict

from bson.dbref import DBRef
from pymongo import MongoClient

# ── shared constants ─────────────────────────────────────────────────────────
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


# ── shared helpers ───────────────────────────────────────────────────────────


def connect(args):
    return MongoClient(args.uri)[args.db]


def ref_id(v):
    if v is None:
        return None
    if isinstance(v, DBRef):
        return v.id
    if isinstance(v, dict):
        return v.get("$id") or v.get("oid")
    return v


def yr(d):
    return d.year if isinstance(d, dt.datetime) else None


def active_count(rsvps):
    return sum(1 for r in rsvps if not r.get("cancelled") and not r.get("waitlisted"))


def fmt_date(d):
    return d.strftime("%b %Y") if isinstance(d, dt.datetime) else "?"


def fmt_duration(start, end):
    if not isinstance(end, dt.datetime):
        return ""
    secs = (end - start).total_seconds()
    if secs < 86400:
        return f"{secs/3600:.0f}h"
    return f"{secs/86400:.1f}d"


def bar(value, max_value, width=40):
    if max_value == 0:
        return "░" * width
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def section(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


# ── SVG chart helpers ─────────────────────────────────────────────────────────

_ACCENT = "#e94560"
_MUTED = "#6b7280"
_INK = "#1a1a2e"


def _svg_bars(labels, values, color=_ACCENT, value_fmt=None, W=680, H=200):
    if value_fmt is None:
        value_fmt = str
    """Vertical bar chart. Returns an SVG string."""
    pt, pr, pb, pl = 28, 8, 32, 8
    cw = W - pl - pr
    ch = H - pt - pb
    n = len(labels)
    if not n:
        return ""
    max_v = max(values, default=1) or 1
    gap = cw / n
    bw = gap * 0.55
    parts = []
    for i, (lbl, v) in enumerate(zip(labels, values)):
        x = pl + i * gap + (gap - bw) / 2
        bh = v / max_v * ch
        y = pt + ch - bh
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" rx="3"/>'
        )
        if v:
            parts.append(
                f'<text x="{x+bw/2:.1f}" y="{y-4:.1f}" text-anchor="middle" font-size="9" fill="{color}">{value_fmt(v)}</text>'
            )
        parts.append(
            f'<text x="{x+bw/2:.1f}" y="{H-6:.1f}" text-anchor="middle" font-size="10" fill="{_MUTED}">{lbl}</text>'
        )
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


def _svg_line(labels, values, color=_ACCENT, value_fmt=None, W=680, H=180):
    if value_fmt is None:
        value_fmt = str
    """Line chart with area fill and dots. Returns an SVG string."""
    pt, pr, pb, pl = 28, 8, 32, 8
    cw = W - pl - pr
    ch = H - pt - pb
    n = len(labels)
    if n < 2:
        return ""
    max_v = max(values, default=1) or 1
    xs = [pl + i * cw / (n - 1) for i in range(n)]
    ys = [pt + ch * (1 - v / max_v) for v in values]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area_pts = f"{xs[0]:.1f},{pt+ch:.1f} {pts} {xs[-1]:.1f},{pt+ch:.1f}"
    parts = [
        f'<polygon points="{area_pts}" fill="{color}" opacity="0.12"/>',
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>',
    ]
    for x, y, lbl, v in zip(xs, ys, labels, values):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{y-7:.1f}" text-anchor="middle" font-size="9" fill="{color}">{value_fmt(v)}</text>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{H-6:.1f}" text-anchor="middle" font-size="10" fill="{_MUTED}">{lbl}</text>'
        )
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


def _svg_stacked_bars(labels, series, colors, W=680, H=220):
    """Stacked vertical bar chart. series = list of (legend_label, values)."""
    pt, pr, pb, pl = 28, 120, 32, 8
    cw = W - pl - pr
    ch = H - pt - pb
    n = len(labels)
    totals = [sum(s[1][i] for s in series) for i in range(n)]
    max_v = max(totals, default=1) or 1
    gap = cw / n
    bw = gap * 0.55
    parts = []
    for i, lbl in enumerate(labels):
        x = pl + i * gap + (gap - bw) / 2
        bottom = pt + ch
        for (_, vals), color in zip(series, colors):
            v = vals[i]
            bh = v / max_v * ch
            y = bottom - bh
            if bh > 0:
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" rx="2"/>'
                )
            bottom = y
        parts.append(
            f'<text x="{x+bw/2:.1f}" y="{H-6:.1f}" text-anchor="middle" font-size="10" fill="{_MUTED}">{lbl}</text>'
        )
        t = totals[i]
        if t:
            bar_top = pt + ch - t / max_v * ch
            parts.append(
                f'<text x="{x+bw/2:.1f}" y="{bar_top-3:.1f}" text-anchor="middle" font-size="9" fill="{_INK}">{t}</text>'
            )
    # legend
    lx, ly = W - pr + 10, pt
    for (label, _), color in zip(series, colors):
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{color}" rx="2"/>'
        )
        parts.append(
            f'<text x="{lx+16}" y="{ly+10}" font-size="11" fill="{_INK}">{label}</text>'
        )
        ly += 20
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


def _svg_heatmap(row_labels, col_labels, matrix, W=680):
    """Grid heatmap. matrix[row][col] = value. Returns SVG string."""
    cell_w = min(52, (W - 130) // max(len(col_labels), 1))
    cell_h = 28
    pl = 130
    pt = 28
    rows = len(row_labels)
    H = pt + rows * cell_h + 20
    max_v = max((v for row in matrix for v in row if v), default=1)

    parts = []
    # col headers
    for j, lbl in enumerate(col_labels):
        x = pl + j * cell_w + cell_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{pt-6}" text-anchor="middle" font-size="10" fill="{_MUTED}">{lbl}</text>'
        )

    for i, row_lbl in enumerate(row_labels):
        y = pt + i * cell_h
        parts.append(
            f'<text x="{pl-6}" y="{y+cell_h*0.65:.1f}" text-anchor="end" font-size="11" fill="{_INK}">{row_lbl}</text>'
        )
        for j, v in enumerate(matrix[i]):
            x = pl + j * cell_w
            opacity = 0.08 + 0.87 * v / max_v if v else 0
            parts.append(
                f'<rect x="{x+1}" y="{y+2}" width="{cell_w-2}" height="{cell_h-4}" fill="{_ACCENT}" opacity="{opacity:.2f}" rx="3"/>'
            )
            if v:
                txt_fill = "#fff" if opacity > 0.5 else _ACCENT
                parts.append(
                    f'<text x="{x+cell_w/2:.1f}" y="{y+cell_h*0.65:.1f}" text-anchor="middle" font-size="10" fill="{txt_fill}">{v}</text>'
                )

    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


_PALETTE = [
    "#e94560",
    "#4f86c6",
    "#22c55e",
    "#f59e0b",
    "#8b5cf6",
    "#ec4899",
    "#14b8a6",
    "#f97316",
    "#6366f1",
    "#84cc16",
    "#06b6d4",
    "#d946ef",
    "#0ea5e9",
    "#fb923c",
    "#34d399",
    "#f43f5e",
    "#60a5fa",
    "#fbbf24",
    "#a78bfa",
    "#a3e635",
]


def _svg_stream(years, player_year_data, W=740, H=320):
    """
    Stream graph (ThemeRiver). player_year_data: [(name, {year: count})], ordered
    so most-games players are in the middle, less active on the outside.
    Bands are stacked and centered; bezier curves smooth transitions between years.
    """
    pt, pb, pl, pr = 28, 28, 8, 8
    ch = H - pt - pb
    cw = W - pl - pr
    n_yr = len(years)
    n_pl = len(player_year_data)
    mid_y = pt + ch / 2

    color_of = {
        nm: _PALETTE[i % len(_PALETTE)]
        for i, nm in enumerate(nm for nm, _ in player_year_data)
    }

    # scale: fit the tallest year-stack into ch
    year_totals = {y: sum(d.get(y, 0) for _, d in player_year_data) for y in years}
    max_total = max(year_totals.values(), default=1)
    scale = ch / max_total

    def xfor(i):
        return pl + i * cw / max(n_yr - 1, 1)

    # compute top/bottom y for each player at each year, centered
    tops = [[0.0] * n_yr for _ in range(n_pl)]
    bots = [[0.0] * n_yr for _ in range(n_pl)]
    for i, y in enumerate(years):
        total_h = year_totals[y] * scale
        cur = mid_y - total_h / 2
        for p, (_, data) in enumerate(player_year_data):
            h = data.get(y, 0) * scale
            tops[p][i] = cur
            bots[p][i] = cur + h
            cur += h

    xs = [xfor(i) for i in range(n_yr)]

    def smooth_band(top_ys, bot_ys):
        """SVG path for one band using cubic bezier curves."""

        def curve(ys, reverse=False):
            pts = list(zip(xs, ys))
            if reverse:
                pts = pts[::-1]
            path = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
            for k in range(len(pts) - 1):
                x1, y1 = pts[k]
                x2, y2 = pts[k + 1]
                cx = (x2 - x1) * 0.5
                path += f" C{x1+cx:.1f},{y1:.1f} {x2-cx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            return path

        return curve(top_ys) + " " + curve(bot_ys, reverse=True) + " Z"

    parts = []

    # year labels
    for i, y in enumerate(years):
        parts.append(
            f'<text x="{xs[i]:.0f}" y="{H-6}" text-anchor="middle"'
            f' font-size="11" fill="{_MUTED}">{y}</text>'
        )

    # bands (back to front — last player on top visually)
    for p, (nm, data) in enumerate(player_year_data):
        col = color_of[nm]
        path = smooth_band(tops[p], bots[p])
        parts.append(f'<path d="{path}" fill="{col}" opacity="0.82"/>')

        # inline label at the widest year
        widths = [(bots[p][i] - tops[p][i], i) for i in range(n_yr)]
        best_h, bi = max(widths)
        if best_h >= 13:
            lx = xs[bi]
            ly = (tops[p][bi] + bots[p][bi]) / 2 + 4
            fs = min(11, max(8, int(best_h * 0.55)))
            parts.append(
                f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle"'
                f' font-size="{fs}" font-weight="bold" fill="white"'
                f' style="text-shadow:0 0 3px rgba(0,0,0,.4)">{nm}</text>'
            )

    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


def _person_path(x, y, w, h, color):
    """Simple person silhouette at (x,y) fitting w×h."""
    hr = w * 0.28  # head radius
    hcx = x + w / 2
    hcy = y + hr + 1
    bx = x + w * 0.15
    by = hcy + hr + 1
    bw = w * 0.7
    bh = h - (by - y)
    return (
        f'<circle cx="{hcx:.1f}" cy="{hcy:.1f}" r="{hr:.1f}" fill="{color}"/>'
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}"'
        f' rx="{bw*0.35:.1f}" fill="{color}"/>'
    )


def _svg_pictogram(total, unit=100, W=680, color=_ACCENT, muted_color="#f4c2cc"):
    """Grid of person icons; each icon = unit show-ups. Last icon is partial."""
    icon_w, icon_h, gap = 28, 36, 6
    step = icon_w + gap
    cols = (W) // step
    n_full = total // unit
    frac = (total % unit) / unit
    n_icons = n_full + (1 if frac else 0)
    rows = math.ceil(n_icons / cols)
    H = rows * (icon_h + gap) + 28

    parts = []
    for k in range(n_icons):
        col = k % cols
        row = k // cols
        x = col * step
        y = row * (icon_h + gap)
        c = muted_color if k == n_full else color
        # partial last icon: clip with a rect
        if k == n_full and frac:
            clip_id = "pc"
            parts.append(
                f'<defs><clipPath id="{clip_id}">'
                f'<rect x="{x}" y="{y}" width="{icon_w*frac:.1f}" height="{icon_h}"/>'
                f"</clipPath></defs>"
            )
            parts.append(
                f'<g opacity="0.2">{_person_path(x, y, icon_w, icon_h, color)}</g>'
            )
            parts.append(
                f'<g clip-path="url(#{clip_id})">{_person_path(x, y, icon_w, icon_h, color)}</g>'
            )
        else:
            parts.append(_person_path(x, y, icon_w, icon_h, c))

    parts.append(
        f'<text x="0" y="{H-4}" font-size="10" fill="{_MUTED}">'
        f"Each figure = {unit:,} show-ups &nbsp;&nbsp; Total: {total:,}</text>"
    )
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


def _svg_hbars(labels, values, color=_ACCENT, value_fmt=None, W=680, H=None):
    if value_fmt is None:
        value_fmt = str
    """Horizontal bar chart. H auto-sizes to number of rows."""
    row_h = 28
    pt, pr, pb, pl = 8, 50, 8, 110
    if H is None:
        H = pt + pb + row_h * len(labels)
    cw = W - pl - pr
    max_v = max(values, default=1) or 1
    parts = []
    for i, (lbl, v) in enumerate(zip(labels, values)):
        y = pt + i * row_h
        bw = v / max_v * cw
        parts.append(
            f'<text x="{pl-6}" y="{y+row_h*0.65:.1f}" text-anchor="end" font-size="11" fill="{_INK}">{lbl}</text>'
        )
        parts.append(
            f'<rect x="{pl}" y="{y+4}" width="{bw:.1f}" height="{row_h-10}" fill="{color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{pl+bw+4:.1f}" y="{y+row_h*0.65:.1f}" font-size="10" fill="{_MUTED}">{value_fmt(v)}</text>'
        )
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">{"".join(parts)}</svg>'


# ── interactive stream graph ──────────────────────────────────────────────────


def _build_stream_html(sorted_years, player_data):
    """Self-contained interactive HTML stream graph for all players."""
    N = len(player_data)
    W = 960
    pt, pb, pl, pr = 52, 52, 10, 10
    ch = 520
    cw = W - pl - pr
    n_yr = len(sorted_years)
    mid_y = pt + ch / 2

    def player_color(i):
        hue = (i * 137.508) % 360
        sat = 65 + (i % 3) * 8
        lit = 46 + (i % 2) * 10
        return f"hsl({hue:.0f},{sat}%,{lit}%)"

    colors = [player_color(i) for i in range(N)]

    year_totals = {y: sum(d.get(y, 0) for _, d in player_data) for y in sorted_years}
    max_total = max(year_totals.values(), default=1)
    scale = ch / max_total

    def xfor(i):
        return pl + i * cw / max(n_yr - 1, 1)

    xs = [xfor(i) for i in range(n_yr)]

    tops = [[0.0] * n_yr for _ in range(N)]
    bots = [[0.0] * n_yr for _ in range(N)]
    for i, y in enumerate(sorted_years):
        total_h = year_totals[y] * scale
        cur = mid_y - total_h / 2
        for p, (_, data) in enumerate(player_data):
            h = data.get(y, 0) * scale
            tops[p][i] = cur
            bots[p][i] = cur + h
            cur += h

    def smooth_band(top_ys, bot_ys):
        def curve(ys, rev=False):
            pts = list(zip(xs, ys))
            if rev:
                pts = pts[::-1]
            path = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
            for k in range(len(pts) - 1):
                x1, y1 = pts[k]
                x2, y2 = pts[k + 1]
                cx = (x2 - x1) * 0.5
                path += f" C{x1+cx:.1f},{y1:.1f} {x2-cx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            return path

        return curve(top_ys) + " " + curve(bot_ys, rev=True) + " Z"

    esc = html_lib.escape
    bands_svg = []
    labels_svg = []
    json_players = []

    for p, (nm, data) in enumerate(player_data):
        col = colors[p]
        total = sum(data.values())
        path_d = smooth_band(tops[p], bots[p])
        bands_svg.append(
            f'<path class="band" data-player="{esc(nm)}" data-total="{total}" '
            f'd="{path_d}" fill="{col}" opacity="0.82" stroke="none"/>'
        )
        widths = [(bots[p][i] - tops[p][i], i) for i in range(n_yr)]
        best_h, bi = max(widths)
        if best_h >= 14:
            lx = xs[bi]
            ly = (tops[p][bi] + bots[p][bi]) / 2 + 4
            fs = min(11, max(8, int(best_h * 0.55)))
            labels_svg.append(
                f'<text class="band-label" data-player="{esc(nm)}" '
                f'x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" '
                f'font-size="{fs}" font-weight="bold" fill="white" '
                f'style="text-shadow:0 0 3px rgba(0,0,0,.5);pointer-events:none">{esc(nm)}</text>'
            )
        json_players.append(
            {
                "name": nm,
                "total": total,
                "color": col,
                "years": {str(y): data.get(y, 0) for y in sorted_years},
            }
        )

    axis_svg = []
    for i, y in enumerate(sorted_years):
        x = xs[i]
        axis_svg.append(
            f'<line x1="{x:.0f}" y1="{mid_y - ch/2 - 10}" x2="{x:.0f}" y2="{mid_y + ch/2 + 10}"'
            f' stroke="#e5e7eb" stroke-width="1"/>'
        )
        axis_svg.append(
            f'<text x="{x:.0f}" y="{mid_y + ch/2 + 28}" text-anchor="middle"'
            f' font-size="13" font-weight="700" fill="#6b7280">{y}</text>'
        )

    svg_h = pt + ch + pb
    svg_content = (
        f'<svg id="stream" viewBox="0 0 {W} {svg_h}" style="width:100%;min-width:600px;height:auto;display:block">'
        + "".join(axis_svg)
        + "".join(bands_svg)
        + "".join(labels_svg)
        + "</svg>"
    )

    players_json = json.dumps(json_players, ensure_ascii=False)
    years_json = json.dumps([str(y) for y in sorted_years])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIKS · Who Showed Up</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;background:#faf9f6;color:#1a1a2e;padding:28px 32px}}
h1{{font-size:2.8rem;font-weight:900;letter-spacing:-1.5px;line-height:1;margin-bottom:6px}}
.sub{{color:#6b7280;font-size:.95rem;margin-bottom:26px;line-height:1.6}}
#controls{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:16px}}
#search{{padding:9px 16px;border:2px solid #e5e7eb;border-radius:24px;font-size:14px;width:240px;outline:none;background:#fff;transition:border-color .15s}}
#search:focus{{border-color:#e94560}}
.sl-wrap{{display:flex;align-items:center;gap:8px;font-size:14px;color:#374151}}
#minEvents{{accent-color:#e94560;width:100px;cursor:pointer}}
#minLabel{{font-weight:700;min-width:22px}}
#count{{color:#9ca3af;font-size:13px}}
.hint{{font-size:12px;color:#d1d5db}}
#sw{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.band{{transition:opacity .18s;cursor:pointer}}
.band-label{{transition:opacity .18s}}
#tip{{position:fixed;background:#111827;color:#f9fafb;padding:14px 18px;border-radius:10px;font-size:13px;pointer-events:none;opacity:0;transition:opacity .12s;max-width:240px;z-index:100;box-shadow:0 8px 30px rgba(0,0,0,.4)}}
.tt-name{{font-size:17px;font-weight:900;margin-bottom:10px}}
.tt-total{{font-size:12px;color:#9ca3af;margin-bottom:8px}}
.tt-row{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:2px 0}}
.tt-yr{{color:#6b7280;font-size:12px;min-width:32px}}
.tt-bar{{height:6px;border-radius:3px;flex:1}}
.tt-g{{font-weight:700;font-size:12px;min-width:24px;text-align:right}}
</style>
</head>
<body>
<h1>TIKS · Who Showed Up</h1>
<p class="sub">Player activity 2018 – 2026 &nbsp;·&nbsp; band width = games attended that year<br>
<strong>Hover</strong> to identify &nbsp;·&nbsp; <strong>Click</strong> to pin &nbsp;·&nbsp; <strong>Search</strong> to highlight &nbsp;·&nbsp; <kbd>Esc</kbd> to reset</p>
<div id="controls">
  <input id="search" type="text" placeholder="Search player…" autocomplete="off">
  <div class="sl-wrap">
    <span>Min events:</span>
    <input id="minEvents" type="range" min="1" max="30" value="5" step="1">
    <span id="minLabel">5</span>
  </div>
  <span id="count"></span>
  <span class="hint">Tip: bands stay in place when filtered — use search to find specific players</span>
</div>
<div id="sw">{svg_content}</div>
<div id="tip"></div>
<script>
const PLAYERS={players_json};
const YEARS={years_json};
const maxPY={{}};
YEARS.forEach(y=>{{maxPY[y]=Math.max(...PLAYERS.map(p=>p.years[y]||0))}});

const svg=document.getElementById('stream');
const tip=document.getElementById('tip');
const srch=document.getElementById('search');
const minSl=document.getElementById('minEvents');
const minLbl=document.getElementById('minLabel');
const cntEl=document.getElementById('count');
const bands=[...svg.querySelectorAll('.band')];
const lbls=[...svg.querySelectorAll('.band-label')];

let pinned=null, curMin=5, curQ='';

const pInfo=name=>PLAYERS.find(p=>p.name===name);

function updateCount(){{
  const v=bands.filter(b=>+b.dataset.total>=curMin).length;
  cntEl.textContent=v+' player'+(v===1?'':'s')+' shown';
}}

function applyVis(){{
  bands.forEach(b=>{{b.style.display=+b.dataset.total>=curMin?'':'none'}});
  lbls.forEach(l=>{{
    const p=pInfo(l.dataset.player);
    l.style.display=(p&&p.total>=curMin)?'':'none';
  }});
  updateCount();
}}

function tipHtml(name){{
  const p=pInfo(name); if(!p) return '';
  const rows=YEARS.map(y=>{{
    const g=p.years[y]||0; if(!g) return '';
    const w=maxPY[y]?Math.round(g/maxPY[y]*70):0;
    return `<div class="tt-row"><span class="tt-yr">${{y}}</span><div class="tt-bar" style="background:${{p.color}};width:${{w}}px"></div><span class="tt-g">${{g}}</span></div>`;
  }}).join('');
  return `<div class="tt-name">${{p.name}}</div><div class="tt-total">${{p.total}} games total</div>${{rows}}`;
}}

function showTip(e,name){{tip.innerHTML=tipHtml(name);tip.style.opacity='1';moveTip(e)}}
function moveTip(e){{
  const x=e.clientX+18,y=e.clientY-8;
  tip.style.left=Math.min(x,window.innerWidth-258)+'px';
  tip.style.top=Math.min(y,window.innerHeight-tip.offsetHeight-8)+'px';
}}
function hideTip(){{tip.style.opacity='0'}}

function hl(name){{
  bands.forEach(b=>b.style.opacity=b.dataset.player===name?'1':'0.06');
  lbls.forEach(l=>l.style.opacity=l.dataset.player===name?'1':'0');
}}
function dimQ(q){{
  bands.forEach(b=>{{const m=b.dataset.player.toLowerCase().includes(q);b.style.opacity=m?'1':'0.06'}});
  lbls.forEach(l=>{{const m=l.dataset.player.toLowerCase().includes(q);l.style.opacity=m?'1':'0'}});
}}
function reset(){{bands.forEach(b=>b.style.opacity='');lbls.forEach(l=>l.style.opacity='')}}

bands.forEach(b=>{{
  b.addEventListener('mouseenter',e=>{{if(pinned)return;hl(b.dataset.player);showTip(e,b.dataset.player)}});
  b.addEventListener('mousemove',moveTip);
  b.addEventListener('mouseleave',()=>{{if(pinned)return;if(curQ)dimQ(curQ);else reset();hideTip()}});
  b.addEventListener('click',()=>{{
    if(pinned===b.dataset.player){{pinned=null;if(curQ)dimQ(curQ);else reset();hideTip()}}
    else{{pinned=b.dataset.player;hl(pinned);showTip({{clientX:window.innerWidth/2,clientY:80}},pinned)}}
  }});
}});

srch.addEventListener('input',()=>{{
  pinned=null;hideTip();
  curQ=srch.value.toLowerCase().trim();
  if(!curQ){{reset();return}}
  const exact=bands.find(b=>b.dataset.player.toLowerCase()===curQ);
  if(exact){{pinned=exact.dataset.player;hl(pinned)}}else{{dimQ(curQ)}}
}});

minSl.addEventListener('input',()=>{{curMin=+minSl.value;minLbl.textContent=curMin;applyVis()}});

document.addEventListener('keydown',e=>{{
  if(e.key==='Escape'){{pinned=null;curQ='';srch.value='';reset();hideTip()}}
}});

applyVis();
</script>
</body>
</html>"""


def cmd_stream(args):
    db = connect(args)
    min_ev = args.min_events

    events = list(db.event.find({}, {"rsvps": 1, "date": 1}))
    users = {str(u["_id"]): u for u in db.user.find()}

    def nick(uid):
        u = users.get(str(uid), {})
        return (u.get("nick") or u.get("name") or str(uid)).split()[0]

    rsvps_by_uid = defaultdict(lambda: defaultdict(int))
    for e in events:
        eyr = yr(e.get("date"))
        if not eyr:
            continue
        for r in e.get("rsvps") or []:
            if r.get("cancelled") or r.get("waitlisted"):
                continue
            uid = ref_id(r.get("user"))
            if uid:
                rsvps_by_uid[uid][eyr] += 1

    sorted_years = sorted({y for yc in rsvps_by_uid.values() for y in yc})

    qualified = [
        (uid, dict(yc))
        for uid, yc in rsvps_by_uid.items()
        if sum(yc.values()) >= min_ev
    ]
    qualified.sort(key=lambda kv: sum(kv[1].values()), reverse=True)

    # interleave: biggest in the middle
    upper = [kv for i, kv in enumerate(qualified) if i % 2 == 0]
    lower = [kv for i, kv in enumerate(qualified) if i % 2 == 1]
    ordered = list(reversed(upper)) + lower

    player_data = [(nick(uid), yc) for uid, yc in ordered]

    html_out = _build_stream_html(sorted_years, player_data)
    with open(args.out, "w") as f:
        f.write(html_out)
    print(
        f"  Stream graph written: {args.out}  ({len(player_data)} players, min {min_ev} events)"
    )


# ── git / app development stats ───────────────────────────────────────────────


def cmd_gitlog(args):
    repo = args.repo
    fmt = "--pretty=format:%ad"
    date = "--date=format:%Y"
    after = "--after=2018-03-31"  # exclude pre-fork commits from upstream app
    log = subprocess.run(
        ["git", "-C", repo, "log", fmt, date, after], capture_output=True, text=True
    )
    if log.returncode != 0:
        print(f"  git log failed: {log.stderr.strip()}")
        return

    years_raw = [l.strip() for l in log.stdout.splitlines() if l.strip()]
    by_year = Counter(years_raw)
    total = len(years_raw)

    print(f"\n  App development — git log ({repo})")
    print(f"  Total commits: {total}")
    print()

    max_c = max(by_year.values(), default=1)
    bar_w = 36
    for y in sorted(by_year):
        c = by_year[y]
        bar = "█" * round(c / max_c * bar_w)
        print(f"  {y}  {bar:<{bar_w}} {c:>4}")

    # first and last commit summaries
    r = subprocess.run(
        ["git", "-C", repo, "log", "--oneline", "--reverse", after],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        lines = r.stdout.strip().splitlines()
        if lines:
            print(f"\n  First commit: {lines[0]}")
            print(f"  Last commit:  {lines[-1]}")

    # top changed files
    stat = subprocess.run(
        ["git", "-C", repo, "log", "--pretty=", "--name-only", after],
        capture_output=True,
        text=True,
    )
    if stat.returncode == 0:
        files = Counter(l.strip() for l in stat.stdout.splitlines() if l.strip())
        print("\n  Most-touched files:")
        for f, c in files.most_common(10):
            print(f"    {c:>5}×  {f}")


# ── dev activity heatmap ──────────────────────────────────────────────────────


def cmd_chart_dev(args):
    """GitHub-style commit heatmap: rows=years, cols=weeks, colour=count."""
    repo  = getattr(args, "repo", ".")
    after = "--after=2018-03-31"

    log = subprocess.run(
        ["git", "-C", repo, "log", "--pretty=format:%ad", "--date=format:%Y %W", after],
        capture_output=True, text=True,
    )
    if log.returncode != 0:
        print(f"git log failed: {log.stderr.strip()}")
        return

    counts: Counter = Counter(l.strip() for l in log.stdout.splitlines() if l.strip())
    max_c  = max(counts.values(), default=1)

    YEARS  = list(range(2018, 2027))
    WEEKS  = 52
    MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    # approximate week number for the 1st of each month (non-leap)
    MONTH_WEEK = [0, 4, 8, 13, 17, 21, 26, 30, 34, 39, 43, 47]

    def bucket_color(n):
        if n == 0:             return "#ede8e0"
        if n <= max_c * 0.12: return "#a8d8d3"
        if n <= max_c * 0.35: return "#2a9d8f"
        if n <= max_c * 0.65: return "#1a7a70"
        return "#0d5c54"

    BG, FG, MUTED = "#fafaf8", "#1a1a2e", "#888"
    CELL_W = 13
    CELL_H = 15
    GAP    = 1
    PAD_L  = 52
    PAD_R  = 20
    PAD_T  = 42
    PAD_B  = 52

    W = PAD_L + WEEKS * (CELL_W + GAP) + PAD_R
    H = PAD_T + len(YEARS) * CELL_H + PAD_B

    els = []

    # month labels along top (at approximate week positions)
    for mi, mw in enumerate(MONTH_WEEK):
        xc = PAD_L + mw * (CELL_W + GAP)
        els.append(f'<text x="{xc}" y="{PAD_T-10}" fill="{MUTED}" '
                   f'font-size="11" font-family="system-ui,sans-serif">{MONTH_NAMES[mi]}</text>')

    # rows
    for yi, y in enumerate(YEARS):
        yc = PAD_T + yi * CELL_H + CELL_H / 2
        els.append(f'<text x="{PAD_L-6}" y="{yc:.1f}" text-anchor="end" '
                   f'dominant-baseline="middle" fill="{MUTED}" font-size="11" '
                   f'font-family="system-ui,sans-serif">{y}</text>')
        for w in range(WEEKS):
            n   = counts.get(f"{y} {w:02d}", 0)
            col = bucket_color(n)
            rx  = PAD_L + w * (CELL_W + GAP)
            ry  = PAD_T + yi * CELL_H + 1
            tip = f"Week {w+1}, {y}: {n} commits"
            els.append(f'<rect x="{rx}" y="{ry}" width="{CELL_W}" height="{CELL_H-2}" '
                       f'fill="{col}" rx="2"><title>{tip}</title></rect>')

    # annotate busiest week
    top_yw, top_n = counts.most_common(1)[0]
    top_y_s, top_w_s = top_yw.split()
    top_yi = YEARS.index(int(top_y_s))
    top_wi = int(top_w_s)
    ann_x  = PAD_L + top_wi * (CELL_W + GAP) + CELL_W / 2
    ann_y  = PAD_T + top_yi * CELL_H - 5
    els.append(f'<text x="{ann_x:.1f}" y="{ann_y:.1f}" text-anchor="middle" fill="{FG}" '
               f'font-size="9" font-family="system-ui,sans-serif">▲ {top_n}</text>')

    # legend
    lx = PAD_L
    ly = H - 20
    els.append(f'<text x="{lx}" y="{ly+1}" fill="{MUTED}" font-size="10" '
               f'font-family="system-ui,sans-serif">Commits:</text>')
    boundaries = [int(max_c*0.12), int(max_c*0.35), int(max_c*0.65)]
    palette = ["#ede8e0", "#a8d8d3", "#2a9d8f", "#1a7a70", "#0d5c54"]
    labels  = ["0", f"1–{boundaries[0]}", f"{boundaries[0]+1}–{boundaries[1]}",
               f"{boundaries[1]+1}–{boundaries[2]}", f"{boundaries[2]+1}+"]
    for i, (col, lbl) in enumerate(zip(palette, labels)):
        rx = lx + 65 + i * 85
        els.append(f'<rect x="{rx}" y="{ly-8}" width="14" height="12" fill="{col}" rx="2"/>')
        els.append(f'<text x="{rx+18}" y="{ly+1}" fill="{MUTED}" font-size="10" '
                   f'font-family="system-ui,sans-serif">{lbl}</text>')

    svg = f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="{BG}"/>
  <text x="{W//2}" y="22" text-anchor="middle" fill="{FG}" font-size="15"
        font-family="system-ui,sans-serif" font-weight="700">Development activity — commits by week</text>
  {"".join(els)}
</svg>'''

    out = getattr(args, "out", "tiks-dev-chart.html")
    with open(out, "w") as f:
        f.write(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIKS development activity</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{BG};display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
svg{{max-width:{W}px;width:100%}}</style></head><body>{svg}</body></html>""")
    print(f"\n  Written → {out}  (total {sum(counts.values())} commits)")


# ── feature stats ─────────────────────────────────────────────────────────────


def cmd_features(args):
    db = connect(args)

    # ── Events ──
    events = list(
        db.event.find(
            {}, {"date": 1, "rsvps": 1, "_end_date": 1, "cancelled": 1, "name": 1}
        )
    )

    def duration_hours(e):
        start = e.get("date")
        end = e.get("_end_date")
        if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
            return (end - start).total_seconds() / 3600
        return None

    total_events = len(events)
    cancelled_ev = sum(1 for e in events if e.get("cancelled"))
    active_events = total_events - cancelled_ev
    multi_day = sum(
        1
        for e in events
        if isinstance(e.get("_end_date"), dt.datetime)
        and isinstance(e.get("date"), dt.datetime)
        and (e["_end_date"] - e["date"]).total_seconds() > 86400
    )
    practice_ev = sum(
        1
        for e in events
        if not e.get("cancelled")
        and (duration_hours(e) is None or duration_hours(e) <= 4)
    )

    # ── RSVPs ──
    total_rsvps = sum(len(e.get("rsvps") or []) for e in events)
    active_rsvps = sum(
        1
        for e in events
        for r in (e.get("rsvps") or [])
        if not r.get("cancelled") and not r.get("waitlisted")
    )
    cancelled_rsvps = sum(
        1 for e in events for r in (e.get("rsvps") or []) if r.get("cancelled")
    )

    # ── Users ──
    users = list(
        db.user.find(
            {}, {"dob": 1, "nick": 1, "name": 1, "gender": 1, "phone": 1, "roles": 1}
        )
    )
    total_users = len(users)
    with_birthday = sum(1 for u in users if u.get("dob"))
    with_phone = sum(1 for u in users if u.get("phone"))
    approved = sum(1 for u in users if ".approved-user" in (u.get("roles") or []))
    # birthday×year: years app ran birthday feature (Oct 2018 → 2026 = ~8 years)
    bday_years = 8
    birthday_celebrations = with_birthday * bday_years

    # ── Posts ──
    posts = list(
        db.post.find({}, {"public": 1, "draft": 1, "title": 1, "created_at": 1})
    )
    total_posts = len(posts)
    public_posts = sum(1 for p in posts if p.get("public"))
    draft_posts = sum(1 for p in posts if p.get("draft"))
    posts_by_year = Counter(p["created_at"].year for p in posts if p.get("created_at"))

    # ── Photos ──
    photos = db.g_drive_photo.count_documents({})

    # ── Bookmarks ──
    bookmarks = db.bookmark.count_documents({})

    # ── Interested users (people who asked for access) ──
    interested = db.interested_user.count_documents({})

    # ── Secret Santas ──
    santas = [
        e for e in events if re.search(r"secret.?santa", e.get("name") or "", re.I)
    ]
    santa_rsvps = sum(
        sum(
            1
            for r in (e.get("rsvps") or [])
            if not r.get("cancelled") and not r.get("waitlisted")
        )
        for e in santas
    )

    print("\n  ── Feature stats ──\n")
    print(f"  Events")
    print(f"    Total created          {total_events:>6}")
    print(f"    Active (ran)           {active_events:>6}")
    print(f"    Practice sessions (<4h){practice_ev:>6}")
    print(f"    Multi-day (tournaments){multi_day:>6}")
    print(f"    Cancelled              {cancelled_ev:>6}")
    print()
    print(f"  RSVPs")
    print(f"    Total RSVP actions     {total_rsvps:>6}")
    print(f"    Active (show-ups)      {active_rsvps:>6}")
    print(f"    Cancellations          {cancelled_rsvps:>6}")
    print()
    print(f"  Players")
    print(f"    Total registered       {total_users:>6}")
    print(f"    Approved members       {approved:>6}")
    print(f"    With birthday set      {with_birthday:>6}")
    print(f"    With phone set         {with_phone:>6}")
    print(
        f"    Birthday×year*         {birthday_celebrations:>6}  (* {with_birthday} people × {bday_years} years)"
    )
    print(f"    People who asked for access  {interested:>3}")
    print()
    print(f"  Posts")
    print(f"    Total posts            {total_posts:>6}")
    print(f"    Public                 {public_posts:>6}")
    print(f"    Drafts                 {draft_posts:>6}")
    for y in sorted(posts_by_year):
        print(f"      {y}                  {posts_by_year[y]:>6}")
    print()
    print(f"  Media")
    print(f"    Photos in GDrive sync  {photos:>6}")
    print()
    print(f"  Bookmarks               {bookmarks:>6}")
    print()
    print(f"  Secret Santas")
    print(f"    Events                 {len(santas):>6}")
    print(f"    Total participants     {santa_rsvps:>6}")


# ── stats ─────────────────────────────────────────────────────────────────────


def cmd_stats(args):
    db = connect(args)

    names = {}
    genders = Counter()
    role_counts = Counter()
    n_users = 0
    for u in db.user.find({}):
        n_users += 1
        names[u["_id"]] = u.get("nick") or u.get("name") or u["_id"]
        g = (u.get("gender") or "unspecified").lower()
        genders[g] += 1
        for r in u.get("roles") or []:
            role_counts[r] += 1

    events = list(db.event.find({}))
    n_events = len(events)
    event_dates = [e["date"] for e in events if isinstance(e.get("date"), dt.datetime)]
    first_event = min(event_dates) if event_dates else None
    last_event = max(event_dates) if event_dates else None

    total_rsvps = active = cancelled = waitlisted = 0
    per_user = Counter()
    events_by_year = Counter()
    creators = Counter()
    attendance = []
    member_years = defaultdict(set)  # uid -> set of years they played

    for e in events:
        eyr = yr(e.get("date"))
        events_by_year[eyr] += 1
        cid = ref_id(e.get("created_by"))
        if cid:
            creators[cid] += 1
        act = 0
        for r in e.get("rsvps") or []:
            total_rsvps += 1
            if r.get("cancelled"):
                cancelled += 1
                continue
            if r.get("waitlisted"):
                waitlisted += 1
                continue
            active += 1
            act += 1
            uid = ref_id(r.get("user"))
            if uid:
                per_user[uid] += 1
                if eyr:
                    member_years[uid].add(eyr)
        attendance.append((act, e.get("name", "(untitled)"), e.get("date")))

    # cohort data
    first_year_of = {uid: min(yrs) for uid, yrs in member_years.items()}
    new_by_year = Counter(first_year_of.values())
    players_by_year = defaultdict(set)
    for uid, yrs in member_years.items():
        for y in yrs:
            players_by_year[y].add(uid)
    all_years = sorted(players_by_year)
    founding_year = all_years[0] if all_years else None
    founders = {
        uid
        for uid, yrs in member_years.items()
        if founding_year and founding_year in yrs
    }

    n_photos = db.g_drive_photo.estimated_document_count()
    n_posts = db.post.count_documents({})
    n_interested = db.interested_user.count_documents({})

    years_running = ""
    if first_event and last_event:
        years_running = f"{(last_event - first_event).days / 365.25:.1f}"

    approved = role_counts.get(".approved-user", 0)
    admins = role_counts.get("admin", 0)
    avg_att = active / n_events if n_events else 0
    cancel_rate = cancelled / total_rsvps * 100 if total_rsvps else 0

    top_members = [(names.get(u, u), c) for u, c in per_user.most_common(args.top)]
    top_creators = [(names.get(u, u), c) for u, c in creators.most_common(5)]
    best_events = sorted(attendance, key=lambda x: x[0], reverse=True)[: args.top]

    section("TIKS ULTIMATE — RSVP APP RETROSPECTIVE")
    if first_event:
        print(f"  {first_event:%b %Y} – {last_event:%b %Y}   ({years_running} years)\n")

    def line(label, val):
        print(f"  {label:32s} {val}")

    line("Members", n_users)
    line("  approved", approved)
    line("  admins", admins)
    line("Events held", n_events)
    line("Total RSVPs (all-time)", total_rsvps)
    line("  showed up (active)", active)
    line("  waitlisted", waitlisted)
    line("  cancelled", f"{cancelled}  ({cancel_rate:.0f}%)")
    line("Avg attendance / event", f"{avg_att:.1f}")
    line("Photos", n_photos)
    line("Posts", n_posts)
    line("Folks who showed interest", n_interested)

    print("\n  Events per year:")
    max_y = max(events_by_year.values())
    for y in sorted(k for k in events_by_year if k):
        print(f"    {y}  {bar(events_by_year[y], max_y, 30)} {events_by_year[y]}")

    print(f"\n  Most active members (by active RSVPs):")
    for i, (nm, c) in enumerate(top_members, 1):
        print(f"    {i:2d}. {nm:24s} {c}")

    print(f"\n  Best-attended events:")
    for c, nm, d in best_events:
        ds = f"{d:%b %Y}" if isinstance(d, dt.datetime) else ""
        print(f"    {c:4d}  {nm}  {ds}")

    print(f"\n  Top event organisers:")
    for nm, c in top_creators:
        print(f"    {nm:24s} {c} events")

    # HTML card
    esc = html_lib.escape

    sorted_years = sorted(k for k in events_by_year if k)

    chart_events = _svg_bars(
        [str(y) for y in sorted_years],
        [events_by_year[y] for y in sorted_years],
    )

    # stacked bar: new vs returning players per year
    prev = set()
    new_vals, ret_vals = [], []
    for y in all_years:
        curr = players_by_year[y]
        new_vals.append(new_by_year.get(y, 0))
        ret_vals.append(len(curr & prev))
        prev = curr
    chart_composition = _svg_stacked_bars(
        [str(y) for y in all_years],
        [("Returning", ret_vals), ("New", new_vals)],
        colors=["#4f86c6", _ACCENT],
    )

    cohort_years = all_years
    cohort_counts = [len(founders & players_by_year[y]) for y in cohort_years]
    cohort_pcts = [
        round(c / len(founders) * 100) if founders else 0 for c in cohort_counts
    ]
    chart_cohort = _svg_line(
        [str(y) for y in cohort_years],
        cohort_pcts,
        value_fmt=lambda v: f"{v}%",
    )

    chart_members = _svg_hbars(
        [nm for nm, _ in top_members],
        [c for _, c in top_members],
    )

    # player × year heatmap (top players by total RSVPs)
    rsvps_by_uid_year = defaultdict(lambda: defaultdict(int))
    for e in events:
        eyr = yr(e.get("date"))
        if not eyr:
            continue
        for r in e.get("rsvps") or []:
            if r.get("cancelled") or r.get("waitlisted"):
                continue
            uid = ref_id(r.get("user"))
            if uid:
                rsvps_by_uid_year[uid][eyr] += 1
    heatmap_players = [uid for uid, _ in per_user.most_common(15)]
    heatmap_matrix = [
        [rsvps_by_uid_year[uid].get(y, 0) for y in sorted_years]
        for uid in heatmap_players
    ]
    heatmap_labels = [names.get(uid, uid) for uid in heatmap_players]
    chart_heatmap = _svg_heatmap(
        heatmap_labels, [str(y) for y in sorted_years], heatmap_matrix
    )

    # stream graph: top N players by total games, show their year-by-year flow
    stream_n = args.bump_top  # reuse same arg
    top_stream_uids = [
        uid
        for uid, _ in sorted(
            rsvps_by_uid_year.items(), key=lambda kv: sum(kv[1].values()), reverse=True
        )
    ][:stream_n]
    # interleave: biggest in middle (odd index = inner, even = outer)
    ordered_uids = []
    inner = [u for i, u in enumerate(top_stream_uids) if i % 2 == 0]
    outer = [u for i, u in enumerate(top_stream_uids) if i % 2 == 1]
    for u in outer:
        ordered_uids.append(u)
    for u in reversed(inner):
        ordered_uids.append(u)
    stream_data = [
        (names.get(uid, uid), dict(rsvps_by_uid_year[uid])) for uid in ordered_uids
    ]
    chart_bump = _svg_stream(sorted_years, stream_data)

    # pictogram
    chart_pictogram = _svg_pictogram(active, unit=100)

    member_rows = "".join(
        f"<li><span>{esc(nm)}</span><b>{c}</b></li>" for nm, c in top_members
    )
    event_rows = "".join(
        f"<li><span>{esc(nm)}</span><b>{c}</b></li>" for c, nm, _ in best_events
    )
    span = f"{first_event:%B %Y} – {last_event:%B %Y}" if first_event else ""

    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TIKS Ultimate — RSVP Retrospective</title>
<style>
  :root {{ --ink:#1a1a2e; --accent:#e94560; --muted:#6b7280; --card:#fff; --bg:#f4f4f8; }}
  * {{ box-sizing:border-box; }}
  body {{ font:16px/1.5 system-ui,sans-serif; background:var(--bg); color:var(--ink);
         margin:0; padding:2rem 1rem; }}
  .wrap {{ max-width:780px; margin:0 auto; }}
  h1 {{ font-size:1.8rem; margin:0; }}
  .sub {{ color:var(--muted); margin:.2rem 0 1.5rem; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
           gap:1rem; margin-bottom:1.5rem; }}
  .stat {{ background:var(--card); border-radius:14px; padding:1.1rem 1.2rem;
           box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .stat .n {{ font-size:1.9rem; font-weight:700; color:var(--accent); }}
  .stat .l {{ color:var(--muted); font-size:.85rem; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; }}
  @media(max-width:560px){{ .cols{{grid-template-columns:1fr}} }}
  .panel {{ background:var(--card); border-radius:14px; padding:1.2rem 1.4rem;
            box-shadow:0 1px 3px rgba(0,0,0,.08); margin-top:1rem; }}
  .panel h3 {{ margin:0 0 .8rem; font-size:1rem; color:var(--ink); }}
  .panel .note {{ color:var(--muted); font-size:.8rem; margin-top:.4rem; }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ display:flex; justify-content:space-between; padding:.25rem 0;
        border-bottom:1px solid #eee; font-size:.9rem; }}
  li b {{ color:var(--accent); }}
  footer {{ color:var(--muted); font-size:.8rem; text-align:center; margin-top:2rem; }}
</style></head><body><div class="wrap">
  <h1>TIKS Ultimate — by the numbers</h1>
  <p class="sub">{esc(span)} &middot; {years_running} years of frisbee</p>

  <div class="grid">
    <div class="stat"><div class="n">{n_users}</div><div class="l">members</div></div>
    <div class="stat"><div class="n">{n_events}</div><div class="l">events held</div></div>
    <div class="stat"><div class="n">{active:,}</div><div class="l">times someone showed up</div></div>
    <div class="stat"><div class="n">{avg_att:.1f}</div><div class="l">avg per event</div></div>
    <div class="stat"><div class="n">{n_photos:,}</div><div class="l">photos</div></div>
    <div class="stat"><div class="n">{n_posts}</div><div class="l">posts written</div></div>
  </div>

  <div class="panel">
    <h3>Events per year</h3>
    {chart_events}
  </div>

  <div class="panel">
    <h3>New vs returning players per year</h3>
    {chart_composition}
    <p class="note">Blue = players who'd played before. Red = first time ever.</p>
  </div>

  <div class="panel">
    <h3>Early players still showing up</h3>
    {chart_cohort}
    <p class="note">Of the {len(founders)} people who played in {founding_year}, what % were still active each year.</p>
  </div>

  <div class="panel">
    <h3>17,149 times someone showed up</h3>
    {chart_pictogram}
  </div>

  <div class="panel">
    <h3>Who was showing up — year by year</h3>
    {chart_bump}
    <p class="note">Top {stream_n} players by total games. Band width = games attended that year.</p>
  </div>

  <div class="panel">
    <h3>Most active members — year by year</h3>
    {chart_heatmap}
    <p class="note">Active RSVPs per year for the top 15 all-time members. Darker = more games.</p>
  </div>

  <div class="panel">
    <h3>Most active members — all time</h3>
    {chart_members}
    <p class="note">Total active RSVPs across all {years_running} years.</p>
  </div>

  <div class="cols">
    <div class="panel"><h3>Best-attended events</h3><ul>{event_rows}</ul></div>
    <div class="panel"><h3>Most active members</h3><ul>{member_rows}</ul></div>
  </div>

  <footer>Generated from the RSVP app data &middot; {dt.date.today():%B %Y}</footer>
</div></body></html>"""

    with open(args.out, "w") as f:
        f.write(html_doc)
    print(f"\n  HTML card written: {args.out}\n")


# ── wa ────────────────────────────────────────────────────────────────────────


def cmd_wa(args):
    db = connect(args)
    lps = args.lines_per_screen
    hdr = args.header_lines

    total_messages = total_name_lines = total_header_lines = events_with_rsvps = 0

    for e in db.event.find({}, {"rsvps": 1}):
        rsvps = e.get("rsvps") or []
        active = waitlisted = cancelled = 0
        for r in rsvps:
            if r.get("cancelled"):
                cancelled += 1
            elif r.get("waitlisted"):
                waitlisted += 1
            else:
                active += 1

        n = active + waitlisted + cancelled
        c = cancelled
        if n == 0:
            continue
        events_with_rsvps += 1

        callin_msgs = n
        callin_name_lines = n * (n + 1) // 2
        callout_msgs = c
        callout_name_lines = c * (2 * n - c + 1) // 2 if c > 0 else 0

        msgs = callin_msgs + callout_msgs
        total_messages += msgs
        total_name_lines += callin_name_lines + callout_name_lines
        total_header_lines += msgs * hdr

    total_lines = total_name_lines + total_header_lines
    total_screens = total_lines / lps
    novels = total_lines / 370_000

    def fmt(n):
        return f"{n:,.0f}"

    section("TIKS ULTIMATE — WhatsApp scrolling avoided")
    print(f"  Model: {hdr} header line(s) per message, {lps} lines per screen\n")
    print(f"  Events with RSVPs          {fmt(events_with_rsvps):>12}")
    print(f"  WA messages avoided        {fmt(total_messages):>12}")
    print(f"    name-list lines          {fmt(total_name_lines):>12}")
    print(f"    header lines             {fmt(total_header_lines):>12}")
    print(f"  Total lines avoided        {fmt(total_lines):>12}")
    print(f"  Phone screens of scrolling {fmt(total_screens):>12}")
    print(f"  Equivalent novels          {novels:>12.1f}")
    print(f"\n  (assumes call-outs happen after all call-ins)")


# ── wordcount ─────────────────────────────────────────────────────────────────


def cmd_wordcount(args):
    """
    WA word-count model (call-ins only, active RSVPs only).

    For an event with N active RSVPs:
      Call-ins: N messages. Message k lists k names → name-lines = 1+2+…+N = N*(N+1)/2

    Words: each name-line is one person's name. We look up actual nick/name word counts.
    """
    db = connect(args)

    users = {str(u["_id"]): u for u in db.user.find({}, {"nick": 1, "name": 1})}

    def word_count(uid):
        u = users.get(str(uid), {})
        nm = u.get("nick") or u.get("name") or ""
        return len(nm.split()) if nm.strip() else 2

    total_msgs = 0
    total_name_lines = 0
    total_name_words = 0

    events = list(
        db.event.find({"rsvps.0": {"$exists": True}}, {"rsvps": 1, "name": 1})
    )

    for e in events:
        rsvps = e.get("rsvps") or []
        active_rsvps = [
            r for r in rsvps if not r.get("cancelled") and not r.get("waitlisted")
        ]
        n = len(active_rsvps)
        if n == 0:
            continue

        name_lines = n * (n + 1) // 2
        words_per_name = [word_count(ref_id(r.get("user"))) for r in active_rsvps]
        avg_wpn = sum(words_per_name) / len(words_per_name) if words_per_name else 2

        total_msgs += n
        total_name_lines += name_lines
        total_name_words += name_lines * avg_wpn

    NOVEL = 90_000
    LINES_PER_SCREEN = 35
    print(f"\n  ── WA word count (call-ins only) ──\n")
    print(f"  Total messages avoided   {total_msgs:>10,}")
    print(
        f"  Total name-line slots    {total_name_lines:>10,}  (cumulative list entries)"
    )
    print(
        f"  Screens of scrolling     {total_name_lines/LINES_PER_SCREEN:>10,.0f}  (@ {LINES_PER_SCREEN} lines/screen)"
    )
    print(
        f"  Total name-words         {total_name_words:>10,.0f}  (avg words/nick × line slots)"
    )
    print(
        f"  Equivalent novels        {total_name_words/NOVEL:>10.1f}  (@ {NOVEL:,} words/novel)"
    )
    print(f"\n  ── Worked example ──")
    print(f"  Event with 10 active RSVPs (N=10):")
    n = 10
    nl = n * (n + 1) // 2
    print(f"    Call-in name-lines  : {n}*({n}+1)/2 = {nl}")
    print(f"    Messages            : {n}")
    print(f"    If avg nick = 1 word: {nl} words for this event")


# ── dow ───────────────────────────────────────────────────────────────────────


def cmd_dow(args):
    db = connect(args)
    max_delta = dt.timedelta(hours=args.max_hours)

    events_by_dow = defaultdict(int)
    events_by_year_dow = defaultdict(lambda: defaultdict(int))
    skipped = 0

    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "_end_date": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        end = e.get("_end_date")
        if isinstance(end, dt.datetime) and (end - start) > max_delta:
            skipped += 1
            continue
        dow = start.weekday()
        year = start.year
        events_by_dow[dow] += 1
        events_by_year_dow[year][dow] += 1

    years = sorted(events_by_year_dow)
    max_e = max(events_by_dow.values(), default=1)

    section("TIKS ULTIMATE — practice sessions by day of week")
    print(f"  (excluding events longer than {args.max_hours}h; {skipped} skipped)\n")
    print(f"  {'Day':<5}  {'Total':>6}  bar")
    print(f"  {'-'*4}  {'-'*6}  {'-'*30}")
    for i, day in enumerate(DAYS):
        n = events_by_dow[i]
        print(f"  {day:<5}  {n:>6}  {bar(n, max_e, 30)}")

    all_counts = [events_by_year_dow[y][d] for y in years for d in range(7)]
    max_cell = max(all_counts, default=1)

    def shade(n):
        if n == 0:
            return "  —  "
        frac = n / max_cell
        block = (
            "░"
            if frac < 0.25
            else ("▒" if frac < 0.5 else ("▓" if frac < 0.75 else "█"))
        )
        return f"{block}{n:>3} "

    col_w = 5
    print(f"\n  Year-by-year breakdown\n")
    print(f"  {'':5}" + "".join(f"{d:>{col_w}}" for d in DAYS))
    print("  " + "-" * (5 + col_w * 7))
    for y in years:
        print(f"  {y:<5}" + "".join(shade(events_by_year_dow[y][d]) for d in range(7)))


# ── circular DOW chart ────────────────────────────────────────────────────────


def cmd_chart_dow(args):
    db = connect(args)

    by_year_dow = defaultdict(lambda: defaultdict(int))
    for e in db.event.find(
        {"date": {"$exists": True}, "cancelled": {"$ne": True}}, {"date": 1}
    ):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        by_year_dow[start.year][start.weekday()] += 1

    years = sorted(by_year_dow.keys())
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    BG, FG, MUTED = "#fafaf8", "#1a1a2e", "#888888"

    def heat_color(frac):
        if frac < 0.001:
            return "#e8e3de"  # empty cell: warm gray
        light = (242, 224, 200)  # cream
        dark = (176, 30, 45)  # deep crimson
        r = int(light[0] + (dark[0] - light[0]) * frac)
        g = int(light[1] + (dark[1] - light[1]) * frac)
        b = int(light[2] + (dark[2] - light[2]) * frac)
        return f"#{r:02x}{g:02x}{b:02x}"

    W, H = 640, 700
    CX, CY = W // 2, H // 2
    MAX_R = 238
    MIN_R = 52
    n_y = len(years)
    ring_w = (MAX_R - MIN_R) / n_y
    GAP_DEG = 2.5
    SEG = 360 / 7

    def arc_path(r1, r2, a1d, a2d):
        a1, a2 = math.radians(a1d), math.radians(a2d)
        large = 1 if abs(a2d - a1d) > 180 else 0

        def pt(r, a):
            return f"{CX + r*math.cos(a):.2f},{CY + r*math.sin(a):.2f}"

        return (
            f"M {pt(r2,a1)} A {r2:.2f},{r2:.2f} 0 {large} 1 {pt(r2,a2)} "
            f"L {pt(r1,a2)} A {r1:.2f},{r1:.2f} 0 {large} 0 {pt(r1,a1)} Z"
        )

    els = []

    # outer background disk
    els.append(f'<circle cx="{CX}" cy="{CY}" r="{MAX_R+2}" fill="#e0dbd4"/>')

    # heatmap: one ring per year, colour = fraction of that year's peak
    for yi, y in enumerate(years):
        r1 = MIN_R + yi * ring_w + 0.8
        r2 = MIN_R + (yi + 1) * ring_w - 0.8
        yr_counts = [by_year_dow[y][d] for d in range(7)]
        yr_max = max(yr_counts) if any(yr_counts) else 1
        for d in range(7):
            a1 = d * SEG - 90 + GAP_DEG
            a2 = (d + 1) * SEG - 90 - GAP_DEG
            cnt = by_year_dow[y][d]
            col = heat_color(cnt / yr_max)
            tip = f"{day_names[d]} {y}: {cnt}"
            els.append(
                f'<path d="{arc_path(r1, r2, a1, a2)}" fill="{col}">'
                f"<title>{tip}</title></path>"
            )

    # center hole
    els.append(f'<circle cx="{CX}" cy="{CY}" r="{MIN_R - 1}" fill="{BG}"/>')

    # year labels inside the Mon segment (low activity → light cells → readable)
    # Mon midpoint: -90 + SEG/2 ≈ -64°; shift a few degrees toward the gap for breathing room
    ANN_ANG = math.radians(-90 + GAP_DEG + 8)
    for yi, y in enumerate(years):
        r_mid = MIN_R + yi * ring_w + ring_w / 2
        lx = CX + r_mid * math.cos(ANN_ANG)
        ly = CY + r_mid * math.sin(ANN_ANG)
        els.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{FG}" font-size="8.5" '
            f'font-family="system-ui,sans-serif" opacity="0.65">{y}</text>'
        )

    # day labels outside
    LABEL_R = MAX_R + 30
    day_totals = [sum(by_year_dow[y][d] for y in years) for d in range(7)]
    for d in range(7):
        mid = math.radians(d * SEG - 90 + SEG / 2)
        lx = CX + LABEL_R * math.cos(mid)
        ly = CY + LABEL_R * math.sin(mid)
        els.append(
            f'<text x="{lx:.1f}" y="{ly-7:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{FG}" font-size="13" '
            f'font-family="system-ui,sans-serif" font-weight="600">{day_names[d]}</text>'
        )
        els.append(
            f'<text x="{lx:.1f}" y="{ly+9:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{MUTED}" font-size="10" '
            f'font-family="system-ui,sans-serif">{day_totals[d]}</text>'
        )

    total = sum(day_totals)
    caption = "Each ring = one year (2018 inner → 2026 outer). Shade = share of that year's peak."
    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="{BG}" rx="14"/>
  <text x="{CX}" y="38" text-anchor="middle" fill="{FG}" font-size="21"
        font-family="system-ui,sans-serif" font-weight="700">When did we play?</text>
  <text x="{CX}" y="60" text-anchor="middle" fill="{MUTED}" font-size="12"
        font-family="system-ui,sans-serif">{total:,} events · 2018–2026 · TIKS</text>
  {"".join(els)}
  <text x="{CX}" y="{H-18}" text-anchor="middle" fill="{MUTED}" font-size="10"
        font-family="system-ui,sans-serif">{caption}</text>
</svg>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>When did we play? – TIKS</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:{BG};display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
  svg{{max-width:640px;width:100%}}
</style>
</head>
<body>{svg}</body>
</html>"""

    out = getattr(args, "out", "tiks-dow-chart.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"\n  Written → {out}")
    for d, name in enumerate(day_names):
        print(f"    {name}: {day_totals[d]:>4}")


# ── evolution tick chart ──────────────────────────────────────────────────────


def cmd_chart_evo(args):
    """Evolution-style tick chart: rows=day-of-week, x=date, ticks=events."""
    db = connect(args)

    events = []
    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "cancelled": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        events.append(
            {
                "date": start.date(),
                "dow": start.weekday(),
                "cancelled": bool(e.get("cancelled")),
            }
        )

    if not events:
        print("No events found.")
        return

    DOW_COLOR = {
        0: "#f4845f",  # Mon  – coral
        1: "#2a9d8f",  # Tue  – teal      (dominant)
        2: "#e9c46a",  # Wed  – amber
        3: "#e76f51",  # Thu  – orange     (dominant)
        4: "#a8c5da",  # Fri  – steel blue
        5: "#6a4c93",  # Sat  – purple     (dominant)
        6: "#8ecae6",  # Sun  – sky blue
    }
    DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    CANCELLED = "#2d2d2d"
    BG, FG, MUTED = "#fafaf8", "#1a1a2e", "#888"

    date_min = dt.date(2018, 4, 1)
    date_max = dt.date(2026, 7, 1)
    total_days = (date_max - date_min).days

    # layout
    PAD_L, PAD_R = 52, 20
    PAD_T, PAD_B = 60, 50
    ROW_H = 34
    TICK_H = 22
    TICK_W = 1.6
    W = PAD_L + 860 + PAD_R
    H = PAD_T + 7 * ROW_H + PAD_B

    def x_for(d):
        return PAD_L + (d - date_min).days / total_days * 860

    els = []

    # row backgrounds (alternating)
    for dow in range(7):
        y_top = PAD_T + dow * ROW_H
        fill = "#f0ece7" if dow % 2 == 0 else "#f8f5f1"
        els.append(
            f'<rect x="{PAD_L}" y="{y_top}" width="860" height="{ROW_H}" fill="{fill}"/>'
        )

    # year dividers + labels
    for y in range(2018, 2027):
        d = dt.date(y, 1, 1)
        if d < date_min:
            continue
        xv = x_for(d)
        els.append(
            f'<line x1="{xv:.1f}" y1="{PAD_T}" x2="{xv:.1f}" '
            f'y2="{PAD_T + 7*ROW_H}" stroke="#d8d3cc" stroke-width="1" stroke-dasharray="4,3"/>'
        )
        els.append(
            f'<text x="{xv+3:.1f}" y="{PAD_T - 8}" fill="{MUTED}" font-size="11" '
            f'font-family="system-ui,sans-serif">{y}</text>'
        )

    # ticks
    for ev in events:
        if ev["date"] < date_min or ev["date"] > date_max:
            continue
        xv = x_for(ev["date"])
        dow = ev["dow"]
        y_center = PAD_T + dow * ROW_H + ROW_H / 2
        col = CANCELLED if ev["cancelled"] else DOW_COLOR[dow]
        els.append(
            f'<rect x="{xv:.1f}" y="{y_center - TICK_H/2:.1f}" '
            f'width="{TICK_W}" height="{TICK_H}" fill="{col}" opacity="0.85"/>'
        )

    # row labels
    for dow in range(7):
        y_center = PAD_T + dow * ROW_H + ROW_H / 2
        col = DOW_COLOR[dow]
        els.append(
            f'<text x="{PAD_L - 6}" y="{y_center:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" fill="{col}" font-size="12" '
            f'font-weight="700" font-family="system-ui,sans-serif">{DOW_NAMES[dow]}</text>'
        )

    # month tick marks at top
    for year in range(2018, 2027):
        for month in range(1, 13):
            try:
                d = dt.date(year, month, 1)
            except ValueError:
                continue
            if d < date_min or d > date_max:
                continue
            xv = x_for(d)
            els.append(
                f'<line x1="{xv:.1f}" y1="{PAD_T - 4}" x2="{xv:.1f}" '
                f'y2="{PAD_T}" stroke="#ccc" stroke-width="0.8"/>'
            )

    # border
    els.append(
        f'<rect x="{PAD_L}" y="{PAD_T}" width="860" height="{7*ROW_H}" '
        f'fill="none" stroke="#d0cbc4" stroke-width="1"/>'
    )

    # caption
    els.append(
        f'<text x="{PAD_L}" y="{H - 14}" fill="{MUTED}" font-size="10" '
        f'font-family="system-ui,sans-serif">Dark ticks = cancelled events</text>'
    )

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="{BG}"/>
  <text x="{W//2}" y="22" text-anchor="middle" fill="{FG}" font-size="17"
        font-family="system-ui,sans-serif" font-weight="700">When did we play? — 2018 to 2026</text>
  {"".join(els)}
</svg>"""

    out = getattr(args, "out", "tiks-evo-chart.html")
    with open(out, "w") as f:
        f.write(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIKS evolution chart</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{BG};display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
svg{{max-width:{W}px;width:100%}}</style></head><body>{svg}</body></html>""")
    print(f"\n  Written → {out}  ({len(events)} events)")


# ── player timeline chart ─────────────────────────────────────────────────────


def cmd_chart_players(args):
    """Horizontal timeline chart: activity periods per player, gaps = absences."""
    from collections import defaultdict

    db = connect(args)
    min_events = getattr(args, "min_events", 30)
    gap_thresh = getattr(args, "gap", 30)  # events of absence → inactive period

    users = {
        str(u["_id"]): u for u in db.user.find({}, {"nick": 1, "name": 1, "email": 1})
    }

    # load email→uid index; some users have email-like _id with no email field
    email_to_uid: dict[str, str] = {}
    for uid, u in users.items():
        if u.get("email"):
            email_to_uid[u["email"].lower()] = uid
        if "@" in uid:  # _id is itself an email string
            email_to_uid[uid.lower()] = uid

    # build uid→canonical from user-merges.json (gitignored)
    merges_path = os.path.join(os.path.dirname(__file__), "user-merges.json")
    uid_to_canonical: dict[str, str] = {}
    if os.path.exists(merges_path):
        with open(merges_path) as f:
            merges = json.load(f)
        for emails in merges.values():
            uids = [
                email_to_uid[e.lower()] for e in emails if e.lower() in email_to_uid
            ]
            if uids:
                canonical = sorted(uids)[0]
                for uid in uids:
                    uid_to_canonical[uid] = canonical

    # for users not in merges, map to themselves (unless unknown)
    for uid, u in users.items():
        if uid in uid_to_canonical:
            continue
        nick_raw = (u.get("nick") or u.get("name") or "").strip()
        if not nick_raw or nick_raw.lower() == "unknown user":
            continue
        uid_to_canonical[uid] = uid

    def label(uid):
        u = users.get(uid, {})
        nm = u.get("nick") or u.get("name") or "?"
        nm = nm.split()[0][:15]
        return nm.capitalize() if nm and nm[0].upper() != nm[0] else nm

    # collect all non-cancelled events sorted by date, with attendee sets
    raw_events = []
    for e in db.event.find(
        {"cancelled": {"$ne": True}, "date": {"$exists": True}}, {"rsvps": 1, "date": 1}
    ):
        edate = e.get("date")
        if not isinstance(edate, dt.datetime):
            continue
        attendees = set()
        for r in e.get("rsvps", []):
            if r.get("cancelled"):
                continue
            uid = str(ref_id(r.get("user")))
            canonical = uid_to_canonical.get(uid)
            if canonical:
                attendees.add(canonical)
        raw_events.append((edate.date(), attendees))
    raw_events.sort(key=lambda x: x[0])

    # for each player: list of global event indices they attended
    player_event_idx: dict[str, list[int]] = defaultdict(list)
    for idx, (_, attendees) in enumerate(raw_events):
        for uid in attendees:
            player_event_idx[uid].append(idx)

    # compute active periods: consecutive attended events with gap ≤ gap_thresh
    def active_periods(idx_list: list[int]) -> list[tuple]:
        """Return list of (start_date, end_date) active periods."""
        if not idx_list:
            return []
        periods = []
        seg_start = idx_list[0]
        seg_end = idx_list[0]
        for i in range(1, len(idx_list)):
            if idx_list[i] - idx_list[i - 1] > gap_thresh:
                periods.append((raw_events[seg_start][0], raw_events[seg_end][0]))
                seg_start = idx_list[i]
            seg_end = idx_list[i]
        periods.append((raw_events[seg_start][0], raw_events[seg_end][0]))
        return periods

    # build player records: (uid, periods, total_count)
    total_events = len(raw_events)
    last_50_start = total_events - gap_thresh  # still-active window

    all_players = []
    for uid, idx_list in player_event_idx.items():
        count = len(idx_list)
        if count < min_events:
            continue
        periods = active_periods(idx_list)
        all_players.append((uid, periods, count, idx_list[-1]))

    # sort alphabetically by display name
    all_players.sort(key=lambda x: label(x[0]).lower())

    BG, FG, MUTED = "#fafaf8", "#1a1a2e", "#888"
    ACTIVE_COL = "#2a9d8f"
    INACTIVE_COL = "#c0b8b0"
    ARROW_COL = "#2a9d8f"

    date_min = dt.date(2018, 4, 1)
    date_max = dt.date(2026, 8, 1)
    total_days = (date_max - date_min).days

    ROW_H = 11
    PAD_L = 75
    PAD_R = 30
    PAD_T = 48
    PAD_B = 36
    CHART_W = 720
    W = PAD_L + CHART_W + PAD_R
    H = PAD_T + len(all_players) * ROW_H + PAD_B

    def xv(d):
        return PAD_L + (d - date_min).days / total_days * CHART_W

    els = []

    # year dividers
    for y in range(2018, 2027):
        d = dt.date(y, 1, 1)
        if d < date_min:
            continue
        x = xv(d)
        els.append(
            f'<line x1="{x:.1f}" y1="{PAD_T-14}" x2="{x:.1f}" '
            f'y2="{PAD_T + len(all_players)*ROW_H}" stroke="#ddd" stroke-width="0.8"/>'
        )
        els.append(
            f'<text x="{x+2:.1f}" y="{PAD_T-4}" fill="{MUTED}" font-size="10" '
            f'font-family="system-ui,sans-serif">{y}</text>'
        )

    # bars
    for i, (uid, periods, count, last_idx) in enumerate(all_players):
        y_c = PAD_T + i * ROW_H + ROW_H / 2
        still = last_idx >= last_50_start
        col = ACTIVE_COL if still else INACTIVE_COL

        first_date = periods[0][0]
        last_date = periods[-1][1]
        tip = f"{label(uid)} · {count} events · {first_date} → {last_date}"

        for seg_start, seg_end in periods:
            x1 = xv(seg_start)
            x2 = xv(seg_end)
            bar_w = max(x2 - x1, 2)
            els.append(
                f'<rect x="{x1:.1f}" y="{y_c-1:.1f}" width="{bar_w:.1f}" height="2" '
                f'fill="{col}" opacity="0.9"><title>{tip}</title></rect>'
            )

        # arrow for still-active players
        if still:
            ax = xv(last_date) + 2
            els.append(
                f'<polygon points="{ax:.1f},{y_c-2} {ax+4:.1f},{y_c} {ax:.1f},{y_c+2}" '
                f'fill="{ARROW_COL}" opacity="0.9"/>'
            )

        els.append(
            f'<text x="{PAD_L-5}" y="{y_c:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" fill="{FG if still else MUTED}" font-size="8.5" '
            f'font-family="system-ui,sans-serif">{label(uid)}</text>'
        )

    # legend
    lx = PAD_L
    ly = H - 18
    els.append(f'<rect x="{lx}" y="{ly-1}" width="16" height="2" fill="{ACTIVE_COL}"/>')
    els.append(
        f'<polygon points="{lx+18},{ly-2} {lx+22},{ly} {lx+18},{ly+2}" fill="{ACTIVE_COL}"/>'
    )
    els.append(
        f'<text x="{lx+27}" y="{ly+1}" fill="{MUTED}" font-size="10" '
        f'font-family="system-ui,sans-serif">Active (attended &gt;1 session in last {gap_thresh})</text>'
    )
    els.append(
        f'<rect x="{lx+280}" y="{ly-1}" width="16" height="2" fill="{INACTIVE_COL}"/>'
    )
    els.append(
        f'<text x="{lx+301}" y="{ly+1}" fill="{MUTED}" font-size="10" '
        f'font-family="system-ui,sans-serif">Not active</text>'
    )
    els.append(
        f'<text x="{W-PAD_R}" y="{ly+1}" text-anchor="end" fill="{MUTED}" font-size="10" '
        f'font-family="system-ui,sans-serif">{min_events}+ events · {len(all_players)} players</text>'
    )

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="{BG}"/>
  <text x="{W//2}" y="22" text-anchor="middle" fill="{FG}" font-size="15"
        font-family="system-ui,sans-serif" font-weight="700">Player timelines — {min_events}+ events</text>
  {"".join(els)}
</svg>"""

    out = getattr(args, "out", "tiks-players-chart.html")
    with open(out, "w") as f:
        f.write(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIKS player timelines</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{BG};display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
svg{{max-width:{W}px;width:100%}}</style></head><body>{svg}</body></html>""")
    print(f"\n  Written → {out}  ({len(all_players)} players, gap={gap_thresh})")


# ── circular calendar chart ────────────────────────────────────────────────────


def cmd_chart_cal(args):
    """Circular calendar: one cell per day, ring per year, colour = day-of-week."""
    db = connect(args)

    active_dates = set()
    cancelled_dates = set()
    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "cancelled": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        d = start.date()
        if e.get("cancelled"):
            cancelled_dates.add(d)
        else:
            active_dates.add(d)

    # day-of-week colours  (Mon=0 … Sun=6)
    DOW_COLOR = {
        0: "#b0b8b0",  # Mon  – muted green-gray
        1: "#2a9d8f",  # Tue  – teal
        2: "#b0b8b0",  # Wed  – muted
        3: "#e76f51",  # Thu  – orange
        4: "#b0b8b0",  # Fri  – muted
        5: "#6a4c93",  # Sat  – purple
        6: "#b0b8b0",  # Sun  – muted
    }
    CANCELLED = "#1a1a2e"
    EMPTY = "#ede8e2"
    BG, FG, MUTED = "#fafaf8", "#1a1a2e", "#888"

    years = list(range(2018, 2027))
    W, H = 680, 740
    CX, CY = W // 2, H // 2 - 10
    MAX_R = 268
    MIN_R = 54
    ring_w = (MAX_R - MIN_R) / len(years)

    def arc(r1, r2, a1d, a2d):
        a1, a2 = math.radians(a1d), math.radians(a2d)
        lg = 1 if abs(a2d - a1d) > 180 else 0

        def p(r, a):
            return f"{CX+r*math.cos(a):.2f},{CY+r*math.sin(a):.2f}"

        return (
            f"M {p(r2,a1)} A {r2:.2f},{r2:.2f} 0 {lg} 1 {p(r2,a2)} "
            f"L {p(r1,a2)} A {r1:.2f},{r1:.2f} 0 {lg} 0 {p(r1,a1)} Z"
        )

    els = []
    els.append(f'<circle cx="{CX}" cy="{CY}" r="{MAX_R+3}" fill="{EMPTY}"/>')

    for yi, y in enumerate(years):
        r1 = MIN_R + yi * ring_w + 0.6
        r2 = MIN_R + (yi + 1) * ring_w - 0.6
        start_d = dt.date(y, 1, 1)
        n_days = 366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365

        for dn in range(n_days):
            d = start_d + dt.timedelta(days=dn)
            if d not in active_dates and d not in cancelled_dates:
                continue
            a1d = -90 + dn / n_days * 360
            a2d = -90 + (dn + 1) / n_days * 360
            col = DOW_COLOR[d.weekday()] if d in active_dates else CANCELLED
            els.append(f'<path d="{arc(r1,r2,a1d,a2d)}" fill="{col}"/>')

        # ring separator line
        els.append(
            f'<circle cx="{CX}" cy="{CY}" r="{r1:.1f}" fill="none" '
            f'stroke="{BG}" stroke-width="1"/>'
        )

        # year label: white-backed text inside ring along ~July angle (day 192)
        r_mid = (r1 + r2) / 2
        ann_ang = math.radians(-90 + 192 / 365 * 360)  # ≈ July 11
        lx = CX + r_mid * math.cos(ann_ang)
        ly = CY + r_mid * math.sin(ann_ang)
        els.append(
            f'<rect x="{lx-13:.1f}" y="{ly-5:.1f}" width="26" height="10" '
            f'fill="rgba(250,250,248,0.75)" rx="2"/>'
        )
        els.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{FG}" font-size="8" '
            f'font-family="system-ui,sans-serif">{y}</text>'
        )

    # center hole
    els.append(f'<circle cx="{CX}" cy="{CY}" r="{MIN_R-1}" fill="{BG}"/>')

    # outer separator
    els.append(
        f'<circle cx="{CX}" cy="{CY}" r="{MAX_R:.1f}" fill="none" '
        f'stroke="{BG}" stroke-width="1.5"/>'
    )

    # month labels
    LABEL_R = MAX_R + 22
    MO_NAMES = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    MO_START = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    for name, ms in zip(MO_NAMES, MO_START):
        a = math.radians(-90 + (ms + 15) / 365 * 360)
        lx = CX + LABEL_R * math.cos(a)
        ly = CY + LABEL_R * math.sin(a)
        els.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="{MUTED}" font-size="9" '
            f'font-family="system-ui,sans-serif">{name}</text>'
        )

    # legend
    leg_items = [
        ("Tue", DOW_COLOR[1]),
        ("Thu", DOW_COLOR[3]),
        ("Sat", DOW_COLOR[5]),
        ("Other", DOW_COLOR[0]),
        ("Cancelled", CANCELLED),
    ]
    lx0 = CX - (len(leg_items) * 76) // 2
    ly0 = H - 28
    for i, (label, col) in enumerate(leg_items):
        lx = lx0 + i * 76
        els.append(
            f'<rect x="{lx}" y="{ly0-1}" width="10" height="10" fill="{col}" rx="2"/>'
        )
        els.append(
            f'<text x="{lx+14}" y="{ly0+8}" fill="{MUTED}" font-size="11" '
            f'font-family="system-ui,sans-serif">{label}</text>'
        )

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{W}" height="{H}" fill="{BG}" rx="14"/>
  <text x="{CX}" y="36" text-anchor="middle" fill="{FG}" font-size="20"
        font-family="system-ui,sans-serif" font-weight="700">When did we play?</text>
  <text x="{CX}" y="57" text-anchor="middle" fill="{MUTED}" font-size="11"
        font-family="system-ui,sans-serif">Each cell = one day · 2018 (inner) → 2026 (outer) · TIKS</text>
  {"".join(els)}
</svg>"""

    out = getattr(args, "out", "tiks-cal-chart.html")
    with open(out, "w") as f:
        f.write(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TIKS calendar chart</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{BG};display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
svg{{max-width:680px;width:100%}}</style></head><body>{svg}</body></html>""")
    print(f"\n  Written → {out}")


# ── monthly ───────────────────────────────────────────────────────────────────


def _clock_face(counts, label):
    rx, ry = 18, 9
    cx, cy = rx + 2, ry + 1
    width, height = cx * 2 + 4, cy * 2 + 3
    grid = [[" "] * width for _ in range(height)]
    max_val = max(counts.values(), default=1)

    for month in range(1, 13):
        angle = math.radians((month - 1) * 30 - 90)
        lx = round(cx + rx * math.cos(angle))
        ly = round(cy + ry * math.sin(angle) * 0.55)
        intensity = counts[month] / max_val
        dot = "●" if intensity > 0.66 else ("◉" if intensity > 0.33 else "○")
        tag = f"{MONTHS[month-1]} {dot} {counts[month]}"
        col = max(0, lx - len(tag)) if lx < cx else min(lx, width - len(tag) - 1)
        row = max(0, min(ly, height - 1))
        for i, ch in enumerate(tag):
            if 0 <= col + i < width:
                grid[row][col + i] = ch

    print(f"\n  — {label} by month (clock-face) —\n")
    for ln in ("    " + "".join(row).rstrip() for row in grid):
        if ln.strip():
            print(ln)


def cmd_monthly(args):
    db = connect(args)

    events_by_month = defaultdict(int)
    attendance_by_month = defaultdict(int)

    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "rsvps": 1}):
        d = e.get("date")
        if not isinstance(d, dt.datetime):
            continue
        m = d.month
        events_by_month[m] += 1
        for r in e.get("rsvps") or []:
            if not r.get("cancelled") and not r.get("waitlisted"):
                attendance_by_month[m] += 1

    max_e = max(events_by_month.values(), default=1)
    max_att = max(attendance_by_month.values(), default=1)

    section("TIKS ULTIMATE — events by month of year")
    print(f"\n  {'Month':<6}  {'Events':>6}  bar")
    print(f"  {'-'*5}  {'-'*6}  {'-'*40}")
    for i, month in enumerate(MONTHS, 1):
        print(
            f"  {month:<6}  {events_by_month[i]:>6}  {bar(events_by_month[i], max_e)}"
        )

    print(f"\n  {'Month':<6}  {'Show-ups':>8}  bar")
    print(f"  {'-'*5}  {'-'*8}  {'-'*40}")
    for i, month in enumerate(MONTHS, 1):
        print(
            f"  {month:<6}  {attendance_by_month[i]:>8}  {bar(attendance_by_month[i], max_att)}"
        )

    _clock_face(events_by_month, "events")
    _clock_face(attendance_by_month, "show-ups")


# ── special ───────────────────────────────────────────────────────────────────


def cmd_special(args):
    db = connect(args)
    max_delta = dt.timedelta(hours=args.max_hours)

    multi_day = []
    single_day = []

    for e in db.event.find(
        {"date": {"$exists": True}}, {"date": 1, "_end_date": 1, "name": 1, "rsvps": 1}
    ):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        end = e.get("_end_date")
        name = e.get("name") or "(untitled)"
        att = active_count(e.get("rsvps") or [])

        if isinstance(end, dt.datetime) and (end - start) > max_delta:
            multi_day.append((att, start, name, fmt_duration(start, end)))
        else:
            single_day.append((att, start, name))

    by_year = defaultdict(list)
    for att, d, name, dur in multi_day:
        by_year[d.year].append((att, name, dur))

    section("MULTI-DAY EVENTS")
    print(f"  ({len(multi_day)} events with duration > {args.max_hours}h)")
    for year in sorted(by_year, reverse=True):
        print(f"\n  {year}")
        for att, name, dur in sorted(by_year[year], key=lambda x: x[0], reverse=True):
            print(f"    {att:>3} people  [{dur:>4}]  {name}")
    total_att = sum(x[0] for x in multi_day)
    print(f"\n  Total attendance across all multi-day events: {total_att:,}")

    single_day.sort(key=lambda x: x[0], reverse=True)
    section(f"TOP {args.top} SINGLE-DAY EVENTS BY ATTENDANCE")
    print(f"\n  {'Att':>4}  {'Date':<9}  Name")
    print(f"  {'-'*4}  {'-'*8}  {'-'*45}")
    for att, d, name in single_day[: args.top]:
        print(f"  {att:>4}  {fmt_date(d):<9}  {name}")


# ── leadership ───────────────────────────────────────────────────────────────


def cmd_leadership(args):
    db = connect(args)

    names = {}
    for u in db.user.find({}, {"nick": 1, "name": 1}):
        names[u["_id"]] = u.get("nick") or u.get("name") or u["_id"]

    # year -> creator -> count
    by_year = defaultdict(Counter)
    total = Counter()

    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "created_by": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        cid = ref_id(e.get("created_by")) or e.get("created_by")
        if not cid:
            continue
        by_year[start.year][cid] += 1
        total[cid] += 1

    years = sorted(by_year)
    top_n = args.top

    section("TIKS ULTIMATE — event organisers by year")
    print(f"  (top {top_n} per year)\n")

    all_time = [(names.get(u, u), c) for u, c in total.most_common(top_n)]
    print(f"  All-time top organisers:")
    for i, (nm, c) in enumerate(all_time, 1):
        print(f"    {i:2d}. {nm:24s} {c:>4} events  {bar(c, all_time[0][1], 20)}")

    print()
    for year in years:
        top = by_year[year].most_common(top_n)
        max_c = top[0][1] if top else 1
        print(f"  {year}")
        for uid, c in top:
            nm = names.get(uid, uid)
            print(f"    {nm:24s} {c:>4}  {bar(c, max_c, 20)}")
        print()


# ── cohorts ───────────────────────────────────────────────────────────────────


def cmd_cohorts(args):
    db = connect(args)

    names = {}
    genders = {}
    for u in db.user.find({}, {"nick": 1, "name": 1, "gender": 1}):
        names[u["_id"]] = u.get("nick") or u.get("name") or u["_id"]
        genders[u["_id"]] = (u.get("gender") or "unknown").lower()

    # uid -> set of years active; year -> gender counts from attendance
    member_years = defaultdict(set)
    gender_by_year = defaultdict(Counter)

    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "rsvps": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        year = start.year
        for r in e.get("rsvps") or []:
            if r.get("cancelled") or r.get("waitlisted"):
                continue
            uid = ref_id(r.get("user")) or r.get("user")
            if uid:
                member_years[uid].add(year)
                gender_by_year[year][genders.get(uid, "unknown")] += 1

    # first year each member appeared
    first_year = {uid: min(yrs) for uid, yrs in member_years.items()}
    new_by_year = Counter(first_year.values())

    all_years = sorted(set(first_year.values()) | set(gender_by_year))
    players_by_year = defaultdict(set)
    for uid, yrs in member_years.items():
        for y in yrs:
            players_by_year[y].add(uid)

    section("TIKS ULTIMATE — team composition by year")

    # new members + retention
    print(f"\n  {'Year':>5}  {'Players':>7}  {'New':>5}  {'Retained%':>9}")
    print(f"  {'-'*5}  {'-'*7}  {'-'*5}  {'-'*9}")
    prev_players = set()
    for year in all_years:
        curr = players_by_year[year]
        new_count = new_by_year.get(year, 0)
        retained = len(curr & prev_players)
        ret_pct = f"{retained/len(prev_players)*100:.0f}%" if prev_players else "—"
        print(f"  {year:>5}  {len(curr):>7}  {new_count:>5}  {ret_pct:>9}")
        prev_players = curr

    # tenure leaderboard
    tenure = sorted(
        ((len(yrs), names.get(uid, uid)) for uid, yrs in member_years.items()),
        reverse=True,
    )
    print(f"\n  Most years active (loyalty)\n")
    print(f"  {'Years':>5}  Member")
    print(f"  {'-'*5}  {'-'*24}")
    for yrs, nm in tenure[: args.top]:
        print(f"  {yrs:>5}  {nm}")

    # founding cohort trajectory
    founding_year = min(all_years)
    founders = {uid for uid, yrs in member_years.items() if founding_year in yrs}
    print(
        f"\n  Founding cohort ({founding_year}) — {len(founders)} members — still playing each year\n"
    )
    print(f"  {'Year':>5}  {'Active':>6}  {'%':>5}  bar")
    print(f"  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*25}")
    for year in all_years:
        still = len(founders & players_by_year[year])
        pct = still / len(founders) * 100
        print(f"  {year:>5}  {still:>6}  {pct:>4.0f}%  {bar(still, len(founders), 25)}")


# ── players ───────────────────────────────────────────────────────────────────


def cmd_players(args):
    db = connect(args)

    names = {}
    for u in db.user.find({}, {"nick": 1, "name": 1}):
        names[u["_id"]] = u.get("nick") or u.get("name") or u["_id"]

    # uid -> year -> rsvp count
    rsvps_by_uid_year = defaultdict(lambda: defaultdict(int))
    member_years = defaultdict(set)

    for e in db.event.find({"date": {"$exists": True}}, {"date": 1, "rsvps": 1}):
        start = e.get("date")
        if not isinstance(start, dt.datetime):
            continue
        year = start.year
        for r in e.get("rsvps") or []:
            if r.get("cancelled") or r.get("waitlisted"):
                continue
            uid = ref_id(r.get("user")) or r.get("user")
            if uid:
                rsvps_by_uid_year[uid][year] += 1
                member_years[uid].add(year)

    all_years = sorted({y for yrs in member_years.values() for y in yrs})
    total_rsvps = Counter(
        {uid: sum(yc.values()) for uid, yc in rsvps_by_uid_year.items()}
    )

    # loyalists: played every year
    n_years = len(all_years)
    loyalists = sorted(
        [
            (uid, total_rsvps[uid])
            for uid, yrs in member_years.items()
            if len(yrs) == n_years
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    section("TIKS ULTIMATE — most active players by year")
    print(f"  (top {args.top} per year by active RSVPs)\n")

    for year in all_years:
        top = sorted(
            (
                (uid, rsvps_by_uid_year[uid][year])
                for uid in rsvps_by_uid_year
                if rsvps_by_uid_year[uid][year] > 0
            ),
            key=lambda x: x[1],
            reverse=True,
        )[: args.top]
        max_c = top[0][1] if top else 1
        print(f"  {year}")
        for uid, c in top:
            nm = names.get(uid, uid)
            print(f"    {nm:24s} {c:>3}  {bar(c, max_c, 20)}")
        print()

    section(f"PLAYERS ACTIVE ALL {n_years} YEARS  ({len(loyalists)} people)")
    print(f"\n  {'Total':>6}  Member")
    print(f"  {'-'*6}  {'-'*24}")
    for uid, total in loyalists:
        nm = names.get(uid, uid)
        print(f"  {total:>6}  {nm}")

    # current era players: active in either of the last two years, sorted by first year
    recent_years = sorted(all_years)[-2:]
    current_uids = {uid for uid, yrs in member_years.items() if yrs & set(recent_years)}
    current = sorted(
        [(min(member_years[uid]), total_rsvps[uid], uid) for uid in current_uids],
        key=lambda x: (x[0], -x[1]),
    )
    section(f"CURRENT PLAYERS — active in {' or '.join(str(y) for y in recent_years)}")
    print(f"  ({len(current)} players)\n")
    print(f"  {'Since':>5}  {'Total':>6}  {'Yrs':>3}  Member")
    print(f"  {'-'*5}  {'-'*6}  {'-'*3}  {'-'*24}")
    for first, total, uid in current:
        nm = names.get(uid, uid)
        yrs = len(member_years[uid])
        print(f"  {first:>5}  {total:>6}  {yrs:>3}  {nm}")


# ── search ────────────────────────────────────────────────────────────────────


def cmd_search(args):
    import re

    db = connect(args)
    pattern = re.compile(args.pattern, re.IGNORECASE)

    matches = []
    for e in db.event.find(
        {"date": {"$exists": True}}, {"date": 1, "name": 1, "rsvps": 1}
    ):
        name = e.get("name") or ""
        if not pattern.search(name):
            continue
        start = e.get("date")
        att = active_count(e.get("rsvps") or [])
        matches.append((start, name, att))

    matches.sort(key=lambda x: x[0])

    by_year = defaultdict(list)
    for d, name, att in matches:
        by_year[yr(d)].append((att, name, d))

    section(f"EVENTS MATCHING  '{args.pattern}'")
    print(f"  ({len(matches)} found)\n")
    print(f"  {'Att':>4}  {'Date':<9}  Name")
    print(f"  {'-'*4}  {'-'*8}  {'-'*50}")

    grand_total = 0
    for year in sorted(by_year):
        year_att = sum(a for a, _, _ in by_year[year])
        grand_total += year_att
        print(f"\n  {year}  —  {len(by_year[year])} event(s), {year_att} attendees")
        for att, name, d in sorted(by_year[year], key=lambda x: x[2]):
            print(f"  {att:>4}  {fmt_date(d):<9}  {name}")

    print(f"\n  Total attendees across all matches: {grand_total:,}")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="TIKS Ultimate RSVP app retrospective stats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--uri", default="mongodb://localhost:27017", help="MongoDB URI")
    ap.add_argument("--db", default="rsvpdata", help="database name")

    sub = ap.add_subparsers(dest="cmd", metavar="subcommand")
    sub.required = True

    # stats
    p = sub.add_parser("stats", help="overall numbers + HTML card")
    p.add_argument("--out", default="rsvp-retrospective.html", help="HTML output path")
    p.add_argument(
        "--top", type=int, default=10, help="entries in leaderboards (default: 10)"
    )
    p.add_argument(
        "--bump-top",
        type=int,
        default=8,
        metavar="N",
        help="players per year in bump chart (default: 10)",
    )

    # wa
    p = sub.add_parser("wa", help="WhatsApp scrolling avoided")
    p.add_argument(
        "--lines-per-screen",
        type=int,
        default=20,
        metavar="N",
        help="visible lines on a phone screen (default: 20)",
    )
    p.add_argument(
        "--header-lines",
        type=int,
        default=3,
        metavar="N",
        help="metadata lines per WA message (default: 3)",
    )

    # dow
    p = sub.add_parser("dow", help="practice sessions by day of week")
    p.add_argument(
        "--max-hours",
        type=int,
        default=24,
        metavar="H",
        help="exclude events longer than H hours (default: 24)",
    )

    # chart-dow
    p = sub.add_parser(
        "chart-dow", help="circular polar-bar chart of practice sessions by day"
    )
    p.add_argument(
        "--out",
        default="tiks-dow-chart.html",
        metavar="FILE",
        help="output HTML file (default: tiks-dow-chart.html)",
    )

    # chart-cal
    p = sub.add_parser("chart-cal", help="circular calendar heatmap, one cell per day")
    p.add_argument(
        "--out",
        default="tiks-cal-chart.html",
        metavar="FILE",
        help="output HTML file (default: tiks-cal-chart.html)",
    )

    # chart-evo
    p = sub.add_parser(
        "chart-evo", help="evolution tick chart: rows=day-of-week, x=date"
    )
    p.add_argument(
        "--out",
        default="tiks-evo-chart.html",
        metavar="FILE",
        help="output HTML file (default: tiks-evo-chart.html)",
    )

    # chart-players
    p = sub.add_parser(
        "chart-players", help="player timeline: first→last event per player"
    )
    p.add_argument(
        "--out",
        default="tiks-players-chart.html",
        metavar="FILE",
        help="output HTML file (default: tiks-players-chart.html)",
    )
    p.add_argument(
        "--min-events",
        type=int,
        default=30,
        metavar="N",
        help="minimum events to include a player (default: 30)",
    )
    p.add_argument(
        "--gap",
        type=int,
        default=30,
        metavar="N",
        help="event gap that marks an inactive period (default: 30)",
    )

    # monthly
    sub.add_parser("monthly", help="events/attendance by month + clock-face")

    # special
    p = sub.add_parser("special", help="multi-day and top single-day events")
    p.add_argument(
        "--max-hours",
        type=int,
        default=24,
        metavar="H",
        help="threshold for multi-day classification (default: 24)",
    )
    p.add_argument(
        "--top",
        type=int,
        default=20,
        metavar="N",
        help="top single-day events to show (default: 20)",
    )

    # leadership
    p = sub.add_parser("leadership", help="top event organisers per year")
    p.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="organisers to show per year (default: 5)",
    )

    # cohorts
    p = sub.add_parser(
        "cohorts", help="new members, retention, and gender ratio by year"
    )
    p.add_argument(
        "--top",
        type=int,
        default=15,
        metavar="N",
        help="entries in loyalty leaderboard (default: 15)",
    )

    # players
    p = sub.add_parser("players", help="top players by year + all-years loyalists")
    p.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="players to show per year (default: 5)",
    )

    # search
    p = sub.add_parser("search", help="find events by title pattern, grouped by year")
    p.add_argument("pattern", help="regex pattern to match against event names")

    # stream
    p = sub.add_parser("stream", help="interactive HTML stream graph of all players")
    p.add_argument("--out", default="tiks-players-stream.html", help="output HTML file")
    p.add_argument(
        "--min-events",
        type=int,
        default=5,
        metavar="N",
        help="minimum total events to include a player (default: 5)",
    )

    # features
    sub.add_parser(
        "features", help="per-feature usage stats (posts, photos, birthdays, etc.)"
    )

    # wordcount
    sub.add_parser("wordcount", help="WA word-count model with worked example")

    # gitlog
    p = sub.add_parser("gitlog", help="app development stats from git history")
    p.add_argument("--repo", default=".", help="path to git repo (default: .)")

    # chart-dev
    p = sub.add_parser("chart-dev", help="GitHub-style commit heatmap by month")
    p.add_argument("--repo", default=".", help="path to git repo (default: .)")
    p.add_argument("--out", default="tiks-dev-chart.html", metavar="FILE",
                   help="output HTML file (default: tiks-dev-chart.html)")

    # all
    sub.add_parser("all", help="run every subcommand with defaults")

    args = ap.parse_args()

    if args.cmd == "all":
        for cmd, defaults in [
            ("stats", {"out": "rsvp-retrospective.html", "top": 10, "bump_top": 8}),
            ("stream", {"out": "tiks-players-stream.html", "min_events": 5}),
            ("wa", {"lines_per_screen": 20, "header_lines": 3}),
            ("dow", {"max_hours": 24}),
            ("monthly", {}),
            ("special", {"max_hours": 24, "top": 20}),
            ("leadership", {"top": 5}),
            ("cohorts", {"top": 15}),
            ("players", {"top": 5}),
            ("features", {}),
            ("gitlog", {"repo": "."}),
        ]:
            sub_args = argparse.Namespace(uri=args.uri, db=args.db, **defaults)
            globals()[f"cmd_{cmd}"](sub_args)
    else:
        fn = "cmd_" + args.cmd.replace("-", "_")
        globals()[fn](args)

    print()


if __name__ == "__main__":
    main()
