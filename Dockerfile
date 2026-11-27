FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
RUN mkdir -p /app/.data /app/.cache/huggingface && chown -R app:app /app/.data /app/.cache

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY knowledge_base ./knowledge_base
COPY mock_services ./mock_services
COPY scripts ./scripts

RUN python -m pip install --upgrade pip && python -m pip install .

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
