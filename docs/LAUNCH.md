# EventMind — запуск с нуля

Пошаговая инструкция: что скачать, какие ключи получить, какие переменные
прописать и в каком порядке всё запускать. В конце — готовый **промпт для
Claude Code**, который проходит те же шаги сам.

Основная машина — **Windows 11, обычный PowerShell**. WSL как рабочая среда
**не нужен**: Docker Desktop использует WSL2 только внутри себя как движок, а
вы работаете в обычной Windows. Для macOS / Linux команды те же (в bash), плюс
есть `make`.

---

## Два режима

| Режим | Что где работает | Когда нужен |
|---|---|---|
| **A. Всё в Docker** (основной) | Postgres, Redis, Mailhog, миграции, api, worker, web, Prometheus, Grafana, бот — в контейнерах | Обычный запуск и демонстрация. На хосте нужны только Git и Docker Desktop |
| **B. Backend на хосте** | Инфраструктура (Postgres, Redis, Mailhog) — в Docker; api и worker — на хосте через `uv`; web — `npm run dev` | Тесты, offline-eval, отладка. **И пока не сделан P0 №1** — для эмбеддингов: в Docker-образ ML-зависимости ещё не ставятся, поэтому в режиме A у событий нет векторов и cosine-компонента рекомендера равна 0 |

---

## 0. Что скачать

Всё ставится через `winget` в PowerShell (или скачать установщик с сайта).

| Что | Зачем | Режим | Команда (Windows 11) |
|---|---|---|---|
| **Git** | клонировать репозиторий | A, B | `winget install -e --id Git.Git` |
| **Docker Desktop** | контейнеры | A, B | `winget install -e --id Docker.DockerDesktop` |
| **uv** | Python-зависимости backend; сам ставит Python 3.12 | B | `winget install -e --id astral-sh.uv` |
| **Node.js LTS** (22+) | web вне Docker | B | `winget install -e --id OpenJS.NodeJS.LTS` |
| **Claude Code** | разработка с помощником | по желанию | `irm https://claude.ai/install.ps1 \| iex` |
| k6 | нагрузочный смоук | по желанию | `winget install -e --id k6.k6` |

После установки Docker Desktop:
1. перезагрузить компьютер, если установщик попросит;
2. запустить Docker Desktop и дождаться статуса **Engine running**;
3. если Docker ругается на виртуализацию — включить её в BIOS/UEFI
   (Intel VT-x / AMD-V); компонент WSL2 установщик ставит сам.

Проверка в новом окне PowerShell:

```powershell
git --version
docker version          # должны быть и Client, и Server
docker compose version
uv --version            # режим B
node --version          # режим B
```

---

## 1. Клонировать репозиторий

```powershell
cd $HOME
git clone https://github.com/EgorBelov/event_mind.git
cd event_mind
```

Окончания строк: в репозитории лежит `.gitattributes` (`eol=lf`), поэтому Git
не превратит файлы в `CRLF`. Свой `.env` сохраняйте в редакторе с окончаниями
`LF` (в VS Code — внизу справа «LF»).

---

## 2. Получить ключи

