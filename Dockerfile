# The doc-harness service. See docs/planning/2026-08-24-34-doc-harness-service.md.
FROM python:3.12-slim

# Only the container needs a server. The test gate does not install this file.
COPY harness/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /app
COPY harness/ /app/harness/
COPY index/ /app/index/

# The service refuses to start without its two secrets, so there are no defaults here.
ENV PYTHONUNBUFFERED=1 \
    DOC_HARNESS_REGISTRY_PATH=/var/lib/doc-harness/registry.db \
    DOC_HARNESS_CACHE_DIR=/var/cache/doc-harness

RUN useradd --system --uid 10001 harness \
 && mkdir -p /var/lib/doc-harness /var/cache/doc-harness \
 && chown -R harness:harness /var/lib/doc-harness /var/cache/doc-harness
USER harness

CMD ["python3", "-m", "harness"]
