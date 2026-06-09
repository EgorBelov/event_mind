"""Generate BPMN-style SVG diagram in the Unisender notation style.

Process: Получение персональной рекомендации.
Pool: Разрабатываемая система.
Lanes (top→bottom): Пользователь, Telegram-бот, Backend, Рекомендатель.
"""
from __future__ import annotations

CANVAS_W = 1920
CANVAS_H = 820
POOL_TITLE_W = 30
LANE_TITLE_W = 70
LANE_LEFT = POOL_TITLE_W + LANE_TITLE_W  # 100
POOL_PAD_BOTTOM = 20

LANES = [
    ('Пользователь', 10, 200),
    ('Telegram-бот', 210, 200),
    ('Backend (FastAPI)', 410, 200),
    ('Рекомендатель', 610, 200),
]
POOL_BOTTOM = LANES[-1][1] + LANES[-1][2]  # 810
POOL_HEIGHT = POOL_BOTTOM + POOL_PAD_BOTTOM  # 830 — adjust canvas

CANVAS_H = POOL_HEIGHT
TITLE = 'Получение персональной рекомендации'

# Colors (matching Unisender style)
C_POOL_BG = '#ffffff'
C_LANE_TITLE = '#f4f4f4'
C_POOL_BORDER = '#7f7f7f'
C_LANE_BORDER = '#7f7f7f'
C_TASK_FILL = '#dceefb'
C_TASK_BORDER = '#4a90d9'
C_GATE_FILL = '#fff2a8'
C_GATE_BORDER = '#a8a000'
C_START_FILL = '#9bd99b'
C_START_BORDER = '#4a9a4a'
C_END_FILL = '#f4a8a8'
C_END_BORDER = '#b04040'
C_FLOW = '#2a2a2a'
C_FLOW_LABEL = '#1a1a1a'
C_TEXT = '#1a1a1a'

FONT = 'Arial, Helvetica, sans-serif'


def lane_center(idx: int) -> int:
    name, y, h = LANES[idx]
    return y + h // 2


# ===== Node positions =====
# Each: (id, label, lane_idx, x_center, kind, [extra])
# kind: 'start', 'end', 'task', 'gate_xor', 'gate_xor_merge'
NODES = {
    'start':       ('',                            0, 170,  'start'),
    't_req':       ('Запросить\nрекомендации',     0, 320,  'task'),
    't_send':      ('Отправить\nзапрос в API',     1, 500,  'task'),
    'g_cache':     ('Кэш\nактуален?',              2, 700,  'gate_xor'),
    't_candidates':('Сформировать\nпул кандидатов', 3, 880,  'task'),
    't_rank':      ('Гибридное\nранжирование',     3, 1080, 'task'),
    'g_merge':     ('',                            2, 1280, 'gate_xor_merge'),
    't_response':  ('Сформировать\nJSON-ответ',    2, 1440, 'task'),
    't_render':    ('Отобразить\nкарточки',        1, 1620, 'task'),
    't_view':      ('Просмотреть\nподборку',       0, 1780, 'task'),
    'end':         ('Готово',                      0, 1880, 'end'),
}

# Sizes
TASK_W, TASK_H = 140, 70
GATE_R = 26  # half-width
EVENT_R = 18


def node_xy(nid: str) -> tuple[float, float]:
    label, lane_idx, x, kind, *_ = NODES[nid]
    return (x, lane_center(lane_idx))


# ===== Flows =====
# (from, to, label, route)
# route: 'h' (direct horizontal), 'vh' (down then right), 'hv' (right then down/up),
#        'vhv' (down, right, up), or 'manual' with custom waypoints
FLOWS = [
    ('start',        't_req',        '',   'h'),
    ('t_req',        't_send',       '',   'vh_down'),    # L1 → L2
    ('t_send',       'g_cache',      '',   'vh_down'),    # L2 → L3
    ('g_cache',      't_candidates', 'нет', 'vh_down'),   # L3 → L4 (down branch)
    ('g_cache',      'g_merge',      'да',  'hv_arc_up'), # L3 stay, label да above
    ('t_candidates', 't_rank',       '',    'h'),
    ('t_rank',       'g_merge',      '',    'vh_up'),    # L4 → L3
    ('g_merge',      't_response',   '',    'h'),
    ('t_response',   't_render',     '',    'vh_up'),    # L3 → L2
    ('t_render',     't_view',       '',    'vh_up'),    # L2 → L1
    ('t_view',       'end',          '',    'h'),
]


