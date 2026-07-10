"""Параметры use-case'ов аккаунтов (TTL одноразовых токенов)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountsConfig:
    email_verification_ttl_seconds: int = 24 * 3600
    password_reset_ttl_seconds: int = 3600
    telegram_link_ttl_seconds: int = 15 * 60
