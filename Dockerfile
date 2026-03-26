FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UVICORN_TIMEOUT_KEEP_ALIVE=30

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn simulated_assets.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE}"]
