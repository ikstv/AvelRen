FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Не працюємо від root у контейнері.
RUN useradd --create-home --uid 10001 avelren
USER avelren

CMD ["python", "-m", "avelren.collector"]
