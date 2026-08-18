# Pinned by digest, not just a tag (issue #23, same convention as
# docker-compose.yml): a tag can be re-pushed to a different image, the
# digest cannot. Tag kept alongside for legibility; Dependabot's docker
# ecosystem for /app watches the digest and opens a PR when it moves.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# The deploy's git SHA — set by CI/build.sh via `--build-arg SOURCE_COMMIT=$(git
# rev-parse HEAD)`. Available at runtime as env AVELREN_GIT_SHA and surfaced in
# /admin/telemetry.version. Default value is an empty string: better a null on
# the client than a fake "unknown".
ARG SOURCE_COMMIT=""
ENV AVELREN_GIT_SHA=${SOURCE_COMMIT}

# We do not run as root in the container.
RUN useradd --create-home --uid 10001 avelren
USER avelren

CMD ["python", "-m", "avelren.collector"]
