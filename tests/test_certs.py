from waxal_agent import certs


def test_system_certificates_are_requested_from_codeagent(monkeypatch):
    calls = []
    monkeypatch.setattr(certs, "use_system_certificates", lambda: calls.append(1) or True)
    assert certs.trust_system_certificates() is True and calls == [1]


def test_a_certificate_failure_gets_an_explanation_and_other_errors_do_not():
    failure = Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate")
    help_text = certs.explain(failure)
    assert help_text and "SSL_CERT_FILE" in help_text
    assert certs.explain(Exception("connection reset")) is None
