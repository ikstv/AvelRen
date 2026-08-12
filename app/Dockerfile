FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Git SHA деплою — виставляється CI/build.sh через `--build-arg SOURCE_COMMIT=$(git
# rev-parse HEAD)`. У runtime доступний як env AVELREN_GIT_SHA і потрапляє в
# /admin/telemetry.version. Значення за замовчуванням — порожній рядок: краще
# null на клієнті, ніж підроблене «unknown».
ARG SOURCE_COMMIT=""
ENV AVELREN_GIT_SHA=${SOURCE_COMMIT}

# Не працюємо від root у контейнері.
RUN useradd --create-home --uid 10001 avelren
USER avelren

CMD ["python", "-m", "avelren.collector"]
