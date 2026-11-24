import time
import uuid

import requests


class AIError(Exception):
    pass


class ChatProvider:
    name = ""

    def __init__(self, model, base_url, timeout=90, verify=True, http=None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self.http = http or requests

    def headers(self):
        raise NotImplementedError

    def response_format(self, schema):
        return None

    def reset_auth(self):
        pass

    def _send(self, payload):
        url = f"{self.base_url}/chat/completions"
        for attempt in range(3):
            resp = self.http.post(
                url, headers=self.headers(), json=payload, timeout=self.timeout, verify=self.verify
            )
            if resp.status_code == 401 and attempt == 0:
                self.reset_auth()
                continue
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        return resp

    def complete(self, system, user, schema):
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        fmt = self.response_format(schema)
        if fmt:
            payload["response_format"] = fmt
        try:
            resp = self._send(payload)
            if resp.status_code in (400, 422) and fmt:
                payload.pop("response_format")
                resp = self._send(payload)
        except requests.RequestException as err:
            raise AIError(f"{self.name}: запрос не удался: {err}")
        if resp.status_code == 402:
            raise AIError(f"{self.name}: квота исчерпана")
        if resp.status_code == 429:
            raise AIError(f"{self.name}: слишком много запросов")
        if resp.status_code != 200:
            raise AIError(f"{self.name}: ответ {resp.status_code}: {resp.text[:200]}")
        try:
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "blacklist":
                raise AIError(f"{self.name}: модель отказалась отвечать на эту тему")
            return choice["message"]["content"]
        except (KeyError, IndexError, ValueError):
            raise AIError(f"{self.name}: неожиданный формат ответа")


class GigaChat(ChatProvider):
    name = "gigachat"

    def __init__(
        self,
        credentials,
        model="GigaChat-2-Max",
        scope="GIGACHAT_API_PERS",
        base_url="https://api.giga.chat/v1",
        auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.credentials = credentials
        self.scope = scope
        self.auth_url = auth_url
        self._token = None
        self._expires = 0

    def reset_auth(self):
        self._token = None

    def _fetch_token(self):
        try:
            resp = self.http.post(
                self.auth_url,
                headers={
                    "Authorization": f"Basic {self.credentials}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": self.scope},
                timeout=self.timeout,
                verify=self.verify,
            )
        except requests.RequestException as err:
            raise AIError(f"gigachat: не удалось получить токен: {err}")
        if resp.status_code != 200:
            raise AIError(f"gigachat: токен не выдан ({resp.status_code})")
        body = resp.json()
        expires = body.get("expires_at", 0)
        self._expires = expires / 1000 if expires > 1e11 else expires
        self._token = body["access_token"]

    def headers(self):
        if not self._token or self._expires - 60 < time.time():
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def response_format(self, schema):
        return {"type": "json_schema", "schema": schema, "strict": True}


class OpenAICompatible(ChatProvider):
    name = "openai"

    def __init__(self, api_key, model, base_url, **kwargs):
        super().__init__(model, base_url, **kwargs)
        self.api_key = api_key

    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def response_format(self, schema):
        return {"type": "json_object"}


def make_provider(kind, env, model=None):
    if kind == "gigachat":
        credentials = env.get("GIGACHAT_CREDENTIALS")
        if not credentials:
            raise AIError("не задан GIGACHAT_CREDENTIALS")
        if env.get("GIGACHAT_INSECURE") == "1":
            verify = False
        else:
            verify = env.get("GIGACHAT_CA_BUNDLE") or True
        return GigaChat(
            credentials,
            model=model or env.get("GIGACHAT_MODEL") or "GigaChat-2-Max",
            scope=env.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            verify=verify,
        )
    if kind == "openai":
        key, base = env.get("LLM_API_KEY"), env.get("LLM_BASE_URL")
        name = model or env.get("LLM_MODEL")
        if not (key and base and name):
            raise AIError("для провайдера openai нужны LLM_API_KEY, LLM_BASE_URL и LLM_MODEL")
        return OpenAICompatible(key, name, base)
    raise AIError(f"неизвестный провайдер: {kind}")
