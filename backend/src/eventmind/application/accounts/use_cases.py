"""Use-case'ы аккаунтов.

Каждый use-case открывает свежий `UnitOfWork`, работает через порты и
коммитит одной транзакцией (изменения агрегатов + доменные события в outbox).
После успешного commit'а ставит обработку outbox в очередь (`process_outbox`),
чтобы письма ушли асинхронно через worker.
"""
from __future__ import annotations

from datetime import timedelta

from eventmind.application.accounts.config import AccountsConfig
from eventmind.application.ports.queue import TaskQueue
from eventmind.application.ports.security import (
    Clock,
    PasswordHasher,
    SecretTokenGenerator,
)
from eventmind.application.ports.uow import UnitOfWorkFactory
from eventmind.domain.accounts.entities import (
    NotificationPreference,
    OneTimeToken,
    User,
    UserChannel,
)
from eventmind.domain.accounts.errors import (
    ChannelAlreadyLinked,
    EmailAlreadyRegistered,
    InvalidCredentials,
    TokenInvalidOrExpired,
    UserNotFound,
)
from eventmind.domain.accounts.events import PasswordResetRequested, UserRegistered
from eventmind.domain.accounts.value_objects import ChannelType, Email, TokenPurpose

# Имя фоновой задачи, обрабатывающей outbox (реализована в worker'е).
PROCESS_OUTBOX_TASK = "process_outbox"


class RegisterUser:
    """Регистрация аккаунта email+пароль + письмо верификации через outbox."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        token_generator: SecretTokenGenerator,
        clock: Clock,
        task_queue: TaskQueue,
        config: AccountsConfig,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = password_hasher
        self._tokens = token_generator
        self._clock = clock
        self._queue = task_queue
        self._config = config

    async def execute(self, *, email: str, password: str) -> User:
        normalized = str(Email(email))
        async with self._uow_factory() as uow:
            if await uow.users.get_by_email(normalized) is not None:
                raise EmailAlreadyRegistered(normalized)

            user = await uow.users.add(
                User(email=normalized, password_hash=self._hasher.hash(password))
            )
            assert user.id is not None
            await uow.channels.add(
                UserChannel(user_id=user.id, type=ChannelType.EMAIL, address=normalized)
            )
            await uow.preferences.add(NotificationPreference(user_id=user.id))

            raw, token_hash = self._tokens.generate()
            expires_at = self._clock.now() + timedelta(
                seconds=self._config.email_verification_ttl_seconds
            )
            await uow.tokens.add(
                OneTimeToken(
                    user_id=user.id,
                    purpose=TokenPurpose.EMAIL_VERIFICATION.value,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
            )
            uow.add_event(
                UserRegistered(user_id=user.id, email=normalized, verification_token=raw)
            )
            await uow.commit()

        await self._queue.enqueue(PROCESS_OUTBOX_TASK)
        return user


class VerifyEmail:
    """Подтверждение email по одноразовому токену."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        token_generator: SecretTokenGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = token_generator
        self._clock = clock

    async def execute(self, *, raw_token: str) -> None:
        token_hash = self._tokens.hash(raw_token)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            token = await uow.tokens.get_by_hash(
                TokenPurpose.EMAIL_VERIFICATION.value, token_hash
            )
            if token is None or not token.is_usable(now=now):
                raise TokenInvalidOrExpired()
            assert token.user_id is not None

            user = await uow.users.get_by_id(token.user_id)
            if user is None or user.id is None:
                raise UserNotFound()
            user.mark_email_verified()
            await uow.users.update(user)

            channel = await uow.channels.get_by_user_and_type(user.id, ChannelType.EMAIL)
            if channel is not None:
                channel.mark_verified()
                await uow.channels.update(channel)

            token.consume(now=now)
            await uow.tokens.update(token)
            await uow.commit()


