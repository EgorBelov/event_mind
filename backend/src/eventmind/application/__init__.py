"""Прикладной слой: use-case'ы и порты (интерфейсы к внешнему миру).

Порты (репозитории, `UnitOfWork`, `LLMGateway`, `EmbeddingProvider`,
`NotificationChannel`, `TaskQueue`, `Cache`) объявляются здесь и
реализуются в `eventmind.infrastructure`. Импортирует только `domain`.
"""