| Ключ | Где взять | Нужен? |
|---|---|---|
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) → API Keys → Create; пополнить баланс | **Да** (основная LLM) |
| `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Нет — запасное звено цепочки |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | Нет — запасное звено цепочки |
| `BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | [@BotFather](https://t.me/BotFather) → `/newbot` → токен и имя бота (без `@`) | Для бота |
| `GOOGLE_OAUTH_CLIENT_ID` | [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) → OAuth client ID (Web), origin `http://localhost:3000` | Нет — вход через Google |
| SMTP Yandex / Mail.ru | пароль приложения в настройках почты | Нет — в dev письма ловит Mailhog |

Ключи никогда не коммитить: `.env` уже в `.gitignore`.

---

## 3. Заполнить `.env`

```powershell
Copy-Item .env.example .env
notepad .env        # или code .env
```

Сгенерировать секреты (по одному на каждую переменную):

```powershell
uv run --no-project python -c "import secrets; print(secrets.token_hex(32))"
```

Без `uv` — в PowerShell:
`-join ((1..32) | % { '{0:x2}' -f [Security.Cryptography.RandomNumberGenerator]::GetInt32(256) })`
(нужен PowerShell 7) или любой генератор паролей длиной 40+.

| Переменная | Значение для dev | Статус |
|---|---|---|
| `DEEPSEEK_API_KEY` | ключ из п. 2 | **обязательно** (хотя бы один LLM-ключ) |
| `DEEPSEEK_MODELS` | пусто → `deepseek-flash`; или `deepseek-flash,deepseek-v4-pro` | по желанию |
| `JWT_SECRET` | сгенерированный секрет | рекомендуется (пустой допустим только в dev) |
| `API_SHARED_SECRET` | сгенерированный секрет | **обязательно для бота**; пустой = внутренние эндпоинты открыты (только dev) |
| `BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | из @BotFather | для бота |
| `RSS_FEEDS` | URL RSS/Atom-лент через запятую; пусто — источник rss выключен (habr и kudago работают всегда) | по желанию |
| `GOOGLE_API_KEY`, `GROQ_API_KEY` | запасные LLM | по желанию |
| `GOOGLE_OAUTH_CLIENT_ID` | для входа через Google | по желанию |
| `LOG_JSON` | `false` — читаемые логи в dev | по желанию |
| `DATABASE_URL`, `REDIS_URL`, `SMTP_*`, `CORS_ORIGINS`, `PUBLIC_WEB_URL`, `API_INTERNAL_URL` | **оставить как в примере** — рассчитаны на Docker | не трогать |
| `GOOGLE_MODEL`, `NORMALIZE_BATCH_SIZE`, `MAX_NORMALIZE_RETRIES`, `OTEL_*` | тонкая настройка | не трогать |

`DATABASE_URL`, `REDIS_URL` и `API_INTERNAL_URL` для контейнеров compose всё
равно подставляет сам; для режима B их переопределяют в оболочке (п. 6).

---

## 4. Запустить стек (режим A)

В PowerShell удобно завести короткую функцию (действует до закрытия окна):

```powershell
function dc { docker compose -f deploy/docker-compose.yml @args }
```

Запуск (первый раз — сборка образов, 5–15 минут):

```powershell
dc up --build -d
dc ps
```

На macOS / Linux то же самое делает `make up`.

Проверка:

| Что | Адрес | Ожидаемо |
|---|---|---|
| API жив | http://localhost:8000/health | `200` |
| API готов (Postgres + Redis) | http://localhost:8000/ready | `200` |
| Документация API | http://localhost:8000/docs | Swagger |
| Веб | http://localhost:3000 | страница входа |
| Mailhog (письма) | http://localhost:8025 | интерфейс почты |
| Grafana | http://localhost:3001 | вход `admin` / `admin` |
| Prometheus | http://localhost:9090 | интерфейс |

```powershell
curl.exe -s http://localhost:8000/health
curl.exe -s http://localhost:8000/ready
```

(В PowerShell `curl` — псевдоним `Invoke-WebRequest`, поэтому именно `curl.exe`.)

Если что-то не поднялось: `dc logs -f --tail=100 api` (или `migrate`, `worker`, `web`).

---

## 5. Данные: демо-аккаунт и события

**Демо-аккаунт** (идемпотентно, повторный запуск не создаёт дубль):

```powershell
dc run --rm api python -m eventmind.interfaces.cli.seed
```

Вход в веб: `demo@eventmind.local` / `demo12345`.

**Загрузка событий.** Внутренние эндпоинты требуют заголовок `X-API-Key`
(если `API_SHARED_SECRET` задан):

```powershell
$secret = ((Select-String -Path .env -Pattern '^API_SHARED_SECRET=(.*)$').Matches[0].Groups[1].Value -split '#')[0].Trim()
$h = @{ "X-API-Key" = $secret }
$api = "http://localhost:8000/api/v1/ingestion"

# 1) забрать сырые события из источников (до 100 на источник)
Invoke-RestMethod -Method Post -Uri "$api/load-all?limit=50" -Headers $h

# 2) нормализовать через LLM (до 200 за вызов; повторять, пока остаются raw)
Invoke-RestMethod -Method Post -Uri "$api/normalize?limit=100" -Headers $h

# 3) статус
Invoke-RestMethod -Uri "$api/status" -Headers $h
```

Нормализация вызывает LLM на каждое событие — это занимает минуты. Упавшие
можно повторить: `POST $api/retry-failed`.

**Сколько событий и есть ли у них эмбеддинги:**

```powershell
dc exec postgres psql -U eventmind -c "SELECT count(*) AS events, count(embedding) AS with_embedding FROM events;"
```

В режиме A сейчас `with_embedding = 0` — это ожидаемо, см. «Два режима».

**Состояние LLM-цепочки** (какие звенья включены, cooldown):

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/admin/llm/status" -Headers $h
```

---

## 6. Режим B: backend на хосте (эмбеддинги, тесты, eval)

Нужны `uv` и Node.js (п. 0).

**6.1. Инфраструктура в Docker, приложения из Docker остановить:**

```powershell
dc up -d postgres redis mailhog migrate
dc stop api worker web
dc --profile bot stop bot     # если бот был запущен в Docker
```

**6.2. Зависимости backend** (первый раз долго: torch ≈ сотни МБ):

```powershell
cd backend
uv sync --extra dev --extra ml --extra bot
```

**6.3. Адреса для хоста.** В `.env` они рассчитаны на Docker-сеть;
переменные оболочки имеют приоритет над `--env-file`, поэтому переопределяем
их в окне PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://eventmind:eventmind@localhost:5432/eventmind"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:SMTP_HOST = "localhost"
$env:API_INTERNAL_URL = "http://localhost:8000"
```

**6.4. Запуск** — каждый процесс в своём окне PowerShell (в каждом окне
повторить п. 6.3 и `cd backend`):

```powershell
# окно 1 — API
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn eventmind.interfaces.api.main:app --reload --port 8000

# окно 2 — worker (outbox, дайджесты, фоновые задачи)
uv run --env-file ../.env arq eventmind.interfaces.worker.main.WorkerSettings

# окно 3 — бот (если задан BOT_TOKEN)
uv run --env-file ../.env python -m eventmind.interfaces.bot.main
```

Первый вызов эмбеддингов скачает модель MiniLM (~120 МБ) в кэш HuggingFace.
Предупреждение про симлинки на Windows безвредно; убрать:
`setx HF_HUB_DISABLE_SYMLINKS_WARNING 1`.

**6.5. Веб** (окно 4, из корня репозитория):

```powershell
cd web
npm install
$env:API_BASE_URL = "http://localhost:8000"
npm run dev            # http://localhost:3000
```

Дальше — п. 5 (загрузка и нормализация теми же запросами): теперь
нормализация идёт в API на хосте, и `with_embedding` растёт вместе с `events`.

---

## 7. Telegram-бот

Нужны `BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `API_SHARED_SECRET` в `.env`.

Режим A:

```powershell
dc --profile bot up -d bot
dc logs -f bot
```

Режим B — окно 3 из п. 6.4.

**Привязка аккаунта:** веб → **Настройки → Привязка Telegram** → открыть
выданную ссылку `t.me/<бот>?start=<токен>` → в боте `/feed`.

Сейчас бот работает только с привязанным веб-аккаунтом; регистрация прямо в
боте — задача B1 в `docs/PROJECT_REVIEW.md`.

---

## 8. Проверить, что всё работает

1. Зарегистрироваться в вебе (или войти демо-аккаунтом); письмо с
   подтверждением видно в Mailhog (http://localhost:8025).
2. Открыть ленту, поставить несколько 👍 / ⭐ / 👎.
3. Обновить ленту — порядок должен поменяться (кэш рекомендаций
   сбрасывается после каждой оценки).
4. Поиск обычной фразой: «онлайн конференции по AI в ноябре».
5. Бот: `/feed`, кнопки под карточками, свободный текст как поиск.

---

## 9. Тесты и проверки кода

Из папки `backend` (нужен `uv`):

```powershell
uv sync --extra dev
uv run ruff check .
uv run mypy src eval
uv run lint-imports
uv run pytest tests/unit
uv run pytest tests/integration -m integration   # нужен запущенный Docker
uv run python -m eval.run                         # offline-eval
```

Веб (из папки `web`): `npm run typecheck`, `npm run lint`, `npm run build`.

---

## 10. Остановка и сброс

```powershell
dc down          # остановить, данные сохраняются
dc down -v       # остановить и УДАЛИТЬ данные (БД, Grafana)
dc up --build -d # пересобрать после изменений кода или зависимостей
```

---

## 11. Типичные проблемы

| Симптом | Причина и решение |
|---|---|
| `docker: error during connect` / нет Server в `docker version` | Docker Desktop не запущен или ещё стартует — дождаться **Engine running** |
| Docker требует виртуализацию / WSL | Включить VT-x / AMD-V в BIOS; обновить WSL: `wsl --update` |
| Порт занят (`8000`, `3000`, `5432`, `6379`, `8025`, `3001`, `9090`) | Найти процесс: `netstat -ano \| findstr :8000`; закрыть его или поменять порт в `deploy/docker-compose.yml` |
| Сервис падает с кодом 78 | Не заполнены обязательные переменные — сообщение в логах называет какие (`dc logs <сервис>`) |
| Странные значения переменных / ошибки парсинга `.env` | `.env` сохранён с `CRLF` или в кодировке не UTF-8 — пересохранить в `LF` / UTF-8 |
| `with_embedding = 0` | Режим A без ML-зависимостей (ожидаемо до P0 №1) — нормализовать через режим B |
| Нормализация падает / `failed` в статусе | LLM недоступна: проверить ключ, баланс DeepSeek и `/api/v1/admin/llm/status`; повторить `retry-failed` |
| `403 forbidden` на ingestion | Не передан или не совпадает `X-API-Key` с `API_SHARED_SECRET` |
| Бот молчит | Нет `BOT_TOKEN` / `API_SHARED_SECRET`, не запущен профиль `bot`, или аккаунт не привязан (`/start <токен>`) |
| Веб не видит API в режиме B | Не задан `API_BASE_URL=http://localhost:8000` перед `npm run dev` |
| В режиме B `connection refused` к БД | Не выполнен п. 6.3 в этом окне PowerShell или не запущены `postgres` / `redis` |

---

## 12. Промпт для Claude Code

Открыть терминал в папке репозитория, запустить `claude` и вставить текст
ниже целиком. (Claude Code на Windows выполняет команды через Git Bash —
`docker`, `uv`, `curl` там работают так же.)

```text
Задача: поднять EventMind локально с нуля и проверить, что он работает.
Инструкция — docs/LAUNCH.md, выполняй её по шагам. Контекст проекта — CLAUDE.md
и docs/PROJECT_REVIEW.md.

Окружение: Windows 11 (или macOS — уточни по `uname`/`ver`), Docker Desktop,
работа в обычной Windows, без WSL как рабочей среды.

Правила:
- Никогда не печатай значения секретов из .env и не коммить .env. Проверяй
  только, заполнена ли переменная (например, через grep -c '^DEEPSEEK_API_KEY=.\+').
- После каждого шага проверяй результат. При ошибке остановись, покажи вывод
  и предложи исправление; не обходи проблему молча.
- Ничего не удаляй (в том числе docker-тома) без моего подтверждения.
- Не меняй код проекта; если для запуска нужен фикс — сначала спроси.

Шаги:
1. Проверь установленные инструменты (п. 0): git, docker (Client и Server),
   docker compose, uv, node. Чего не хватает — скажи, какой командой поставить.
2. Проверь .env (п. 3): есть ли файл; заполнены ли DEEPSEEK_API_KEY (или другой
   LLM-ключ), JWT_SECRET, API_SHARED_SECRET; для бота — BOT_TOKEN и
   TELEGRAM_BOT_USERNAME. Если .env нет — создай из .env.example и попроси меня
   вписать ключи; пустые JWT_SECRET и API_SHARED_SECRET можешь сгенерировать сам.
3. Режим A (п. 4): docker compose -f deploy/docker-compose.yml up --build -d;
   дождись healthy; проверь /health, /ready, веб :3000, Mailhog :8025.
4. Демо-аккаунт (п. 5): seed через `docker compose run --rm api ...`.
5. События (п. 5): load-all?limit=50, затем normalize?limit=100 (повторяй, пока
   в статусе есть raw), с заголовком X-API-Key из API_SHARED_SECRET; покажи
   итоговый ingestion/status и количество events / with_embedding из psql.
6. Если with_embedding = 0 — перейди в режим B (п. 6): инфраструктура в Docker,
   api и worker на хосте с `uv sync --extra dev --extra ml --extra bot`,
   адреса localhost через переменные оболочки, запуск с `--env-file ../.env`;
   повтори normalize для новых событий и убедись, что эмбеддинги появились.
7. Бот (п. 7): если задан BOT_TOKEN — подними его и подскажи, как привязать
   аккаунт через веб.
8. Прогони проверки (п. 9): ruff, mypy, lint-imports, pytest tests/unit.

Итоговый отчёт: какие сервисы подняты и на каких адресах; сколько событий и
сколько с эмбеддингами; какие звенья LLM-цепочки активны
(/api/v1/admin/llm/status); результаты тестов; что не удалось и почему.
```
