# MBK assistant — Backend deployment

Бэкенд на FastAPI, разворачивается в Docker. Состояние сессий — in-memory + снапшоты в `logs/sessions/`.

## Что внутри

- `main.py` — FastAPI приложение, SSE-стрим, эндпоинты.
- `session_store.py` — хранилище сессий и фоновый ThreadPoolExecutor.
- `usage_tracker.py` — учёт токенов и стоимости (USD за миллион токенов).
- Остальные `*.py` — бизнес-логика, переиспользована из Streamlit-версии без изменений.

## VPS: минимальные требования

- Ubuntu 22.04 / Debian 12 (любой дистрибутив с современным Docker).
- 2 GB RAM, 1 vCPU, 10 GB диск — достаточно для пилота на 30–50 одновременных сессий.
- Открытый порт 8000 (для прямого тестирования) или 80/443 (через reverse-proxy в проде).

## Развёртывание — три команды

```bash
# 1. Поставить Docker и compose plugin (одноразово)
curl -fsSL https://get.docker.com | sh
sudo apt-get install -y docker-compose-plugin

# 2. Скопировать репо на сервер и подложить .env
git clone https://github.com/Zheltenkov/MBK_v3.git mbk && cd mbk
cp .env.example .env
nano .env   # ВНЕСТИ свой OPEN_ROUTER_API_KEY и опционально LANGFUSE_*

# 3. Запустить
sudo docker compose up -d --build
```

После этого `http://VPS_IP:8000/api/health` должен вернуть `{"status":"ok",...}`.

## Smoke-тест после старта

```bash
./test_api.sh
```

Покажет: создание сессии, SSE-стрим opening, один turn клиента, расход токенов.

## Переменные окружения

Обязательные:
- `OPEN_ROUTER_API_KEY` — ключ OpenRouter.

Опциональные:
- `OPENROUTER_MODEL` — разговорная модель (по умолчанию `qwen/qwen3.7-max`).
- `OPENROUTER_EXTRACTOR_MODEL` — извлекатель JSON (по умолчанию `deepseek/deepseek-v4-pro`).
- `OPENROUTER_TEMPERATURE` (default 0.75), `OPENROUTER_MAX_TOKENS` (default 5000).
- `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` + `LANGFUSE_HOST` — для трейсинга (необязательно).
- `LEAD_WEBHOOK_URL` — куда отдавать готовый лид (CRM / n8n / Telegram-бот). Пусто — пишем только в `logs/leads.jsonl`.
- `CORS_ALLOWED_ORIGINS` — список доменов фронта через запятую (для прода — обязательно сузить).
- `MBK_BACKEND_PORT` — на каком порту слушать (default 8000).

Цены токенов настраиваются в коде в `usage_tracker.py` (`PRICING_PER_MILLION_TOKENS`). Можно
переопределить из env через `PRICE_<model_slug>_INPUT` / `PRICE_<model_slug>_OUTPUT`.

## Эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| GET  | `/api/health`                          | проверка живости + текущая модель |
| POST | `/api/session`                         | создать сессию (body: `{"anketa": {...} \| null}`) |
| GET  | `/api/session/{id}`                    | текущий state |
| GET  | `/api/session/{id}/stream?message=...` | SSE-стрим: opening (если message пуст и нет истории) или turn |
| GET  | `/api/session/{id}/usage`              | расход токенов и стоимость по этой сессии |
| GET  | `/api/usage/global`                    | суммарно по всем активным сессиям |
| POST | `/api/session/{id}/end`                | закрыть сессию (записать summary) |

## SSE-формат

Каждое событие `event: <type>` + `data: <json>`:

- `chunk`   — `{ "text": "..." }` — кусок токенов от модели.
- `bubbles` — `{ "bubbles": ["...", "..."] }` — пузыри после стрима (после разбиения по пустым строкам).
- `state`   — `{ "state": {...}, "lead_delivered": {...} }` — обновлённое состояние после extract-фазы.
- `error`   — `{ "message": "..." }` — ошибка.
- `done`    — `{}` — стрим закрылся.

Фронт буферизует `chunk`-события в один растущий пузырь до прихода `bubbles`, потом перерисовывает
в окончательную разбивку. Это убирает «прыжок» текста, который был на Streamlit.

## Reverse-proxy на проде (опционально, но рекомендуется)

Один nginx на 80/443 раздаёт фронт + проксирует `/api/*` на backend. Минимальный конфиг (фрагмент):

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;            # критично для SSE
    proxy_read_timeout 24h;          # SSE-соединение долгое
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

TLS — через certbot (`apt install certbot python3-certbot-nginx && certbot --nginx`).

## Логи и наблюдаемость

- `logs/dialogs.jsonl` — каждое сообщение клиента и бота.
- `logs/leads.jsonl` — все доставленные лиды.
- `logs/sessions/{id}.json` — снапшоты состояний (для разбора кейсов).
- Langfuse (если ключи заданы) — дашборд по каждому ходу: латентность, токены, стоимость.

## Логи проверять командой

```bash
docker compose logs -f backend
```

## Обновление после правки кода

```bash
git pull
sudo docker compose up -d --build
```

## Откат на Streamlit (на всякий)

Streamlit-приложение `app.py` остаётся в репо. Для запуска вне Docker:
```bash
pip install -r requirements.txt
streamlit run app.py
```

Не для прода, но удобно для отладки и быстрых проверок.
