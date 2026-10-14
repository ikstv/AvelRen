# Only these two allowlisted files enter the build context.
FROM sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3
ARG SOURCE_COMMIT
ENV AVELREN_GIT_SHA=$SOURCE_COMMIT
COPY --chown=0:0 --chmod=0644 eta.py /usr/local/lib/python3.14/site-packages/avelren/eta.py
