"""Инфраструктурный слой: адаптеры портов `application`.

async-SQLAlchemy-репозитории, Redis-кэш/очередь (arq), LLM Gateway,
EmbeddingProvider, outbox-relay, NotificationChannel'ы, HTTP-клиенты
источников, телеметрия. Импортирует `application` и `domain`.
"""
