"""Доменное ядро событий: сущности Event/RawEvent, таксономия, series-slug.

Чистые функции канонизации (город/slug) и распознавания серии портированы из
v1 (`legacy/app/core/topics.py`, `legacy/app/recommender/series.py`) без
привязки к БД. DB-зависимые лукапы словаря живут в application/infrastructure.
"""
