"""ER-диаграмма модели данных со связями «поле-к-полю».

Линии — строго ортогональные (прямые углы) и проложены по пустым каналам
между столбцами таблиц, поэтому не заходят за таблицы. Раскладка:
  • слева  — USERS (родитель большинства связей);
  • центр  — дочерние таблицы пользователя;
  • справа — TOPICS и EVENTS.
Связи рисуются «гребёнкой»: один вертикальный ствол от PK + горизонтальные
ответвления к каждому FK. PK помечен точкой, FK — «лапкой многих».

PNG получается из SVG через cairosvg. Запуск:
    python docs/diagrams/04_er_diagram.py
"""
from __future__ import annotations

from pathlib import Path

NAVY = "#0F2C68"
LIGHT = "#eaeff7"
KEYBG = "#fde7c9"
WHITE = "#ffffff"
TEXT = "#1a1a1a"
FONT = "Arial, Helvetica, sans-serif"

# цвет связей по родительской таблице — чтобы было видно, что откуда куда идёт
C_USERS = "#0F2C68"   # тёмно-синий
C_TOPICS = "#1f8a4c"  # зелёный
C_EVENTS = "#c0531f"  # кирпичный

ROW_H = 34
TITLE_H = 38

# --- поля таблиц ------------------------------------------------------------
FIELDS = {
    "USERS": [("int", "id", "PK"), ("bigint", "telegram_id", "UK"),
              ("string", "username", ""), ("string", "preferred_format", ""),
              ("string", "city", ""), ("text", "topic_weights", "JSON"),
              ("vector", "embedding", "384")],
    "USER_MEMORIES": [("int", "id", "PK"), ("int", "user_id", "FK"),
                      ("text", "text", ""), ("string", "category", ""),
                      ("float", "salience", "")],
    "USER_SKILL_PROFILES": [("int", "user_id", "FK"),
                            ("string", "current_role", ""),
                            ("string", "target_role", ""),
                            ("text", "target_skills", "JSON")],
    "USER_BANDIT_STATES": [("int", "user_id", "FK"), ("int", "dim", ""),
                           ("text", "a_json", ""), ("text", "b_json", "")],
    "USER_TOPIC_STATS": [("int", "user_id", "FK"), ("int", "topic_id", "FK"),
                         ("float", "alpha", ""), ("float", "beta", "")],
    "USER_TOPICS": [("int", "user_id", "FK"), ("int", "topic_id", "FK")],
    "INTERACTIONS": [("int", "id", "PK"), ("int", "user_id", "FK"),
                     ("int", "event_id", "FK"), ("string", "action", "like/save"),
                     ("datetime", "created_at", "")],
    "TOPICS": [("int", "id", "PK"), ("string", "code", "UK"),
               ("string", "title", "")],
    "EVENTS": [("int", "id", "PK"), ("string", "title", ""),
               ("text", "description", ""), ("string", "format", ""),
               ("string", "city", ""), ("datetime", "start_at", ""),
               ("vector", "embedding", "384"), ("int", "quality_score", ""),
               ("int", "hype_score", ""), ("text", "tech_stack", "JSON")],
    "EVENT_TOPICS": [("int", "event_id", "FK"), ("int", "topic_id", "FK")],
}

# --- раскладка: x, ширина по столбцам ---------------------------------------
COL_L_X, COL_L_W = 40, 300        # USERS (левый столбец)
COL_M_X, COL_M_W = 500, 290       # дочерние пользователя (центр)
COL_R_X, COL_R_W = 980, 290       # TOPICS / EVENTS (правый столбец)
TRUNK_L = 415                     # ствол связей USERS (левый канал)
TRUNK_T = 820                     # ствол связей TOPICS (правый канал)
TRUNK_E = 900                     # ствол связей EVENTS (правый канал)

POS = {}  # name -> (x, y, w)


def height(name):
    return TITLE_H + len(FIELDS[name]) * ROW_H


def _stack(names, x, w, y0, gap):
    y = y0
    for n in names:
        POS[n] = (x, y, w)
        y += height(n) + gap


def layout():
    POS["USERS"] = (COL_L_X, 60, COL_L_W)
    _stack(["USER_MEMORIES", "USER_SKILL_PROFILES", "USER_BANDIT_STATES",
            "USER_TOPIC_STATS", "USER_TOPICS", "INTERACTIONS"],
           COL_M_X, COL_M_W, 60, 26)
    _stack(["TOPICS", "EVENTS", "EVENT_TOPICS"], COL_R_X, COL_R_W, 60, 34)


def fidx(name, field):
    return [f[1] for f in FIELDS[name]].index(field)


