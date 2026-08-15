# Pinned by digest, not just a tag (issue #23, same convention as
# docker-compose.yml): a tag can be re-pushed to a different image, the
# digest cannot. Tag kept alongside for legibility; Dependabot's docker
# ecosystem for /app watches the digest and opens a PR when it moves.
FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

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
