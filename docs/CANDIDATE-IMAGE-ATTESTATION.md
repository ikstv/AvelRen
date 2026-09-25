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

The candidate built locally on 2026-09-25 from commit
`6be250eaadbfc4276ec9707a4a7341c10fa34104` had image ID
`sha256:285abc3313fa62f6cade2792af2cced56d94e9754fef557d80777574b8ab0429`
and embedded the same commit. This is local build evidence only: it is not an
approved production candidate until a fresh target commit, evidence record and
review are prepared.
