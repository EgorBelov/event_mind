"""EventMind v2 — гексагональный модульный монолит.

Слои (правило зависимостей `interfaces → application → domain`,
`infrastructure` реализует порты `application`, `domain` наружу не импортирует):

- :mod:`eventmind.domain`         — чистые сущности/VO/доменные сервисы, без I/O.
- :mod:`eventmind.application`     — use-case'ы + порты (репозитории, шины, gateway'и).
- :mod:`eventmind.infrastructure` — адаптеры портов: async-SQLAlchemy, Redis, LLM, каналы.
- :mod:`eventmind.interfaces`      — входные адаптеры: FastAPI, aiogram, worker, scheduler.
"""

__version__ = "2.0.0"
