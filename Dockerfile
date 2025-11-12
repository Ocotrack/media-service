FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg supervisor ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir \
    "uvicorn[standard]" fastapi python-dotenv redis pillow minio python-multipart

ENV PYTHONPATH=/app

COPY supervisord.conf /app/supervisord.conf

EXPOSE 8002
CMD ["supervisord", "-c", "/app/supervisord.conf"]
