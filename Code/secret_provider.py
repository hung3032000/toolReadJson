import os

try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover
    keyring = None


_PREFIX = "toolreadjson"


def _env_name(env: str) -> str:
    return (env or "").strip().upper()


def _env_var(env: str, key: str) -> str:
    return f"{_PREFIX}_{_env_name(env)}_{key}".upper()


def _cfg_get(cfg: dict, section: str, key: str, default=""):
    return (cfg.get(section, {}) or {}).get(key, default)


def _read_keyring(env: str, key: str):
    if keyring is None:
        return None
    service = f"{_PREFIX}:{_env_name(env)}"
    try:
        return keyring.get_password(service, key)
    except Exception:
        return None


def _get_secret(env: str, key: str, fallback: str):
    from_env = os.getenv(_env_var(env, key))
    if from_env:
        return from_env
    from_store = _read_keyring(env, key)
    if from_store:
        return from_store
    return fallback


def resolve_secret_bundle(cfg: dict, env: str):
    env_name = _env_name(env)

    bearer_username = _get_secret(env_name, "BEARER_USERNAME", _cfg_get(cfg, "bearertoken", "username", ""))
    bearer_password = _get_secret(env_name, "BEARER_PASSWORD", _cfg_get(cfg, "bearertoken", "password", ""))
    bearer_apikey = _get_secret(env_name, "BEARER_APIKEY", _cfg_get(cfg, "bearertoken", "apikey", ""))

    api_username = _get_secret(env_name, "API_USERNAME", _cfg_get(cfg, "headers", "username", ""))
    api_password = _get_secret(env_name, "API_PASSWORD", _cfg_get(cfg, "headers", "password", ""))
    api_apikey = _get_secret(env_name, "API_APIKEY", _cfg_get(cfg, "headers", "apikey", ""))

    return {
        "bearertoken": {
            "username": bearer_username,
            "password": bearer_password,
            "apikey": bearer_apikey,
        },
        "headers": {
            "username": api_username,
            "password": api_password,
            "apikey": api_apikey,
        },
    }


def apply_secrets_to_headers(cfg: dict, env: str, headers: dict):
    out = dict(headers or {})
    bundle = resolve_secret_bundle(cfg, env)
    for k, v in (bundle.get("headers", {}) or {}).items():
        if v:
            out[k] = v
    return out

