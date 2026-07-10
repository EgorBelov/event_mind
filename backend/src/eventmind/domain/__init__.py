"""Доменный слой: чистые сущности, value-objects, доменные сервисы.

Без I/O и фреймворков. Наружу (application/infrastructure/interfaces,
sqlalchemy, fastapi, httpx, redis) не импортирует — это гарантирует
import-linter в CI. Наполняется агрегатами начиная с M1.
"""
