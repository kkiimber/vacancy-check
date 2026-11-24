import pytest

from tests.conftest import FakeResponse
from vacancy_check import llm


class ScriptedHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def ok(content="{}"):
    return FakeResponse({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def token():
    return FakeResponse({"access_token": "tok", "expires_at": 9999999999999})


def giga(http):
    return llm.GigaChat("cred", http=http)


def test_gigachat_gets_token_and_sends_schema():
    http = ScriptedHttp(token(), ok('{"issues": []}'))
    assert giga(http).complete("s", "u", {"type": "object"}) == '{"issues": []}'
    auth_call, chat_call = http.calls
    assert auth_call[1]["headers"]["Authorization"] == "Basic cred"
    assert auth_call[1]["data"] == {"scope": "GIGACHAT_API_PERS"}
    assert chat_call[1]["headers"]["Authorization"] == "Bearer tok"
    assert chat_call[1]["json"]["response_format"]["type"] == "json_schema"
    assert chat_call[0].endswith("/chat/completions")


def test_token_is_reused():
    http = ScriptedHttp(token(), ok(), ok())
    provider = giga(http)
    provider.complete("s", "u", {})
    provider.complete("s", "u", {})
    assert len(http.calls) == 3


def test_rejected_response_format_is_retried_without_it():
    http = ScriptedHttp(token(), FakeResponse({}, 400), ok())
    giga(http).complete("s", "u", {})
    assert "response_format" not in http.calls[-1][1]["json"]


def test_expired_token_is_refreshed_once():
    http = ScriptedHttp(token(), FakeResponse({}, 401), token(), ok())
    assert giga(http).complete("s", "u", {}) == "{}"


def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    http = ScriptedHttp(token(), FakeResponse({}, 429), ok())
    assert giga(http).complete("s", "u", {}) == "{}"


def test_quota_exhausted_is_a_clear_error():
    http = ScriptedHttp(token(), FakeResponse({}, 402))
    with pytest.raises(llm.AIError, match="квота"):
        giga(http).complete("s", "u", {})


def test_blacklist_finish_reason():
    body = {"choices": [{"message": {"content": ""}, "finish_reason": "blacklist"}]}
    http = ScriptedHttp(token(), FakeResponse(body))
    with pytest.raises(llm.AIError, match="отказалась"):
        giga(http).complete("s", "u", {})


def test_token_failure():
    http = ScriptedHttp(FakeResponse({}, 401))
    with pytest.raises(llm.AIError, match="токен"):
        giga(http).complete("s", "u", {})


def test_openai_compatible_uses_bearer_key():
    http = ScriptedHttp(ok())
    llm.OpenAICompatible("k", "m", "https://example.test/v1", http=http).complete("s", "u", {})
    url, kwargs = http.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer k"


def test_make_provider_requires_settings():
    with pytest.raises(llm.AIError):
        llm.make_provider("gigachat", {})
    with pytest.raises(llm.AIError):
        llm.make_provider("openai", {"LLM_API_KEY": "k"})
    assert llm.make_provider("gigachat", {"GIGACHAT_CREDENTIALS": "c"}).verify is True
