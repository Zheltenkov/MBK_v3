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
Контрольная сумма есть в `ARTIFACTS.sha256`.

## Запуск 

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
- `OPENROUTER_BASE_URL` - https://openrouter.ai/api/v1
- `OPENROUTER_PROXY`
- `OPENROUTER_MODEL` - qwen/qwen3.7-max
- `OPENROUTER_EXTRACTOR_MODEL` - deepseek/deepseek-v4-pro
- `MBK_PORT`

См. детали в `HANDOFF.md`.

## Что не передаётся