# ===== SVG renderers =====
def svg_text(x, y, text, *, fs=12, anchor='middle', baseline='middle',
             color=C_TEXT, weight='normal'):
    lines = text.split('\n')
    if len(lines) == 1:
        return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
                f'dominant-baseline="{baseline}" font-family="{FONT}" '
                f'font-size="{fs}" font-weight="{weight}" fill="{color}">{lines[0]}</text>')
    # Multi-line: use tspan
    line_h = fs + 2
    total_h = line_h * len(lines)
    start_y = y - total_h / 2 + line_h / 2
    parts = [f'<text x="{x}" text-anchor="{anchor}" font-family="{FONT}" '
             f'font-size="{fs}" font-weight="{weight}" fill="{color}">']
    for i, line in enumerate(lines):
        ly = start_y + i * line_h
        parts.append(f'<tspan x="{x}" y="{ly}" dominant-baseline="middle">{line}</tspan>')
    parts.append('</text>')
    return ''.join(parts)


def render_pool() -> str:
    parts = []
    # Outer pool rectangle
    parts.append(
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'fill="{C_POOL_BG}" stroke="{C_POOL_BORDER}" stroke-width="1.5"/>'
    )
    # Pool title bar (left vertical)
    parts.append(
        f'<rect x="0" y="0" width="{POOL_TITLE_W}" height="{CANVAS_H}" '
        f'fill="{C_LANE_TITLE}" stroke="{C_POOL_BORDER}" stroke-width="1.5"/>'
    )
    # Pool title text (rotated)
    parts.append(
        f'<text x="{POOL_TITLE_W/2}" y="{CANVAS_H/2}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="14" font-weight="bold" fill="{C_TEXT}" '
        f'transform="rotate(-90, {POOL_TITLE_W/2}, {CANVAS_H/2})">{TITLE}</text>'
    )
    # Lanes
    for i, (name, y, h) in enumerate(LANES):
        # Lane title cell
        parts.append(
            f'<rect x="{POOL_TITLE_W}" y="{y}" width="{LANE_TITLE_W}" height="{h}" '
            f'fill="{C_LANE_TITLE}" stroke="{C_LANE_BORDER}" stroke-width="1"/>'
        )
        cx = POOL_TITLE_W + LANE_TITLE_W / 2
        cy = y + h / 2
        parts.append(
            f'<text x="{cx}" y="{cy}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="12" font-weight="bold" fill="{C_TEXT}" '
            f'transform="rotate(-90, {cx}, {cy})">{name}</text>'
        )
        # Lane content separator (horizontal line)
        if i > 0:
            parts.append(
                f'<line x1="{POOL_TITLE_W}" y1="{y}" x2="{CANVAS_W}" y2="{y}" '
                f'stroke="{C_LANE_BORDER}" stroke-width="1"/>'
            )
        # Right border of lane title column
        parts.append(
            f'<line x1="{LANE_LEFT}" y1="{y}" x2="{LANE_LEFT}" y2="{y + h}" '
            f'stroke="{C_LANE_BORDER}" stroke-width="1"/>'
        )
    return '\n'.join(parts)


def render_node(nid: str) -> str:
    label, lane_idx, x, kind, *_ = NODES[nid]
    y = lane_center(lane_idx)
    parts = []
    if kind == 'start':
        parts.append(
            f'<circle cx="{x}" cy="{y}" r="{EVENT_R}" '
            f'fill="{C_START_FILL}" stroke="{C_START_BORDER}" stroke-width="1.5"/>'
        )
    elif kind == 'end':
        parts.append(
            f'<circle cx="{x}" cy="{y}" r="{EVENT_R}" '
            f'fill="{C_END_FILL}" stroke="{C_END_BORDER}" stroke-width="3"/>'
        )
        if label:
            parts.append(svg_text(x, y + EVENT_R + 14, label, fs=11))
    elif kind == 'task':
        parts.append(
            f'<rect x="{x - TASK_W/2}" y="{y - TASK_H/2}" '
            f'width="{TASK_W}" height="{TASK_H}" rx="8" ry="8" '
            f'fill="{C_TASK_FILL}" stroke="{C_TASK_BORDER}" stroke-width="1.5"/>'
        )
        parts.append(svg_text(x, y, label, fs=12))
    elif kind in ('gate_xor', 'gate_xor_merge'):
        # Diamond
        pts = f'{x},{y - GATE_R} {x + GATE_R},{y} {x},{y + GATE_R} {x - GATE_R},{y}'
        parts.append(
            f'<polygon points="{pts}" fill="{C_GATE_FILL}" '
            f'stroke="{C_GATE_BORDER}" stroke-width="1.5"/>'
        )
        # X marker inside
        m = GATE_R * 0.45
        parts.append(
            f'<line x1="{x - m}" y1="{y - m}" x2="{x + m}" y2="{y + m}" '
            f'stroke="{C_GATE_BORDER}" stroke-width="2"/>'
            f'<line x1="{x - m}" y1="{y + m}" x2="{x + m}" y2="{y - m}" '
            f'stroke="{C_GATE_BORDER}" stroke-width="2"/>'
        )
        if label:
            parts.append(svg_text(x, y + GATE_R + 22, label, fs=11))
    return '\n'.join(parts)


