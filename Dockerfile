# A sandbox for WaxalAgent: the server, ffmpeg and (optionally) the Wolof models, isolated from your PC.
#
#   docker compose up --build            # fake engines: the plumbing, no models
#   WAXAL_ENGINES=wolof docker compose up --build    # the real models (a big image, CPU only)
#
# Behind a company proxy that re-signs HTTPS: put the company root certificate (a .crt or .pem file) in ./certs before
# building; it is installed in the image so pip, git and the model downloads trust it.
FROM python:3.12-slim

ARG WITH_MODELS=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Company root certificates (optional): *.crt are installed; a .pem is renamed to .crt first.
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

# The server; the model libraries only when WITH_MODELS=1 (CPU build of torch: the default wheel is several GB of CUDA).
RUN uv venv /opt/venv \
 && . /opt/venv/bin/activate \
 && if [ "$WITH_MODELS" = "1" ]; then \
      uv pip install --index-url https://download.pytorch.org/whl/cpu torch; \
      uv pip install ".[models]"; \
    else \
      uv pip install .; \
    fi
ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/models \
    PYTHONUNBUFFERED=1

# Models are downloaded on first use into /models (a volume: they are kept between runs); conversations in /app/data.
VOLUME ["/models", "/app/data"]
EXPOSE 8000
CMD ["waxal-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
