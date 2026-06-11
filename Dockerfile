# Ada runtime image.
# Storage + DB connectivity are driven by environment / .env (DATABASE_URL).
# Point DATABASE_URL at Postgres for scale; omit it for SQLite.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application source.
COPY . .

# Default server port (overridable via PORT).
EXPOSE 8002

# Boot the runtime. init_db() runs alembic migrations on Postgres
# (creating the schema) or create_all on SQLite.
CMD ["python", "main.py"]
