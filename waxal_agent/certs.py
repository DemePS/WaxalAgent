"""HTTPS behind a company proxy: trust the certificates the operating system trusts.

On a network that inspects HTTPS, downloading a model from Hugging Face fails with CERTIFICATE_VERIFY_FAILED, because
Python does not know the company's root certificate (the browser does). CodeAgent already knows how to use the
operating system's certificate store (truststore); this turns it on before any model is downloaded. AGENT_SYSTEM_CERTS=0
turns it off.
"""

from coding_agent.certificates import use_system_certificates


def trust_system_certificates() -> bool:
    """True when Python now checks certificates with the operating system's store."""
    return use_system_certificates()


HELP = """The model download failed on a certificate check. On a company network this usually means a proxy inspects HTTPS.
Try, in this order:
  1. Run again: the operating system's certificates are used automatically (set AGENT_SYSTEM_CERTS=0 to switch that off).
  2. Ask IT for the company root certificate (a .pem file) and set  SSL_CERT_FILE=<that file>  and  REQUESTS_CA_BUNDLE=<that file>.
  3. Download the models on a machine without the proxy (`huggingface-cli download <model>`), copy the folder
     ~/.cache/huggingface to this PC, and run with  HF_HUB_OFFLINE=1."""


def explain(error: BaseException) -> str | None:
    """HELP when the error is a certificate failure, else None."""
    text = str(error)
    return HELP if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text.lower() else None