def node_bounds(nid: str) -> tuple[float, float, float, float]:
    """Return left, right, top, bottom of the node's body."""
    label, lane_idx, x, kind, *_ = NODES[nid]
    y = lane_center(lane_idx)
    if kind in ('start', 'end'):
        return x - EVENT_R, x + EVENT_R, y - EVENT_R, y + EVENT_R
    if kind in ('gate_xor', 'gate_xor_merge'):
        return x - GATE_R, x + GATE_R, y - GATE_R, y + GATE_R
    return x - TASK_W/2, x + TASK_W/2, y - TASK_H/2, y + TASK_H/2


def render_arrow(points: list[tuple[float, float]], label: str = '') -> str:
    if len(points) < 2:
        return ''
    d = f'M {points[0][0]},{points[0][1]}'
    for px, py in points[1:]:
        d += f' L {px},{py}'
    parts = [
        f'<path d="{d}" fill="none" stroke="{C_FLOW}" stroke-width="1.5" '
        f'marker-end="url(#arrow)"/>'
    ]
    if label:
        # Place label near the middle of the longest horizontal segment if exists
        # Otherwise just middle
        # Find longest horizontal segment
        best_idx, best_len = 0, -1
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            if y1 == y2 and abs(x2 - x1) > best_len:
                best_len = abs(x2 - x1)
                best_idx = i
        if best_len > 30:
            x1, y1 = points[best_idx]
            x2, y2 = points[best_idx + 1]
            lx = (x1 + x2) / 2
            ly = y1 - 8
            parts.append(svg_text(lx, ly, label, fs=11, color=C_FLOW_LABEL, weight='normal'))
        else:
            # Use first vertical segment
            for i in range(len(points) - 1):
                x1, y1 = points[i]
                x2, y2 = points[i + 1]
                if x1 == x2 and abs(y2 - y1) > 20:
                    lx = x1 + 10
                    ly = (y1 + y2) / 2
                    parts.append(svg_text(lx, ly, label, fs=11, anchor='start',
                                          color=C_FLOW_LABEL))
                    break
    return '\n'.join(parts)


def compute_route(src_id: str, dst_id: str, route: str) -> list[tuple[float, float]]:
    sl, sr, st, sb = node_bounds(src_id)
    dl, dr, dt_, db = node_bounds(dst_id)
    src_cx = (sl + sr) / 2
    src_cy = (st + sb) / 2
    dst_cy = (dt_ + db) / 2

    if route == 'h':
        return [(sr, src_cy), (dl, dst_cy)]
    if route == 'vh_down':
        # Exit bottom of src, go down to dst's lane center, then right into left of dst
        return [(src_cx, sb), (src_cx, dst_cy), (dl, dst_cy)]
    if route == 'vh_up':
        return [(src_cx, st), (src_cx, dst_cy), (dl, dst_cy)]
    if route == 'hv_arc_up':
        # From src right, go right halfway, up to a lane above, right to dst
        # Used for "да" branch: g_cache (L3) → g_merge (L3) horizontal but routed above L3
        # Actually simplest: straight horizontal at L3 level (same lane). Draw above
        mid_y = src_cy - GATE_R - 30  # above the gateway
        return [(sr, src_cy), (sr + 30, src_cy), (sr + 30, mid_y),
                (dl - 30, mid_y), (dl - 30, dst_cy), (dl, dst_cy)]
    raise ValueError(f'Unknown route: {route}')


def render_flows() -> str:
    parts = []
    for src, dst, label, route in FLOWS:
        pts = compute_route(src, dst, route)
        parts.append(render_arrow(pts, label))
    return '\n'.join(parts)


def render() -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'width="{CANVAS_W}" height="{CANVAS_H}">',
        # Arrowhead marker
        '<defs>',
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse">',
        f'<path d="M 0,0 L 10,5 L 0,10 z" fill="{C_FLOW}"/>',
        '</marker>',
        '</defs>',
        # Pool + lanes
        render_pool(),
        # Flows first (so nodes sit on top)
        render_flows(),
        # Nodes
        *(render_node(nid) for nid in NODES),
        '</svg>',
    ]
    return '\n'.join(parts)


if __name__ == '__main__':
    svg = render()
    with open('/Users/Hisoka/eventmind/docs/diagrams/02_business_process.svg', 'w',
              encoding='utf-8') as f:
        f.write(svg)
    print(f'SVG written: {len(svg)} bytes, canvas {CANVAS_W}x{CANVAS_H}')
