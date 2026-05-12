# EventMind

EventMind — прототип системы агрегации IT-событий и персонализированных рекомендаций на основе модели пользователя.

## Идея проекта

Система предназначена для:
- сбора информации об IT-событиях,
- хранения пользовательских предпочтений,
- формирования персональных рекомендаций,
- фиксации обратной связи пользователя.

В качестве пользовательского интерфейса используется Telegram-бот.  
Backend реализован в виде REST API на FastAPI.  
Для хранения данных используется SQLite (миграции Alembic).

## Архитектура

Система состоит из следующих модулей:

- `app/bot` — Telegram-бот
- `app/api` — backend API
- `app/db` — модели данных и подключение к БД
- `app/recommender` — модуль рекомендаций (rule + embeddings)
- `app/ingestion` — загрузка и нормализация событий (включая источники)
- `app/agents` — LangGraph-агенты для нормализации и рекомендаций
- `app/scheduler` — планировщик AI-дайджестов (APScheduler)
- `app/admin` — заготовка admin-дашборда
- `tests/` — unit-тесты
- `alembic/` — миграции БД
- `data/events.json` — тестовый набор событий

## Реализованный функционал

- настройка профиля пользователя через Telegram-бота;
- выбор интересующих тем / формата / города;
- регистрация пользователя через API;
- загрузка событий из JSON + Habr RSS;
- AI-нормализация сырых событий (LangGraph + Groq LLM);
- генерация краткого summary через LLM;
- получение персональных рекомендаций (hybrid: rule + embeddings);
- LangGraph-агенты с собственной AI-карточкой рекомендаций;
- запись пользовательских действий: интересно / не интересно / сохранить;
- объяснения рекомендаций с учётом истории взаимодействий;
- поиск событий по ключевым словам, темам, формату, городу;
- похожие события (по пересечению тем);
- статистика активности пользователя;
- холодный старт через `/bio <текст>` (LLM извлекает темы);
- ежедневный AI-дайджест в Telegram (APScheduler);
- admin-дашборд и аналитика;
- определение дубликатов через fuzzy-сравнение заголовков;
- alembic-миграции (включая `summary` и `embedding` колонки).

## Основные команды Telegram-бота

- `/start` — первичная настройка профиля
- `/recommend` — показать рекомендации
- `/profile` — показать профиль и веса интересов
- `/saved` — показать сохраненные события
- `/edit` — изменить профиль
- `/stats` — личная статистика (likes/dislikes/saves, топ тем, последние действия)
- `/search <запрос>` — поиск событий
- `/bio <текст>` — холодный старт, извлекаем темы из bio
- `/subscribe`, `/unsubscribe` — управление подпиской на AI-дайджесты

## Логика рекомендаций

Используется hybrid-подход:
1. **Rule-based score** — совпадение тем, веса тем, формат, город.
2. **Embedding similarity** — `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`)
   считает cosine similarity между профилем пользователя (тематические интересы)
   и текстом события (`title + description`).
3. Финальный score: `rule * 0.5 + similarity * 10`. При недоступности
   `sentence-transformers` система плавно деградирует до rule-based.

Объяснение рекомендаций (`explain_event_for_user`) при наличии `db` использует
историю взаимодействий: «ты сохранял события по этой теме», «тебе нравятся
online-форматы», «высокий интерес к теме AI / ML».

## Пайплайн обработки событий (ingestion)

1. Источник: JSON-файл (`data/events.json`) или RSS-фид Habr (`app/ingestion/sources/habr.py`).
2. Сырое событие сохраняется в `raw_events` со статусом `raw`.
3. `EventNormalizerAgent` (LangGraph) анализирует описание и нормализует поля.
4. При сохранении проверяется дубликат (`SequenceMatcher`, порог 0.85).
5. Если у нормализованного события нет `summary` — он генерируется через LLM.
6. Для события создаётся embedding (если установлен `sentence-transformers`).
7. Готовое событие сохраняется в `events` со статусом `normalized`.

## API endpoints

### Users
- `POST /users/register`
- `GET /users/{telegram_id}`
- `GET /users/{telegram_id}/stats`
- `POST /users/{telegram_id}/analyze-bio` — холодный старт

### Events
- `GET /events/`
- `GET /events/search?q=&topics=&format=&city=`
- `GET /events/{event_id}/similar`
- `POST /events/load` / `POST /events/load-ai`

### Recommendations
- `GET /recommendations/{telegram_id}`
- `GET /agent-recommendations/{telegram_id}` (LangGraph)
- `GET /agent-recommendations/{telegram_id}/cards`
- `POST /recommendations/interactions`
- `GET /recommendations/{telegram_id}/saved`

### Ingestion
- `POST /ingestion/load-json`
- `POST /ingestion/load-habr`
- `POST /ingestion/normalize?limit=N`

### Subscriptions
- `POST /subscriptions/{telegram_id}/subscribe` / `unsubscribe`
- `GET /subscriptions/users`

### Admin
- `GET /admin/` — HTML-дашборд

### Analytics
- `GET /analytics/topics` — самые лайкнутые / сохранённые темы, веса
- `GET /analytics/interactions` — статистика по действиям, топ событий

## Scheduler (AI-дайджест)

Запускается отдельным процессом и каждые 24 часа отправляет подписчикам топ
AI-рекомендацию:

```bash
python -m app.scheduler.digest
```

## Admin dashboard

Открой `http://localhost:8000/admin/` после запуска API.

## Установка и запуск

```bash
pip install -r requirements.txt

# Применить миграции
alembic upgrade head

# Запустить API
uvicorn app.api.main:app --reload

# Запустить бота
python -m app.bot.main

# (Опционально) запустить scheduler дайджестов
python -m app.scheduler.digest
```

## Переменные окружения (`.env`)

- `BOT_TOKEN` — токен Telegram-бота.
- `DATABASE_URL` — `sqlite:///./eventmind.db` по умолчанию.
- `API_HOST` — `http://localhost:8000` по умолчанию.
- `GROQ_API_KEY` — токен для Groq LLM (LangGraph-агенты).
- `GROQ_MODEL` — модель Groq (`llama-3.3-70b-versatile` по умолчанию).

## Структура проекта

```bash
app/
  bot/
  api/
    routers/
    services/
    schemas/
  core/
  db/
    models/
  recommender/    # scoring, explain, embeddings, hybrid
  ingestion/
    sources/      # habr.py и др.
  agents/
    recommendation/
    event_normalization/
  scheduler/
  admin/
alembic/
  versions/
data/
tests/
```
