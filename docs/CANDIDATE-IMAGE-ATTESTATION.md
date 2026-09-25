# Local candidate-image attestation

`ops/build-candidate-image.sh` builds one backend image locally from a clean
checkout, under the non-production tag `avelren-candidate:<full-commit>`.
It passes that exact commit as `SOURCE_COMMIT`, reads Docker's immutable image
ID, then starts a one-shot `python` process with `--network none` to verify
`AVELREN_GIT_SHA` inside the image.

The script never runs Compose, pushes an image, contacts production, reads
`.env`, or deploys a container. Its JSON output supplies one candidate-image
attestation; the same attestation may be assigned to API, collector, notifier
and watchdog because they share the backend image.

The current candidate was built locally on 2026-09-25 from clean `main` commit
`ec070b6edd8b87aaf11fc81c6613378a5abad66a`. Its image ID is
`sha256:b7a708e8ed7c7773129b96297dcfe10d1ddcfe5d5cd60bef445668e1193b4acc`
and the one-shot no-network attestation read the same value from
`AVELREN_GIT_SHA`. The image remains only in local Docker Desktop: it was not
pushed, run as a service or deployed. It is not an approved production
candidate until a fresh server evidence record and review are prepared.
