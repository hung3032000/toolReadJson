import base64
import json

import requests

from util import update_message_status_box


def _read_cfg(config_file="config.json"):
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_cfg(cfg, config_file="config.json"):
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


def _resolve_bundle(cfg, env):
    try:
        from secret_provider import resolve_secret_bundle

        return resolve_secret_bundle(cfg, env)
    except Exception:
        return {
            "bearertoken": cfg.get("bearertoken", {}) or {},
            "headers": cfg.get("headers", {}) or {},
        }


def get_new_token(self, config_file="config.json"):
    cfg = _read_cfg(config_file)
    env = (self.envCombobox.currentText() if hasattr(self, "envCombobox") else "TEST").strip().upper()

    api_home_test = cfg.get("envData", {}).get("API_HOME_TEST", "")
    api_home_stg = cfg.get("envData", {}).get("API_HOME_STG", "")
    token_path = cfg.get("envData", {}).get("URL", "")
    api_home = api_home_stg if env == "STG" else api_home_test
    if not isinstance(api_home, str) or not isinstance(token_path, str) or not api_home or not token_path:
        update_message_status_box(self, "Config URL/host is invalid.")
        return None

    url = api_home + token_path
    bundle = _resolve_bundle(cfg, env)
    bearer_cfg = bundle.get("bearertoken", {}) or {}

    username = bearer_cfg.get("username", "")
    password = bearer_cfg.get("password", "")
    if not username or not password:
        update_message_status_box(self, "Bearer username/password is missing.")
        return None

    basic_auth_str = f"{username}:{password}"
    encoded_auth = base64.b64encode(basic_auth_str.encode("utf-8")).decode("utf-8")

    token_headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if bearer_cfg.get("apikey"):
        token_headers["apikey"] = bearer_cfg["apikey"]

    response = None
    try:
        response = requests.post(url, headers=token_headers)
        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("access_token") or token_data.get("token")
            if not token:
                raise Exception("Token not found in response")
            update_message_status_box(self, "Token refreshed successfully")
            return token
        update_message_status_box(self, f"Token request failed [{response.status_code}]: {response.text[:300]}")
        raise Exception(f"Token request failed {response.status_code}")
    except Exception as e:
        msg = response.text[:300] if response is not None else str(e)
        update_message_status_box(self, f"Error getting token: {msg}")
        raise


def updateConfigToken(self, config_file="config.json"):
    try:
        new_token = get_new_token(self, config_file=config_file)
        if not new_token:
            return None
        cfg = _read_cfg(config_file)
        cfg.setdefault("headers", {})
        cfg["headers"]["Authorization"] = f"Bearer {new_token}"
        _write_cfg(cfg, config_file=config_file)
        update_message_status_box(self, "Token updated successfully")
        return cfg
    except Exception as e:
        update_message_status_box(self, f"Error updating token: {str(e)}")
        return None

