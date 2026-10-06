# A small container for WaxalAgent: the server and ffmpeg. All speech and translation go through Soynade's hosted API.
#
#   docker compose up --build
#
# Behind a company proxy that re-signs HTTPS: put the company root certificate (a .crt or .pem file) in ./certs before
# building; it is installed in the image so pip, git and the calls to Soynade and Meta trust it.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY certs/ /tmp/certs/
RUN for f in /tmp/certs/*.pem /tmp/certs/*.crt; do \
      [ -f "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
    done; \
    update-ca-certificates && rm -rf /tmp/certs
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    UV_NATIVE_TLS=1

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY waxal_agent ./waxal_agent
COPY scripts ./scripts
# The library baked into the image: the documents of this deployment (the domain: finance, medicine...). Put them in
# ./library (or another folder, --build-arg LIBRARY=customers/acme/docs) before building. Per-person documents and
# memory stay outside the image, in the mounted data/ volume.
ARG LIBRARY=library
COPY ${LIBRARY}/ /app/library/
ENV WAXAL_DOCUMENTS=/app/library
RUN uv venv /opt/venv && . /opt/venv/bin/activate && uv pip install .
# The agent can browse the allowed websites (WAXAL_LINK_DOMAINS) in a headless browser. It adds a Chromium (a few hundred MB) to the image:
#   docker compose build --build-arg WITH_BROWSER=1       (not tested here: there is no Docker daemon in my environment)
ARG WITH_BROWSER=0
RUN if [ "$WITH_BROWSER" = "1" ]; then . /opt/venv/bin/activate && uv pip install ".[browser]" && playwright install --with-deps chromium; fi
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1

VOLUME ["/app/data"]
EXPOSE 8000
CMD ["waxal-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
