FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements.worker.txt ./
RUN pip install --no-cache-dir -r requirements.worker.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libx11-6 \
    libxext6 \
    libsm6 \
    libice6 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Run as a dedicated non-root user; see backend.Dockerfile for the one-time
# chown needed on pre-existing volumes.
RUN groupadd -r -g 10001 app \
    && useradd -r -u 10001 -g app -m -d /home/app app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data /home/app
USER app

CMD ["python", "-m", "app.workers.rag_worker"]
