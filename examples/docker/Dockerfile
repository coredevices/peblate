# Stock Weblate with installed extension wheels; no patched Weblate source.
FROM weblate/weblate@sha256:990720d1737a3f5a0221017943f568adb215e8f1571f2c6d37622c1bdfbc678b
USER root
COPY wheels/ /tmp/peblate-wheels/
RUN uv pip install --python /app/venv/bin/python --no-cache /tmp/peblate-wheels/*.whl && rm -rf /tmp/peblate-wheels
USER 1000
