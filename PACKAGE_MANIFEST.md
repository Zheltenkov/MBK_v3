# MBK runtime handoff package

Этот файл фиксирует состав передаваемого runtime-пакета. Цель — отдать партнёру
контейнеризуемое приложение без ключей, логов, eval-наборов и локальных артефактов.

## Входит в пакет

Backend runtime:
- `main.py`
- `core.py`
- `llm_agent.py`
- `prompts.py`
- `state.py`
- `lead_delivery.py`
- `session_store.py`
- `usage_tracker.py`
- `assistant_contracts.py`
- `observability.py`
- `logger.py`
- `config.py`
- `utils.py`
- `pii_masking.py`

Frontend runtime:
- `frontend/Dockerfile`
- `frontend/.dockerignore`
- `frontend/nginx.conf`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/postcss.config.js`
- `frontend/tailwind.config.js`
- `frontend/vite.config.js`
- `frontend/src/**`

Infra and docs:
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.images.yml`
- `requirements.txt`
- `.env.example`
- `.dockerignore`
- `.gitignore`
- `test_api.sh`
- `README_DEPLOY.md`
- `HANDOFF.md`
- `README_IMAGES.md`
- `PACKAGE_MANIFEST.md`

## Не входит в пакет

- `.env` — реальные ключи и пароли.
- `logs/` — диалоги, лиды и session snapshots с ПД.
- `.venv*`, `__pycache__`, `.pytest_cache`, `.serena`, `.playwright-mcp`, `.tmp`.
- `frontend/node_modules/`, `frontend/dist/`.
- `run_eval.py`, `run_routing_eval.py`, `mikhail_eval_cases.json`, `routing_cases.json` — внутренняя eval-кухня.
- `app.py`, `.streamlit/`, `config.toml` — legacy Streamlit UI, не production runtime.

## Проверки перед передачей

```bash
python -m py_compile main.py core.py llm_agent.py prompts.py state.py lead_delivery.py \
  session_store.py usage_tracker.py assistant_contracts.py observability.py logger.py \
  config.py utils.py pii_masking.py

cd frontend && npm run build
docker compose config --quiet
```

На машине с запущенным Docker:

```bash
docker compose build
docker compose up -d
./test_api.sh
```

## Передача готовыми Docker images

Если партнёру не нужно сразу смотреть исходники, можно передать уже собранные образы:

- `mbk_images_20260615.tar`
- `docker-compose.images.yml`
- `.env.example`
- `HANDOFF.md`

Запуск у партнёра:

```bash
docker load -i mbk_images_20260615.tar
cp .env.example .env
nano .env
docker compose -f docker-compose.images.yml up -d
```