def anchor(name, field, side):
    x, y, w = POS[name]
    ry = y + TITLE_H + (fidx(name, field) + 0.5) * ROW_H
    return (x if side == "l" else x + w), ry


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_table(name):
    x, y, w = POS[name]
    h = height(name)
    p = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" '
         f'fill="{WHITE}" stroke="{NAVY}" stroke-width="1.5"/>',
         f'<rect x="{x}" y="{y}" width="{w}" height="{TITLE_H}" rx="4" fill="{NAVY}"/>',
         f'<rect x="{x}" y="{y + TITLE_H - 6}" width="{w}" height="6" fill="{NAVY}"/>',
         f'<text x="{x + w/2}" y="{y + TITLE_H/2}" text-anchor="middle" '
         f'dominant-baseline="central" font-family="{FONT}" font-size="17" '
         f'font-weight="bold" fill="{WHITE}">{esc(name)}</text>']
    c1, c2, c3 = x + 12, x + w * 0.40, x + w - 12
    for i, (typ, fld, key) in enumerate(FIELDS[name]):
        ry = y + TITLE_H + i * ROW_H
        is_key = key in ("PK", "FK", "UK")
        fill = KEYBG if is_key else (LIGHT if i % 2 else WHITE)
        cy = ry + ROW_H / 2
        bold = ' font-weight="bold"' if is_key else ""
        p.append(f'<rect x="{x}" y="{ry}" width="{w}" height="{ROW_H}" '
                 f'fill="{fill}" stroke="{LIGHT}" stroke-width="0.5"/>')
        p.append(f'<text x="{c1}" y="{cy}" dominant-baseline="central" '
                 f'font-family="{FONT}" font-size="13" fill="#666">{esc(typ)}</text>')
        p.append(f'<text x="{c2}" y="{cy}" dominant-baseline="central" '
                 f'font-family="{FONT}" font-size="14"{bold} fill="{TEXT}">{esc(fld)}</text>')
        if key:
            p.append(f'<text x="{c3}" y="{cy}" text-anchor="end" '
                     f'dominant-baseline="central" font-family="{FONT}" '
                     f'font-size="12" font-weight="bold" fill="{NAVY}">{esc(key)}</text>')
    return "\n".join(p)


def _seg(x1, y1, x2, y2, color):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="2.5"/>')


def _crowfoot(x, y, sign, color):
    fx = 12 * sign
    return "\n".join([_seg(x, y, x + fx, y - 7, color),
                      _seg(x, y, x + fx, y + 7, color),
                      _seg(x, y, x + fx, y, color)])


def comb(parent, pk, parent_side, trunk_x, children, color):
    px, py, pw = POS[parent]
    pax = px if parent_side == "l" else px + pw
    pay = anchor(parent, pk, parent_side)[1]
    out = [_seg(pax, pay, trunk_x, pay, color),
           f'<circle cx="{pax}" cy="{pay}" r="4.5" fill="{color}"/>']
    ys = [pay]
    for ct, cf, cside in children:
        cax, cay = anchor(ct, cf, cside)
        ys.append(cay)
        out.append(_seg(cax, cay, trunk_x, cay, color))
        out.append(_crowfoot(cax, cay, 1 if trunk_x > cax else -1, color))
    out.append(_seg(trunk_x, min(ys), trunk_x, max(ys), color))
    return "\n".join(out)


def legend(x, y):
    items = [(C_USERS, "связи USERS"), (C_TOPICS, "связи TOPICS"),
             (C_EVENTS, "связи EVENTS")]
    out = [f'<rect x="{x}" y="{y}" width="210" height="118" rx="6" '
           f'fill="{WHITE}" stroke="{NAVY}" stroke-width="1.5"/>',
           f'<text x="{x + 105}" y="{y + 24}" text-anchor="middle" '
           f'font-family="{FONT}" font-size="15" font-weight="bold" '
           f'fill="{NAVY}">Условные обозначения</text>']
    for i, (c, label) in enumerate(items):
        ly = y + 52 + i * 24
        out.append(_seg(x + 16, ly, x + 56, ly, c))
        out.append(f'<circle cx="{x + 16}" cy="{ly}" r="4" fill="{c}"/>')
        out.append(_crowfoot(x + 56, ly, 1, c))
        out.append(f'<text x="{x + 72}" y="{ly}" dominant-baseline="central" '
                   f'font-family="{FONT}" font-size="13" '
                   f'fill="{TEXT}">{label}</text>')
    return "\n".join(out)


def render():
    layout()
    edges = [
        comb("USERS", "id", "r", TRUNK_L, [
            ("USER_MEMORIES", "user_id", "l"),
            ("USER_SKILL_PROFILES", "user_id", "l"),
            ("USER_BANDIT_STATES", "user_id", "l"),
            ("USER_TOPIC_STATS", "user_id", "l"),
            ("USER_TOPICS", "user_id", "l"),
            ("INTERACTIONS", "user_id", "l")], C_USERS),
        comb("TOPICS", "id", "l", TRUNK_T, [
            ("USER_TOPIC_STATS", "topic_id", "r"),
            ("USER_TOPICS", "topic_id", "r"),
            ("EVENT_TOPICS", "topic_id", "l")], C_TOPICS),
        comb("EVENTS", "id", "l", TRUNK_E, [
            ("INTERACTIONS", "event_id", "r"),
            ("EVENT_TOPICS", "event_id", "l")], C_EVENTS),
    ]
    w = max(x + ww for x, _, ww in POS.values()) + 40
    h = max(y + height(n) for n, (_, y, _) in POS.items()) + 40
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
             f'width="{w}" height="{h}">',
             f'<rect width="{w}" height="{h}" fill="{WHITE}"/>',
             *edges,
             *(render_table(n) for n in POS),
             legend(40, 400),
             "</svg>"]
    return "\n".join(parts), w, h


if __name__ == "__main__":
    svg, w, h = render()
    out_svg = Path(__file__).with_name("04_er_diagram.svg")
    out_svg.write_text(svg, encoding="utf-8")
    print(f"SVG written: {len(svg)} bytes, {w}x{h}")
    try:
        import cairosvg
        cairosvg.svg2png(url=str(out_svg),
                         write_to=str(out_svg.with_suffix(".png")), scale=2)
        print("PNG written via cairosvg")
    except ImportError:
        print("cairosvg недоступен — конвертируйте SVG в PNG вручную")
