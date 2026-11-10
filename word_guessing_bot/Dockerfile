FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd -m bot && mkdir -p /app/storage /app/logs && chown -R bot:bot /app
USER bot

# On Railway: attach a Volume mounted at /app/storage (do not use the VOLUME keyword).
ENV DB_PATH=/app/storage/wordzuno.db LOG_DIR=/app/logs

CMD ["python", "main.py"]
