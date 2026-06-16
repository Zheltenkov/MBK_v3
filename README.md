# MBK Assistant deploy package

Эта ветка предназначена для передачи и запуска MBK Assistant без сборки исходников.

## Что лежит в ветке

- `docker-compose.images.yml` — запуск готовых Docker images без `build:`.
- `.env.example` — шаблон runtime-переменных.
- `HANDOFF.md` — полная инструкция по развёртыванию и прокси/OpenRouter.
- `README_IMAGES.md` — короткий запуск из Docker images.
- `PACKAGE_MANIFEST.md` — состав пакетов и что исключено.
- `mbk_handoff_20260615.zip` — runtime-исходники без секретов, логов и eval-кухни.
- `ARTIFACTS.sha256` — контрольные суммы артефактов.

## Где Docker images

Готовый image-пакет `mbk_images_package_20260615.zip` не хранится в git-ветке, потому что
его размер около 214 МБ. Обычный GitHub repository не подходит для таких бинарников.

Передайте файл отдельно или загрузите его в GitHub Release asset:

- `mbk_images_package_20260615.zip`

Контрольная сумма есть в `ARTIFACTS.sha256`.

## Запуск у партнёра

1. Скачать/получить `mbk_images_package_20260615.zip`.
2. Распаковать его рядом с файлами этой ветки.
3. Загрузить Docker images:

```bash
docker load -i mbk_images_20260615.tar
```

4. Создать runtime `.env`:

```bash
cp .env.example .env
nano .env
```

5. Запустить:

```bash
docker compose -f docker-compose.images.yml up -d
```

6. Проверить:

```bash
docker compose -f docker-compose.images.yml ps
curl -i http://127.0.0.1:${MBK_PORT:-80}/api/health
```

## Что обязательно заполнить в `.env`

- `OPEN_ROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_PROXY`, если доступ к OpenRouter идёт через зарубежный VPS
- `OPENROUTER_MODEL`
- `OPENROUTER_EXTRACTOR_MODEL`
- `MBK_AUTH_USERNAME`
- `MBK_AUTH_PASSWORD`
- `MBK_PORT`

См. детали в `HANDOFF.md`.

## Что не передаётся

- Реальный `.env`.
- `logs/` с ПД клиентов.
- Eval-кухня и эталонные кейсы.
- Legacy Streamlit UI.
- `node_modules`, `frontend/dist`, virtualenv/cache.
