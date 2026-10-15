# Only the two allowlisted Python modules are copied into the image.
FROM avelren-legacy-eta-base:e7b02f58581d
ARG SOURCE_COMMIT
ENV AVELREN_GIT_SHA=$SOURCE_COMMIT
COPY --chown=0:0 --chmod=0644 eta.py /usr/local/lib/python3.14/site-packages/avelren/eta.py
COPY --chown=0:0 --chmod=0644 collector.py /usr/local/lib/python3.14/site-packages/avelren/collector.py
