FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install third-party dependencies first so this layer is cached
# independently of application source changes. A minimal package skeleton
# lets `pip install .` resolve and install deps without the real source.
COPY pyproject.toml ./
RUN mkdir -p app \
    && touch app/__init__.py \
    && pip install . \
    && rm -rf app

# Now copy the real source and install only the package (deps already present).
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-deps . \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
