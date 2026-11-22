def test_placeholder_protocol_fields():
    # Documents the single-field contract; extend with shared/protocol.py once generated.
    fields = {"qr.detected": ["session_id", "request_id", "jpg", "digest", "attempt_id", "captured_at"]}
    assert "session_id" in fields["qr.detected"]