class AuthenticateUser:
    """Проверка учётных данных (email+пароль). Выдачу JWT делает интерфейс."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, password_hasher: PasswordHasher
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = password_hasher

    async def execute(self, *, email: str, password: str) -> User:
        normalized = str(Email(email))
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(normalized)
            # Единый путь ошибки — не раскрываем, отсутствует ли аккаунт.
            if user is None or user.password_hash is None:
                raise InvalidCredentials()
            if not self._hasher.verify(password, user.password_hash):
                raise InvalidCredentials()
            user.ensure_can_login()

            # Прозрачный upgrade хеша при смене параметров argon2.
            if self._hasher.needs_rehash(user.password_hash):
                user.set_password_hash(self._hasher.hash(password))
                await uow.users.update(user)
                await uow.commit()
            return user


class RequestPasswordReset:
    """Запрос сброса пароля. Не раскрывает, существует ли email (анти-энумерация)."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        token_generator: SecretTokenGenerator,
        clock: Clock,
        task_queue: TaskQueue,
        config: AccountsConfig,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = token_generator
        self._clock = clock
        self._queue = task_queue
        self._config = config

    async def execute(self, *, email: str) -> None:
        try:
            normalized = str(Email(email))
        except ValueError:
            return  # молча выходим — не раскрываем валидность
        enqueued = False
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(normalized)
            if user is not None and user.id is not None:
                raw, token_hash = self._tokens.generate()
                expires_at = self._clock.now() + timedelta(
                    seconds=self._config.password_reset_ttl_seconds
                )
                await uow.tokens.add(
                    OneTimeToken(
                        user_id=user.id,
                        purpose=TokenPurpose.PASSWORD_RESET.value,
                        token_hash=token_hash,
                        expires_at=expires_at,
                    )
                )
                uow.add_event(
                    PasswordResetRequested(
                        user_id=user.id, email=normalized, reset_token=raw
                    )
                )
                enqueued = True
            await uow.commit()

        if enqueued:
            await self._queue.enqueue(PROCESS_OUTBOX_TASK)


class ResetPassword:
    """Смена пароля по токену сброса."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        token_generator: SecretTokenGenerator,
        password_hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = token_generator
        self._hasher = password_hasher
        self._clock = clock

    async def execute(self, *, raw_token: str, new_password: str) -> None:
        token_hash = self._tokens.hash(raw_token)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            token = await uow.tokens.get_by_hash(
                TokenPurpose.PASSWORD_RESET.value, token_hash
            )
            if token is None or not token.is_usable(now=now):
                raise TokenInvalidOrExpired()
            assert token.user_id is not None

            user = await uow.users.get_by_id(token.user_id)
            if user is None:
                raise UserNotFound()
            user.set_password_hash(self._hasher.hash(new_password))
            await uow.users.update(user)

            token.consume(now=now)
            await uow.tokens.update(token)
            await uow.commit()


class CreateTelegramLinkToken:
    """Сгенерировать одноразовый токен привязки Telegram (для deep-link)."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        token_generator: SecretTokenGenerator,
        clock: Clock,
        config: AccountsConfig,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = token_generator
        self._clock = clock
        self._config = config

    async def execute(self, *, user_id: int) -> str:
        async with self._uow_factory() as uow:
            raw, token_hash = self._tokens.generate()
            expires_at = self._clock.now() + timedelta(
                seconds=self._config.telegram_link_ttl_seconds
            )
            await uow.tokens.add(
                OneTimeToken(
                    user_id=user_id,
                    purpose=TokenPurpose.TELEGRAM_LINK.value,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
            )
            await uow.commit()
        return raw


class ConfirmTelegramLink:
    """Связать chat_id с аккаунтом по токену (вызывается ботом через внутренний API)."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        token_generator: SecretTokenGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = token_generator
        self._clock = clock

    async def execute(self, *, raw_token: str, chat_id: str) -> int:
        token_hash = self._tokens.hash(raw_token)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            token = await uow.tokens.get_by_hash(
                TokenPurpose.TELEGRAM_LINK.value, token_hash
            )
            if token is None or not token.is_usable(now=now):
                raise TokenInvalidOrExpired()
            assert token.user_id is not None
            user_id = token.user_id

            # chat_id уже привязан к другому аккаунту? — запрещаем.
            existing = await uow.channels.get_by_type_and_address(
                ChannelType.TELEGRAM, chat_id
            )
            if existing is not None and existing.user_id != user_id:
                raise ChannelAlreadyLinked()

            channel = await uow.channels.get_by_user_and_type(user_id, ChannelType.TELEGRAM)
            if channel is None:
                channel = UserChannel(
                    user_id=user_id,
                    type=ChannelType.TELEGRAM,
                    address=chat_id,
                    verified=True,
                )
                await uow.channels.add(channel)
            else:
                channel.address = chat_id
                channel.mark_verified()
                channel.enabled = True
                await uow.channels.update(channel)

            pref = await uow.preferences.get_by_user(user_id)
            if pref is not None:
                pref.telegram_enabled = True
                await uow.preferences.update(pref)

            token.consume(now=now)
            await uow.tokens.update(token)
            await uow.commit()
        return user_id
