# A small container for {{app_title}}: the server, ffmpeg and tesseract (OCR of scanned PDF pages). All speech and translation go through Soynade's hosted API.
#
#   docker compose up --build
#
# Behind a company proxy that re-signs HTTPS: put the company root certificate (a .crt or .pem file) in ./certs before
# building; it is installed in the image so pip, git and the calls to Soynade and Meta trust it.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git ca-certificates tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara tesseract-ocr-eng \
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
COPY {{app_slug}} ./{{app_slug}}
# The library comes from git (the local folder ../WaxalAgent used while developing is outside this build context).
# Pin a commit for a reproducible image: --build-arg WAXAL_AGENT="waxal-agent @ git+https://github.com/DemePS/WaxalAgent.git@<commit>"
ARG WAXAL_AGENT="waxal-agent @ git+https://github.com/DemePS/WaxalAgent.git"
# The library baked into the image: the documents of this deployment (the domain: finance, medicine...). Put them in
# ./library (or another folder, --build-arg LIBRARY=customers/acme/docs) before building. Per-person documents and
# memory stay outside the image, in the mounted data/ volume.
ARG LIBRARY=library
COPY ${LIBRARY}/ /app/library/
ENV WAXAL_DOCUMENTS=/app/library
RUN uv venv /opt/venv && . /opt/venv/bin/activate && uv pip install "$WAXAL_AGENT" && uv pip install --no-deps .
# The agent can browse the allowed websites (WAXAL_LINK_DOMAINS) in a headless browser. It adds a Chromium (a few hundred MB) to the image:
#   docker compose build --build-arg WITH_BROWSER=1       (not tested here: there is no Docker daemon in my environment)
ARG WITH_BROWSER=0
RUN if [ "$WITH_BROWSER" = "1" ]; then . /opt/venv/bin/activate && uv pip install "waxal-agent[browser] @ git+https://github.com/DemePS/WaxalAgent.git" && playwright install --with-deps chromium; fi
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1

VOLUME ["/app/data"]
EXPOSE 8000
CMD ["{{app_slug}}", "serve", "--host", "0.0.0.0", "--port", "8000"]
