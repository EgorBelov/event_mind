"""Unit: argon2-хешер, JWT-сервис, генератор одноразовых токенов."""
from __future__ import annotations

import time

import jwt
import pytest

from eventmind.infrastructure.security.jwt import JwtTokenService
from eventmind.infrastructure.security.password import Argon2PasswordHasher
from eventmind.infrastructure.security.tokens import Sha256SecretTokenGenerator


def test_argon2_hash_and_verify() -> None:
    hasher = Argon2PasswordHasher()
    h = hasher.hash("s3cret-password")
    assert h != "s3cret-password"
    assert hasher.verify("s3cret-password", h)
    assert not hasher.verify("wrong", h)


def test_argon2_verify_rejects_garbage_hash() -> None:
    hasher = Argon2PasswordHasher()
    assert not hasher.verify("x", "not-a-valid-hash")


def test_jwt_access_and_refresh_roundtrip() -> None:
    svc = JwtTokenService("s" * 40)
    access = svc.create_access_token("42")
    refresh = svc.create_refresh_token("42")
    a = svc.decode(access)
    r = svc.decode(refresh)
    assert a["sub"] == "42" and a["type"] == "access"
    assert r["sub"] == "42" and r["type"] == "refresh"


def test_jwt_empty_secret_rejected() -> None:
    with pytest.raises(ValueError):
        JwtTokenService("")


def test_jwt_expired_token_raises() -> None:
    svc = JwtTokenService("s" * 40, access_ttl_seconds=-1)
    token = svc.create_access_token("1")
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        svc.decode(token)


def test_jwt_wrong_secret_rejected() -> None:
    token = JwtTokenService("a" * 40).create_access_token("1")
    with pytest.raises(jwt.InvalidTokenError):
        JwtTokenService("b" * 40).decode(token)


def test_secret_token_generator_hash_is_deterministic_and_hides_raw() -> None:
    gen = Sha256SecretTokenGenerator()
    raw, token_hash = gen.generate()
    assert raw != token_hash
    assert gen.hash(raw) == token_hash  # тот же raw → тот же хеш
    assert len(token_hash) == 64  # sha256 hex
