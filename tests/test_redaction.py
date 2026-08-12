from xibalba_cortex.redaction import redact


def test_redacts_bearer_token():
    assert redact("Authorization: bearer sk-liveAbc123DEF456") == "Authorization: bearer [REDACTED]"


def test_redacts_api_key_field():
    assert redact("api_key: verysecretvalue123") == "api_key: [REDACTED]"
    assert redact("api-key=verysecretvalue123") == "api-key=[REDACTED]"


def test_redacts_secret_password_token_private_key_fields():
    assert redact("secret: abc123") == "secret=[REDACTED]"
    assert redact("password=hunter2") == "password=[REDACTED]"
    assert redact("private_key: -----BEGIN-----") == "private_key=[REDACTED]"


def test_redacts_sk_style_api_keys_anywhere_in_text():
    assert redact("here is my key sk-abcdefghijklmnop for the demo") == "here is my key [REDACTED] for the demo"


def test_redacts_64_char_hex_strings():
    hex64 = "a" * 64
    assert redact(f"hash: {hex64}") == "hash: [REDACTED]"


def test_leaves_ordinary_text_untouched():
    text = "The capital of France is Paris."
    assert redact(text) == text


def test_recurses_into_lists():
    assert redact(["clean text", "api_key: abc123secret"]) == ["clean text", "api_key: [REDACTED]"]


def test_recurses_into_dicts_and_stringifies_keys():
    result = redact({"note": "clean", "auth": "bearer abc123secretvalue", 5: "also fine"})
    assert result == {"note": "clean", "auth": "bearer [REDACTED]", "5": "also fine"}


def test_recurses_into_nested_structures():
    payload = {"tool_calls": [{"attributes": {"header": "api_key=supersecretvalue"}}]}
    result = redact(payload)
    assert result["tool_calls"][0]["attributes"]["header"] == "api_key=[REDACTED]"


def test_non_string_non_container_values_pass_through_unchanged():
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(3.14) == 3.14
    assert redact(True) is True
