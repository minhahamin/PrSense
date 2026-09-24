FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 \
    CHROMA_DIR=/data/chroma

# NOTE: no VOLUME instruction — Railway rejects it.
# Persistent /data comes from the "chroma-data" volume in .railway/railway.ts.

EXPOSE 8000

# Railway injects $PORT — fall back to 8000 for local docker runs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
