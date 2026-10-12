from yc_snippets.redact import redact


def test_redact_hides_tokens_and_private_keys():
    text = "\n".join(
        [
            "failed for token t1.9euAAA.bbbb",
            "oauth y0_AgAAAAAexample",
            "password=hunter2",
            "-----BEGIN PRIVATE KEY-----",
            "SECRET",
            "-----END PRIVATE KEY-----",
        ]
    )
    cleaned = redact(text)
    assert "t1.9eu" not in cleaned
    assert "y0_AgAAAAAexample" not in cleaned
    assert "hunter2" not in cleaned
    assert "SECRET" not in cleaned
    assert "[REDACTED IAM TOKEN]" in cleaned
    assert "[REDACTED PRIVATE KEY]" in cleaned
