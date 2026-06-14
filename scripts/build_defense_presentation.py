"""Сборка презентации для защиты курсовой EventMind.

Дизайн (шрифт HSE Sans, тёмно-синий 0F2C68, колонтитул, макет «Текст_1»)
переиспользуется из эталонного шаблона презентации прошлой защиты, чтобы
комиссия видела привычное оформление. Контент полностью заменён на EventMind.

Запуск:  python -m scripts.build_defense_presentation \
             --template <шаблон.pptx> --out docs/Презентация_EventMind.pptx
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# --- палитра темы шаблона --------------------------------------------------
NAVY = RGBColor(0x0F, 0x2C, 0x68)
ORANGE = RGBColor(0xED, 0x7D, 0x31)
BLUE = RGBColor(0x44, 0x72, 0xC4)
GREY = RGBColor(0x59, 0x59, 0x59)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xEA, 0xEF, 0xF7)
FONT = "HSE Sans"

DIAGRAMS = Path("docs/diagrams")

# колонтитул (повторяется на каждом контентном слайде) — геометрия из шаблона
PROJ_TITLE = "EventMind — IT-события и AI-рекомендации"
AUTHOR = "Белов Егор"
EVENT = ("Защита курсовой", "Пермь, 2026")


def _set_font(run, size=None, bold=None, color=None, italic=None):
    run.font.name = FONT
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def _clear(tf):
    tf.word_wrap = True
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    p0 = tf.paragraphs[0]
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)
    return p0


def add_textbox(slide, l, t, w, h, anchor=None):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    if anchor is not None:
        tf.vertical_anchor = anchor
    return tb


def add_footer(slide):
    """Верхний колонтитул: вписываем текст в ячейки шапки макета «Текст_1».

    Сам макет рисует логотип ВШЭ (слева), номер слайда (справа) и сетку
    разделителей — поэтому позиции берём из оригинала, чтобы не наезжать
    на эти элементы.
    """
    tb = add_textbox(slide, 1.08, 0.27, 3.0, 0.55, anchor=MSO_ANCHOR.MIDDLE)
    p = _clear(tb.text_frame)
    r = p.add_run(); r.text = PROJ_TITLE
    _set_font(r, 10.5, bold=True, color=NAVY)

    tb = add_textbox(slide, 4.2, 0.27, 2.2, 0.55, anchor=MSO_ANCHOR.MIDDLE)
    p = _clear(tb.text_frame)
    r = p.add_run(); r.text = AUTHOR
    _set_font(r, 10.5, color=GREY)

    tb = add_textbox(slide, 7.46, 0.27, 2.0, 0.6, anchor=MSO_ANCHOR.MIDDLE)
    tf = tb.text_frame
    p = _clear(tf)
    r = p.add_run(); r.text = EVENT[0]; _set_font(r, 10.5, bold=True, color=NAVY)
    p2 = tf.add_paragraph()
    r = p2.add_run(); r.text = EVENT[1]; _set_font(r, 10.5, color=GREY)


def add_heading(slide, text):
    tb = add_textbox(slide, 0.5, 1.02, 12.3, 0.8)
    p = _clear(tb.text_frame)
    r = p.add_run(); r.text = text
    _set_font(r, 32, bold=True, color=NAVY)


def new_slide(prs, heading=None):
    """Контентный слайд на макете «Текст_1» без унаследованных плейсхолдеров."""
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    for ph in list(slide.placeholders):
        ph._element.getparent().remove(ph._element)
    add_footer(slide)
    if heading:
        add_heading(slide, heading)
    return slide


def bullets(slide, l, t, w, h, items, size=16, gap=8, anchor=MSO_ANCHOR.TOP):
    """items: список (text, level) либо строк. level 0 — буллет, 1 — подпункт."""
    tb = add_textbox(slide, l, t, w, h, anchor=anchor)
    tf = tb.text_frame
    first = True
    for it in items:
        if isinstance(it, tuple):
            text, level = it
        else:
            text, level = it, 0
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_after = Pt(gap)
        marker = "•  " if level == 0 else "–  "
        r = p.add_run(); r.text = marker + text
        _set_font(r, size if level == 0 else size - 2,
                  bold=False, color=NAVY if level == 0 else GREY)
    return tb


def card(slide, l, t, w, h, title, body, fill=LIGHT, title_color=NAVY):
    """Прямоугольная карточка с заголовком и текстом."""
    sh = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = NAVY; sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    tf = sh.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for m in ("left", "right", "top", "bottom"):
        setattr(tf, f"margin_{m}", Pt(8))
    p = _clear(tf)
    r = p.add_run(); r.text = title
    _set_font(r, 15, bold=True, color=title_color)
    for line in body:
        bp = tf.add_paragraph(); bp.space_before = Pt(3)
        r = bp.add_run(); r.text = line
        _set_font(r, 12.5, color=GREY)
    return sh


def add_image_fit(slide, path, area_l, area_t, area_w, area_h):
    """Вписать картинку в прямоугольную область, центрируя."""
    from PIL import Image
    iw, ih = Image.open(path).size
    scale = min(area_w / iw, area_h / ih)
    w, h = iw * scale, ih * scale
    left = area_l + (area_w - w) / 2
    top = area_t + (area_h - h) / 2
    return slide.shapes.add_picture(str(path), Inches(left), Inches(top),
                                    width=Inches(w), height=Inches(h))


def caption(slide, text, t=7.05):
    tb = add_textbox(slide, 0.55, t, 12.2, 0.4)
    p = _clear(tb.text_frame); p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    _set_font(r, 12, italic=True, color=GREY)


def style_table(table, header_fill=NAVY, col_widths=None, header_size=12.5,
                body_size=11, first_col_bold=True):
    if col_widths:
        for i, cw in enumerate(col_widths):
            table.columns[i].width = Inches(cw)
    n_cols = len(table.columns)
    for ci in range(n_cols):
        cell = table.cell(0, ci)
        cell.fill.solid(); cell.fill.fore_color.rgb = header_fill
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                _set_font(r, header_size, bold=True, color=WHITE)
    for ri in range(1, len(table.rows)):
        for ci in range(n_cols):
            cell = table.cell(ri, ci)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if ri % 2 else LIGHT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    _set_font(r, body_size,
                              bold=(first_col_bold and ci == 0),
                              color=NAVY if (first_col_bold and ci == 0) else GREY)


def add_table(slide, data, l, t, w, h, col_widths=None, header_size=12.5,
              body_size=11):
    rows, cols = len(data), len(data[0])
    gf = slide.shapes.add_table(rows, cols, Inches(l), Inches(t),
                                Inches(w), Inches(h))
    table = gf.table
    # отключаем «банд» стандартного стиля — красим сами
    tbl = table._tbl
    tblPr = tbl.tblPr
    tblPr.set("firstRow", "1")
    tblPr.set("bandRow", "0")
    for ri, row in enumerate(data):
        for ci, val in enumerate(row):
            cell = table.cell(ri, ci)
            cell.text = str(val)
            for m in ("left", "right"):
                setattr(cell.text_frame, f"margin_{m}", Pt(6))
            for m in ("top", "bottom"):
                setattr(cell.text_frame, f"margin_{m}", Pt(3))
    style_table(table, col_widths=col_widths, header_size=header_size,
                body_size=body_size)
    return table


# ===========================================================================
def build(template: str, out: str):
    prs = Presentation(template)

    # --- Слайд 1: обложка — правим текст по месту -------------------------
    s1 = prs.slides[0]
    by_name = {}
    for sh in s1.shapes:
        by_name.setdefault(sh.name, []).append(sh)

    def set_title(shape, lines, size=30, bold=True):
        tf = shape.text_frame
        p = _clear(tf)
        first = True
        for ln in lines:
            pp = p if first else tf.add_paragraph()
            first = False
            r = pp.add_run(); r.text = ln
            _set_font(r, size, bold=bold, color=NAVY)

    set_title(by_name["Заголовок 1"][0],
              ["EventMind — система агрегации IT-мероприятий",
               "и персонализированных AI-рекомендаций"], size=30)

    # «Пермь / 2026»
    t4 = by_name["Текст 4"][0]
    tf = t4.text_frame; p = _clear(tf)
    r = p.add_run(); r.text = "Пермь"; _set_font(r, 14)
    p2 = tf.add_paragraph(); r = p2.add_run(); r.text = "2026"; _set_font(r, 14)

    # автор / руководитель — берём текстблоки по позиции
    for sh in s1.shapes:
        if not sh.has_text_frame:
            continue
        txt = sh.text_frame.text
        if txt.startswith("Работу выполнил"):
            tf = sh.text_frame; p = _clear(tf)
            r = p.add_run(); r.text = "Работу выполнил студент: "
            _set_font(r, 18)
            r = p.add_run(); r.text = "Белов Е.А."
            _set_font(r, 18, bold=True)
        elif txt.startswith("Руководитель"):
            tf = sh.text_frame; p = _clear(tf)
            r = p.add_run(); r.text = "Руководитель:"
            _set_font(r, 18)
            p2 = tf.add_paragraph()
            r = p2.add_run()
            r.text = "Доцент к.ф.-м.н., доцент кафедры информационных технологий в бизнесе"
            _set_font(r, 14)
            p3 = tf.add_paragraph()
            r = p3.add_run(); r.text = "Замятина Е.Б."
            _set_font(r, 14, bold=True)

    # --- удаляем старые контентные слайды 2..N ----------------------------
    # важно сбросить и rel, иначе старые части слайдов остаются достижимы и
    # при записи конфликтуют по имени с новыми (slideN.xml).
    xml_slides = prs.slides._sldIdLst
    for sld in list(xml_slides)[1:]:
        rId = sld.get(qn("r:id"))
        prs.part.drop_rel(rId)
        xml_slides.remove(sld)

    # ---------------------------------------------------------------------
    # Слайд 2 — Актуальность
    s = new_slide(prs, "Актуальность")
    bullets(s, 0.6, 1.95, 7.2, 4.8, [
        "IT-мероприятий очень много: конференции, митапы, вебинары, "
        "хакатоны идут десятками в неделю.",
        "Анонсы разбросаны по сайтам, агрегаторам и Telegram-каналам — "
        "нет единой точки входа.",
        "Отфильтровать релевантное по теме, уровню, формату и городу — "
        "ручная рутина, отнимающая время.",
        "Классические афиши не знают карьерной цели пользователя и его "
        "истории интересов.",
        "Растёт спрос на персонализацию: лента «под меня», а не общий список.",
    ], size=16, gap=12)
    card(s, 8.2, 1.95, 4.6, 1.45, "Проблема",
         ["Релевантные IT-события теряются в информационном шуме "
          "десятков источников."])
    card(s, 8.2, 3.6, 4.6, 1.55, "Решение",
         ["Один Telegram-бот собирает события из 6 источников и строит "
          "ленту по 9 признакам с объяснением «почему именно это»."],
         fill=RGBColor(0xE3, 0xF0, 0xE6))
    card(s, 8.2, 5.35, 4.6, 1.45, "Отличие",
         ["Учитываем не только темы, но и карьерную цель и историю реакций "
          "пользователя."], fill=RGBColor(0xFD, 0xEF, 0xE3))

    # ---------------------------------------------------------------------
    # Слайд 3 — Объект и предмет
    s = new_slide(prs, "Объект и предмет исследования")
    card(s, 0.7, 2.2, 5.8, 3.2, "Объект исследования",
         ["Процессы агрегации информации об IT-мероприятиях и "
          "построения персонализированных рекомендаций для "
          "пользователей."])
    card(s, 6.9, 2.2, 5.8, 3.2, "Предмет исследования",
         ["Программная система, объединяющая сбор и нормализацию "
          "событий, гибридный рекомендатель и мультиагентного "
          "AI-копилота вокруг общей базы данных."],
         fill=RGBColor(0xE3, 0xF0, 0xE6))

    # ---------------------------------------------------------------------
    # Слайд 4 — Цель и задачи
    s = new_slide(prs, "Цель и задачи")
    card(s, 0.6, 1.95, 5.5, 3.3, "Цель",
         ["Разработать систему, которая автоматически собирает "
          "анонсы IT-мероприятий из множества источников, "
          "нормализует их и строит для каждого пользователя "
          "персональную ленту рекомендаций с понятным "
          "объяснением выбора."])
    bullets(s, 6.4, 1.7, 6.4, 5.2, [
        "Анализ предметной области и подходов к рекомендациям",
        "Проектирование архитектуры (API, бот, планировщик)",
        "Сбор и AI-нормализация событий из 6 источников",
        "Реализация гибридного рекомендатора (9 компонент)",
        "Разработка Telegram-интерфейса и AI-копилота",
        "Тестирование и оценка качества рекомендаций",
    ], size=16, gap=14)
    tb = add_textbox(s, 6.4, 1.0, 4, 0.6)
    p = _clear(tb.text_frame); r = p.add_run(); r.text = "Задачи"
    _set_font(r, 20, bold=True, color=ORANGE)

    # ---------------------------------------------------------------------
    # Слайд 5 — Проблемы (овалы)
    s = new_slide(prs)
    # центральный овал
    def oval(l, t, w, h, text, fill, size=14, tcolor=WHITE, bold=False):
        o = s.shapes.add_shape(9, Inches(l), Inches(t), Inches(w), Inches(h))
        o.fill.solid(); o.fill.fore_color.rgb = fill
        o.line.color.rgb = WHITE; o.line.width = Pt(1.25)
        o.shadow.inherit = False
        tf = o.text_frame; tf.word_wrap = True
        p = _clear(tf); p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = text
        _set_font(r, size, bold=bold, color=tcolor)
        return o
    oval(4.42, 3.05, 4.5, 1.5, "Проблемы", NAVY, size=27, bold=True)
    oval(0.5, 1.45, 3.6, 1.45, "Фрагментированность источников событий", BLUE)
    oval(0.65, 4.7, 3.6, 1.45, "Информационный шум и дубли анонсов", BLUE)
    oval(4.9, 5.5, 3.55, 1.45, "Нет персонализации под уровень и цель", BLUE)
    oval(9.2, 1.45, 3.6, 1.45, "Рекомендации без объяснения выбора", BLUE)
    oval(9.05, 4.7, 3.6, 1.45, "Ручная фильтрация отнимает время", BLUE)

    # ---------------------------------------------------------------------
    # Слайд 6 — Анализ подходов
    s = new_slide(prs, "Анализ подходов к рекомендациям")
    data = [
        ["Подход", "Преимущества", "Недостатки", "В EventMind"],
        ["Контентный\n(rule-based)", "Работает при малом числе "
         "пользователей, объясним", "Ограниченное разнообразие",
         "Базовый rule + cosine"],
        ["Коллаборативная\nфильтрация", "Скрытые закономерности, "
         "серендипити", "Холодный старт, нужны объёмы",
         "LightGCN (эксперим.)"],
        ["Семантический\n(embeddings)", "Учёт смысла, многоязычность",
         "Затраты на векторы", "MiniLM + pgvector"],
        ["Контекстный\nбандит", "Баланс exploration/exploitation",
         "Настройка признаков", "LinUCB поверх hybrid"],
        ["Гибридный\nподход", "Точность, устойчивость к "
         "холодному старту", "Сложность настройки весов",
         "Основной алгоритм"],
    ]
    add_table(s, data, 0.55, 1.95, 12.25, 5.0,
              col_widths=[2.4, 4.0, 3.05, 2.8], body_size=11.5)
    caption(s, "Гибрид объединяет сильные стороны подходов и снимает "
               "холодный старт — выбран основным алгоритмом.")

    # ---------------------------------------------------------------------
    # Слайд 7 — Use case
    s = new_slide(prs, "Диаграмма вариантов использования")
    add_image_fit(s, DIAGRAMS / "01_use_case.png", 0.6, 1.85, 5.6, 5.15)
    bullets(s, 6.6, 2.1, 6.2, 4.8, [
        "Настройка профиля: интересы, уровень, формат, город, цель",
        "Просмотр персональной ленты рекомендаций",
        "Обратная связь: 👍 / 👎 / ⭐ — лента адаптируется",
        "Объяснение «❓ Почему» и «📖 Подробнее» по событию",
        "Семантический поиск событий обычным языком",
        "Диалог с AI-копилотом: план развития под цель",
    ], size=15, gap=13)

    # ---------------------------------------------------------------------
    # Слайд 8 — Бизнес-процесс
    s = new_slide(prs, "Бизнес-процесс системы")
    add_image_fit(s, DIAGRAMS / "02_business_process.png", 0.6, 1.85, 12.1, 5.15)
    caption(s, "От сбора и нормализации событий до доставки "
               "персональной ленты и обработки обратной связи.")

    # ---------------------------------------------------------------------
    # Слайд 9 — Архитектура C4
    s = new_slide(prs, "Архитектура системы")
    add_image_fit(s, DIAGRAMS / "03_c4_containers.png", 0.5, 1.85, 8.4, 5.15)
    bullets(s, 9.1, 1.95, 3.8, 5.0, [
        ("API — REST на FastAPI", 0),
        ("Bot — Telegram (aiogram 3)", 0),
        ("Scheduler — фоновые джобы", 0),
        ("Общая БД: PostgreSQL + pgvector", 0),
        ("LLM-провайдеры (Gemini, Groq)", 0),
        ("Три независимых процесса вокруг общей базы", 0),
    ], size=13.5, gap=10)
    caption(s, "Модульная схема на уровне контейнеров (C4).")

    # ---------------------------------------------------------------------
    # Слайд 10 — ER
    s = new_slide(prs, "Модель данных")
    add_image_fit(s, DIAGRAMS / "04_er_diagram.png", 0.6, 1.85, 12.1, 5.15)
    caption(s, "Пользователи, события, взаимодействия, embedding'и, "
               "состояние бандита и долговременная память.")

    # ---------------------------------------------------------------------
    # Слайд 11 — Технологический стек
    s = new_slide(prs, "Выбор средств реализации")
    data = [
        ["Компонент", "Технология", "Назначение"],
        ["Язык", "Python 3.12", "Весь стек: API, бот, ML"],
        ["API", "FastAPI + Uvicorn", "REST-слой, OpenAPI на /docs"],
        ["Бот", "aiogram 3", "Telegram-интерфейс, FSM, роутеры"],
        ["БД", "PostgreSQL + pgvector", "Данные + семантический поиск"],
        ["ORM / миграции", "SQLAlchemy 2.0 + Alembic", "Модели и версии схемы"],
        ["Эмбеддинги", "sentence-transformers (MiniLM)", "384-мерные векторы, рус."],
        ["AI-агенты", "LangGraph + LangChain", "Supervisor-Worker граф"],
        ["LLM", "Gemini → Groq 70b → Groq 8b", "Нормализация, объяснения, копилот"],
        ["Планировщик", "APScheduler", "Дайджест, ingestion, backfill"],
    ]
    add_table(s, data, 0.55, 1.9, 12.25, 5.1,
              col_widths=[2.6, 4.3, 5.35], body_size=12)

    # ---------------------------------------------------------------------
    # Слайд 12 — 9 компонент рекомендатора
    s = new_slide(prs, "Гибридный рекомендатель: 9 компонент")
    data = [
        ["Компонент", "Парадигма / источник", "Назначение"],
        ["rule", "rule-based, профиль", "Совпадение явных предпочтений"],
        ["cosine", "content-based, embeddings", "Семантическая близость"],
        ["bayesian", "Thompson sampling", "Статистика по темам с затуханием"],
        ["quality", "LLM-оценка 1–10", "Качество описания и источника"],
        ["hype", "LLM-оценка 1–10", "Актуальность темы сейчас"],
        ["freshness", "exp-decay по дате", "Свежесть события"],
        ["skill_gap", "goal-aware", "Соответствие карьерной цели"],
        ["bandit", "LinUCB contextual", "Баланс exploration/exploitation"],
        ["gnn", "LightGCN collaborative", "Коллаборативный сигнал (эксперим.)"],
    ]
    add_table(s, data, 0.55, 1.85, 9.0, 5.15,
              col_widths=[1.9, 3.5, 3.6], body_size=11)
    bullets(s, 9.8, 2.0, 3.2, 5.0, [
        ("Веса задаются конфигом", 0),
        ("MMR-rerank (λ=0.7) для разнообразия", 0),
        ("Series anti-flood: один выпуск серии", 0),
        ("Каждая компонента в try/except — сбой не ломает выдачу", 0),
        ("TTL-кэш выдачи 15 мин", 0),
    ], size=12.5, gap=10)

    # ---------------------------------------------------------------------
    # Слайд 13 — Sequence рекомендации
    s = new_slide(prs, "Как строится рекомендация")
    add_image_fit(s, DIAGRAMS / "05_sequence_recommend.png", 0.6, 1.85, 12.1, 5.1)
    caption(s, "GET /recommendations → hybrid отбирает top-N → один "
               "LLM-вызов пишет объяснения батчем (RAG, без галлюцинаций).")

    # ---------------------------------------------------------------------
    # Слайд 14 — Нормализация ingestion
    s = new_slide(prs, "Сбор и нормализация событий")
    add_image_fit(s, DIAGRAMS / "06_activity_normalization.png", 0.5, 1.85, 8.6, 5.1)
    bullets(s, 9.3, 1.95, 3.6, 5.0, [
        ("6 источников: habr, rss, kudago, luma, meetup, telegram", 0),
        ("source → raw_events", 0),
        ("AI-нормализация + Pydantic-валидация", 0),
        ("Строгая enum- и ISO-date валидация", 0),
        ("pgvector-дедуп (cosine ≥ 0.92)", 0),
        ("Идемпотентный повторный сбор", 0),
    ], size=12.5, gap=9)
    caption(s, "Батчевая нормализация с адаптивным размером чанка.")

    # ---------------------------------------------------------------------
    # Слайд 15 — AI-Copilot
    s = new_slide(prs, "AI-копилот: Supervisor-Worker")
    add_image_fit(s, DIAGRAMS / "07_copilot_graph.png", 0.5, 1.85, 8.4, 5.1)
    bullets(s, 9.0, 1.95, 3.9, 5.0, [
        ("Граф LangGraph: retrieve → supervisor → specialist → finalize", 0),
        ("5 специалистов: recommendation, career_coach, roadmap, "
         "explainer, summary", 0),
        ("6 function-calling tools", 0),
        ("Мульти-туровый диалог + long-term память", 0),
        ("Явный, тестируемый граф — не «магия»", 0),
    ], size=12.5, gap=9)

    # ---------------------------------------------------------------------
    # Слайд 16 — LLM-цепочка и надёжность
    s = new_slide(prs, "LLM-цепочка и надёжность")
    card(s, 0.6, 1.95, 6.0, 3.4, "Цепочка провайдеров",
         ["1.  Gemini — primary (REST-транспорт, автопроба модели)",
          "2.  Groq llama-3.3-70b — fallback",
          "3.  Groq llama-3.1-8b — last-resort",
          "",
          "Circuit-breaker: 5 фейлов подряд → cooldown 120 с.",
          "Per-provider cooldown: 2 фейла → skip на 10 мин."])
    bullets(s, 6.9, 2.0, 6.0, 4.8, [
        ("Три уровня graceful-degradation:", 0),
        ("LLM → следующий провайдер цепочки", 1),
        ("hybrid → rule-only выдача при сбое", 1),
        ("Copilot → сохранение сессии, «AI временно недоступен»", 1),
        ("X-API-Key shared-secret + request-логирование", 0),
        ("Prompt-injection sanitize пользовательского ввода", 0),
        ("Read-only hot-path + TTL-кэш рекомендаций", 0),
    ], size=14, gap=10)

    # ---------------------------------------------------------------------
    # Слайд 17 — Оценка качества
    s = new_slide(prs, "Оценка качества")
    t1 = [
        ["Метрика", "k", "rule", "hybrid", "bayes"],
        ["Recall@k", "5", "0,50", "0,65", "0,65"],
        ["Recall@k", "10", "0,80", "0,85", "0,85"],
        ["nDCG@k", "5", "0,26", "0,38", "0,38"],
        ["nDCG@k", "10", "0,36", "0,44", "0,45"],
    ]
    add_table(s, t1, 0.6, 2.0, 6.0, 2.7,
              col_widths=[1.7, 0.8, 1.1, 1.3, 1.1], body_size=12)
    tb = add_textbox(s, 0.6, 1.6, 6, 0.4)
    p = _clear(tb.text_frame); r = p.add_run()
    r.text = "Leave-one-out (Recall@k / nDCG@k)"
    _set_font(r, 13, bold=True, color=ORANGE)

    t2 = [
        ["Алгоритм", "relevance", "diversity"],
        ["rule", "4,33", "2,53"],
        ["hybrid", "4,40", "2,10"],
        ["bayesian", "4,40", "2,03"],
    ]
    add_table(s, t2, 7.0, 2.0, 5.6, 2.4,
              col_widths=[2.4, 1.6, 1.6], body_size=12)
    tb = add_textbox(s, 7.0, 1.6, 6, 0.4)
    p = _clear(tb.text_frame); r = p.add_run()
    r.text = "LLM-судья (оценка 1–5)"
    _set_font(r, 13, bold=True, color=ORANGE)

    bullets(s, 0.6, 5.0, 12.2, 1.9, [
        "Гибрид превосходит rule-only по Recall@5 (0,65 против 0,50) "
        "и nDCG@5 (0,38 против 0,26).",
        "369 автотестов в tests/ (scoring, bayesian, bandit, gnn, "
        "memory, ingestion, copilot, security).",
        "Воспроизводимые скрипты оценки с фиксированным seed=42.",
    ], size=14, gap=8)

    # ---------------------------------------------------------------------
    # Слайд 18 — Заключение
    s = new_slide(prs, "Заключение")
    bullets(s, 0.6, 1.9, 6.1, 5.0, [
        "Все поставленные задачи выполнены.",
        "Собрана рабочая система: API + бот + планировщик вокруг "
        "общей БД (PostgreSQL + pgvector).",
        "Реализован гибридный рекомендатель из 9 компонент с "
        "объяснениями и AI-копилот на LangGraph.",
        "Сбор из 6 источников с AI-нормализацией и дедупом.",
        "Качество подтверждено метриками и 369 тестами.",
    ], size=15.5, gap=11)
    card(s, 7.0, 1.9, 5.8, 3.5, "Направления развития",
         ["• Расширение списка источников событий",
          "• Включение GNN-сигнала на большем датасете",
          "• Переработка UX AI-копилота в боте",
          "• A/B-тестирование весов рекомендатора",
          "• Развитие в магистерскую работу"],
         fill=RGBColor(0xFD, 0xEF, 0xE3), title_color=ORANGE)

    # ---------------------------------------------------------------------
    # Слайд 19 — Спасибо
    s = prs.slides.add_slide(prs.slide_layouts[1])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    add_footer(s)
    box = s.shapes.add_shape(1, Inches(1.6), Inches(2.3), Inches(10.1), Inches(2.2))
    box.fill.solid(); box.fill.fore_color.rgb = NAVY
    box.line.fill.background(); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = _clear(tf); p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = "Благодарю за внимание!"
    _set_font(r, 40, bold=True, color=WHITE)
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r = p2.add_run(); r.text = "Готов ответить на ваши вопросы"
    _set_font(r, 20, color=RGBColor(0xCF, 0xDA, 0xEE))

    tb = add_textbox(s, 1.6, 5.0, 10.1, 1.6)
    tf = tb.text_frame
    p = _clear(tf); p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = "Белов Егор Александрович"
    _set_font(r, 16, bold=True, color=NAVY)
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r = p2.add_run()
    r.text = "НИУ ВШЭ — Пермь · Программная инженерия"
    _set_font(r, 14, color=GREY)
    p3 = tf.add_paragraph(); p3.alignment = PP_ALIGN.CENTER
    r = p3.add_run(); r.text = "Проект: EventMind"
    _set_font(r, 14, color=GREY)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    print(f"saved: {out}  ({len(prs.slides._sldIdLst)} слайдов)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default="docs/Презентация_EventMind.pptx")
    args = ap.parse_args()
    build(args.template, args.out)
