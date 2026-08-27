FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Run as a dedicated non-root user. /data volume mount points are created
# here so fresh named volumes inherit the right ownership on first mount;
# pre-existing volumes need a one-time:
#   docker compose exec -u root api chown -R app:app /data
RUN groupadd -r -g 10001 app \
    && useradd -r -u 10001 -g app -m -d /home/app app \
    && mkdir -p /data/uploads /data/hermes-profiles \
    && chown -R app:app /data /home/app
USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
