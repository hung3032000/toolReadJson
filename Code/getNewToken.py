import json
import requests
import base64
from util import update_message_status_box
with open("config.json", "r", encoding="utf-8") as f:
    config_data = json.load(f)
API_HOME_TEST = config_data["envData"].get("API_HOME_TEST", {})
API_HOME_STG = config_data["envData"].get("API_HOME_STG", {})
URL = config_data["envData"].get("URL", {})
def get_new_token(self):
    env = self.envCombobox.currentText().strip()
    api_home = API_HOME_STG if env == "STG" else API_HOME_TEST
    token_path = URL  # nên là path string, ví dụ "/oauth/token"
    if not isinstance(api_home, str) or not isinstance(token_path, str):
        update_message_status_box(self, "Config URL/host không hợp lệ (không phải string).")
        return

    url = api_home + token_path
    credentials = config_data.get("bearertoken", {})
    username = credentials.get("username", "")
    password = credentials.get("password", "")

    basic_auth_str = f"{username}:{password}"
    encoded_auth = base64.b64encode(basic_auth_str.encode("utf-8")).decode("utf-8")
    config_data["bearertoken"]["Authorization"] = f"Basic {encoded_auth}"

    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)

    response = None
    try:
        response = requests.post(url, headers=config_data["bearertoken"])
        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("access_token") or token_data.get("token")
            if not token:
                raise Exception("Token not found in response")
            update_message_status_box(self, f"New token is: {token}")
            return token
        else:
            update_message_status_box(self, f"Token request failed [{response.status_code}]: {response.text[:500]}")
            raise Exception(f"Token request failed {response.status_code}")
    except Exception as e:
        msg = response.text[:500] if response else str(e)
        update_message_status_box(self, f"Error getting token: {msg}")
        raise

def updateConfigToken(self, config_file="config.json"):
    try:
        new_token = get_new_token(self)
        if not new_token:
            return None
        config_data["headers"]["Authorization"] = f"Bearer {new_token}"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        update_message_status_box(self, "Token updated successfully")
        return config_data
    except Exception as e:
        update_message_status_box(self, f"Error updating token: {str(e)}")
        return None
