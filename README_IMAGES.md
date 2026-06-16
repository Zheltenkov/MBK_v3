# MBK Assistant — запуск из готовых Docker images

Этот пакет нужен для запуска без сборки исходников на сервере партнёра.

## Состав

- `mbk_images_20260615.tar` — backend/frontend Docker images.
- `docker-compose.images.yml` — compose-файл без `build:`.
- `.env.example` — шаблон переменных окружения.
- `HANDOFF.md` — полный deployment handoff.
- `PACKAGE_MANIFEST.md` — состав пакета и исключения.

## Запуск

```bash
docker load -i mbk_images_20260615.tar
cp .env.example .env
nano .env
docker compose -f docker-compose.images.yml up -d
```

Проверка:

```bash
docker compose -f docker-compose.images.yml ps
curl -i http://127.0.0.1:${MBK_PORT:-80}/api/health
```

## Образы

- `mbk-backend:handoff-20260615`
- `mbk-frontend:handoff-20260615`

Архитектура: `linux/amd64`.

## Важно

Не кладите реальные ключи в репозиторий или архив передачи. Runtime-секреты должны быть
только в `.env` на сервере партнёра.
