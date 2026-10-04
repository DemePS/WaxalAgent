def certs_for_models() -> None:
    """Before a model is downloaded: trust the operating system's certificates (company proxy)."""
    from .. import certs
    certs.trust_system_certificates()
