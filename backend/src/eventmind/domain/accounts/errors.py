"""Доменные ошибки аккаунтов (без привязки к HTTP/фреймворкам).

Транспортный слой (interfaces/api) мапит их в HTTP-статусы.
"""
from __future__ import annotations


class DomainError(Exception):
    """Базовая доменная ошибка."""


class EmailAlreadyRegistered(DomainError):
    """Аккаунт с таким email уже существует."""


class InvalidCredentials(DomainError):
    """Неверный email или пароль (единое сообщение — не раскрываем, что именно)."""


class UserNotFound(DomainError):
    """Пользователь не найден."""


class AccountInactive(DomainError):
    """Аккаунт деактивирован."""


class EmailNotVerified(DomainError):
    """Email не подтверждён — действие запрещено."""


class ChannelAlreadyLinked(DomainError):
    """Канал такого типа уже привязан к аккаунту."""


class TokenInvalidOrExpired(DomainError):
    """Одноразовый токен не найден, уже использован или истёк."""
