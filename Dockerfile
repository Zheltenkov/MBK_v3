FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала requirements — кэшируется отдельным слоем.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения (без logs/.streamlit/.env — они через volume / env-файл).
COPY *.py ./
COPY *.json ./

# Logs пишутся в volume, директорию создаём заранее.
RUN mkdir -p logs/sessions && \
    groupadd --system mbk && \
    useradd --system --gid mbk --no-create-home mbk && \
    chown -R mbk:mbk /app
USER mbk

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=3).status == 200 else 1)"

# uvicorn без --reload в проде; workers=2 — компромисс между параллельностью и памятью.
# При желании поменяй на gunicorn + uvicorn worker'ы, но для одного VPS uvicorn хватает.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
