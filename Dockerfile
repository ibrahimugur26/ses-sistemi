FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

ENV PYTHONUNBUFFERED=1

# Görev takibi bellekte tutulduğu için tek worker + çok thread kullanılır
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:${PORT:-10000}"]
