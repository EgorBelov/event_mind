# Локальный запуск EventMind — пошагово

Гайд «с нуля»: что установить, что вписать в `.env`, откуда взять ключи и в
каком порядке запускать. Есть два режима — выбери один.

- **Режим A — всё в Docker** (`make up`). Рекомендуется: одна команда, миграции
  применяются автоматически. Нужен только Docker.
- **Режим B — backend/web на хосте** (hot-reload для разработки), а
  Postgres/Redis/Mailhog — в Docker.

---

## 0. Предпосылки

| Инструмент | Зачем | Проверка |
|---|---|---|
| **Docker + Docker Compose** | dev-стек (обязательно для режима A) | `docker --version` |
| **uv** | пакетный менеджер Python (режим B) | `uv --version` · [install](https://docs.astral.sh/uv/getting-started/installation/) |
| **Node 20+** | веб-клиент на хосте (режим B) | `node --version` |
| **git** | клонирование | `git --version` |

uv сам поставит Python 3.12 — отдельно ставить питон не нужно.

```bash
git clone https://github.com/EgorBelov/event_mind.git
cd event_mind
cp .env.example .env      # дальше редактируем .env
```

---

## 1. Ключи: что нужно и где взять

**Чтобы просто поднять систему, войти/зарегистрироваться и полистать веб —
ключи НЕ нужны.** В dev всё работает с пустыми секретами (JWT эфемерный,
API-key в open-mode, письма ловит Mailhog). Ключи нужны для «умных» функций:

| Ключ в `.env` | Для чего | Обязателен? | Где взять |
|---|---|---|---|
| `GROQ_API_KEY` | LLM-нормализация событий, NL-поиск, оценки quality/hype | желательно **хотя бы один из двух** | [console.groq.com](https://console.groq.com) → *API Keys* → *Create*. Бесплатно, мгновенно, щедрый лимит. **Рекомендую начать с него.** |
| `GOOGLE_API_KEY` | то же (primary-звено LLM-цепочки — Gemini) | — | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (Google AI Studio) → *Create API key*. Бесплатный tier с дневными лимитами. |
| `BOT_TOKEN` | Telegram-бот (опциональный процесс) | только для бота | Написать [@BotFather](https://t.me/BotFather) → `/newbot` → получить токен. `TELEGRAM_BOT_USERNAME` = username бота (без `@`). |
| `GOOGLE_OAUTH_CLIENT_ID` | вход «Sign in with Google» | нет (можно пропустить) | Google Cloud Console → *APIs & Services → Credentials → OAuth client ID (Web)*. |

> LLM-цепочка: **Gemini → Groq-70b → Groq-8b** с fallback. Достаточно **одного**
> ключа. Без ключей LLM-функции деградируют: нормализация не создаёт события,
> NL-поиск падает в простой текстовый поиск — но auth/веб/лента работают.

**Почта в dev не требует ничего** — SMTP по умолчанию смотрит на Mailhog,
письма (верификация, сброс пароля) видно на http://localhost:8025.

---

## 2. Что вписать в `.env`

Минимальный dev-`.env` (скопирован из `.env.example`) можно оставить как есть и
только добавить LLM-ключ:

```dotenv
# --- достаточно для старта; допиши ключ, если нужен «умный» функционал ---
ENVIRONMENT=dev
LOG_JSON=false                 # человекочитаемые логи в dev

GROQ_API_KEY=gsk_...           # ← вставь свой (или GOOGLE_API_KEY)
# GOOGLE_API_KEY=AIza...

# опционально — Telegram-бот:
# BOT_TOKEN=123456:ABC...
# TELEGRAM_BOT_USERNAME=my_eventmind_bot
```

Поля, которые **в dev можно не трогать** (рабочие значения по умолчанию):

- `DATABASE_URL`, `REDIS_URL` — для `make up` их подставляет compose (хосты
  `postgres`/`redis` во внутренней сети). Менять нужно только в режиме B (см. ниже).
- `JWT_SECRET` пустой → на dev генерится эфемерный (токены живут до перезапуска).
- `API_SHARED_SECRET` пустой → open-mode (внутренние вызовы bot↔api без ключа).
- `SMTP_*` → Mailhog, без TLS.

> На **проде** обязательно задать `JWT_SECRET` и `API_SHARED_SECRET` (иначе
> процесс предупредит в логах), реальный SMTP и т.д. — см. `.env.example`.

---

## 3. Режим A — всё в Docker (рекомендуется)

```bash
make up
```

Что происходит: поднимаются `postgres(pgvector)` + `redis` + `mailhog`, затем
одноразовый сервис **`migrate`** прогоняет `alembic upgrade head` (схема БД
создаётся автоматически), после чего стартуют `api`, `worker`, `web`,
`prometheus`, `grafana`.

Открывай:

| Сервис | URL |
|---|---|
| API health | http://localhost:8000/health → `{"status":"ok"}` |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Веб-клиент | http://localhost:3000 |
| Mailhog (письма) | http://localhost:8025 |
| Grafana | http://localhost:3001 (admin / admin) |
| Prometheus | http://localhost:9090 |

**(Опц.) демо-данные** — засеять аккаунт и настройки:

```bash
docker compose -f deploy/docker-compose.yml run --rm api python -m eventmind.interfaces.cli.seed
```

**(Опц.) Telegram-бот** — отдельный профиль (нужен `BOT_TOKEN` в `.env`):

```bash
docker compose -f deploy/docker-compose.yml --profile bot up -d bot
```

Остановить: `make down` (данные сохраняются в volume'ах). Логи: `make logs`.

> ⚠️ Полный контентный рекомендер использует эмбеддинги (MiniLM, extra `ml` с
> torch), которые в базовый образ **не** ставятся ради лёгкости. Auth, веб,
> NL-поиск, дайджест, лента по quality/freshness работают; для cosine-близости
> по эмбеддингам подними backend на хосте с `--extra ml` (режим B) или добавь
> `--extra ml` в `backend/Dockerfile`.

---

## 4. Режим B — backend/web на хосте (hot-reload)

Инфраструктуру держим в Docker, а код — на хосте (удобно для разработки с
автоперезагрузкой).

### 4.1 Поднять только инфраструктуру

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis mailhog
```

Теперь БД доступна на `localhost:5432`, Redis на `localhost:6379`, Mailhog на
`localhost:1025` (SMTP) / `:8025` (UI).

### 4.2 Указать backend'у на localhost

В режиме B процессы читают `.env` из каталога `backend/`. Проще всего —
задать URL'ы через переменные окружения при запуске (значения указывают на
**localhost**, а не на compose-хосты):

```bash
export DATABASE_URL="postgresql+asyncpg://eventmind:eventmind@localhost:5432/eventmind"
export REDIS_URL="redis://localhost:6379/0"
export SMTP_HOST=localhost
export GROQ_API_KEY=gsk_...        # если нужен LLM
```

### 4.3 Backend: зависимости, миграции, запуск

```bash
cd backend
uv sync --extra dev                 # (+ --extra ml для эмбеддингов, --extra bot для бота)
uv run alembic upgrade head         # создать схему
uv run python -m eventmind.interfaces.cli.seed   # (опц.) демо-данные

# API (в одном терминале):
uv run uvicorn eventmind.interfaces.api.main:app --reload --port 8000

# worker очереди + cron (в другом терминале, из backend/, те же env):
uv run arq eventmind.interfaces.worker.main.WorkerSettings
```

`worker` нужен, чтобы уходили письма (outbox → очередь) и работал дайджест;
для простого просмотра ленты он не обязателен.

### 4.4 Web

```bash
cd web
npm install
API_BASE_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

`API_BASE_URL` говорит BFF-прокси Next.js, куда ходить за API server-side.

### 4.5 (Опц.) Telegram-бот на хосте

```bash
cd backend
API_INTERNAL_URL=http://localhost:8000 BOT_TOKEN=... uv run python -m eventmind.interfaces.bot.main
```

---

## 5. Проверка, что всё работает

1. `curl http://localhost:8000/health` → `{"status":"ok"}`; `.../ready` → 200
   (пингует Postgres+Redis).
2. Открой http://localhost:3000 → зарегистрируйся (email + пароль 8+ символов).
3. Письмо верификации — на http://localhost:8025 (Mailhog).
4. Залей события и построй ленту:
   ```bash
   # заголовок X-API-Key нужен, только если задан API_SHARED_SECRET
   curl -X POST "http://localhost:8000/api/v1/ingestion/load-all?limit=20"
   curl -X POST  http://localhost:8000/api/v1/ingestion/normalize      # нужен LLM-ключ
   ```
   затем в вебе — вкладка «Лента».

---

## 6. Частые проблемы

| Симптом | Причина / решение |
|---|---|
| `/ready` → 503 | Postgres/Redis не подняты или БД не мигрирована. В режиме A подожди `migrate`; в B — `alembic upgrade head`. |
| Лента пустая | Нет событий (сделай ingestion+normalize) или нет LLM-ключа для нормализации. |
| NL-поиск «тупит» | Нет `GROQ_API_KEY`/`GOOGLE_API_KEY` → фильтры не извлекаются, работает текстовый fallback. |
| Письма не приходят | Смотри Mailhog http://localhost:8025; в режиме B письма шлёт **worker** (запусти его). |
| `connection refused :5432` в режиме B | `DATABASE_URL` указывает на `postgres` вместо `localhost` — поправь (см. 4.2). |
| cosine-рекомендации нулевые | Не установлен extra `ml` (torch) — см. примечание в разделе 3. |
| Порт занят (8000/3000/5432…) | Освободи порт или поменяй маппинг в `deploy/docker-compose.yml`. |

---

## 7. Тесты и проверки (для разработки)

```bash
make lint          # ruff
make typecheck     # mypy (strict)
make imports       # границы гексагональных слоёв
make test-unit     # 155 unit-тестов (без Docker)
make test-integration   # 31 integration (testcontainers, нужен Docker)
make eval          # offline-eval рекомендера (seed=42)
```

Подробнее об архитектуре — [`ARCHITECTURE.md`](../ARCHITECTURE.md),
обзор проекта — [`README.md`](../README.md).
