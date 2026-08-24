# The doc-harness service. See docs/planning/2026-08-24-34-doc-harness-service.md.
FROM python:3.12-slim

# Only the container needs a server. The test gate does not install this file.
COPY harness/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /app
COPY harness/ /app/harness/
COPY index/ /app/index/
# `index/build_index.py` loads these two out of its SIBLING directory at call time, not by
# import, so leaving them out broke every index render with a 500 and nothing caught it.
# Named individually on purpose: the rest of `scripts/` is the publisher toolchain and its
# test suite, and neither belongs in a serving container. Both modules are stdlib-only.
COPY scripts/vdl_packs.py scripts/user_config.py /app/scripts/

# The service refuses to start without its two secrets, so there are no defaults here.
ENV PYTHONUNBUFFERED=1 \
    DOC_HARNESS_REGISTRY_PATH=/var/lib/doc-harness/registry.db \
    DOC_HARNESS_CACHE_DIR=/var/cache/doc-harness

RUN useradd --system --uid 10001 harness \
 && mkdir -p /var/lib/doc-harness /var/cache/doc-harness \
 && chown -R harness:harness /var/lib/doc-harness /var/cache/doc-harness
USER harness

# A TCP connect from inside the container, deliberately NOT an HTTP health endpoint: the whole
# design is that only gated hosts answer, so an unauthenticated route would be a new request
# surface no criterion asked for. Measured in both states on this base image: exit 1 with
# nothing listening (ConnectionRefusedError), exit 0 with a listener.
# It assumes the harness accepts on loopback, which DOC_HARNESS_BIND's default 0.0.0.0:8080
# does. Narrowing that bind breaks this silently AND stops cloudflared ever starting, because
# it waits on service_healthy. Change both in one commit or neither.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python3", "-c", "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()"]

CMD ["python3", "-m", "harness"]
