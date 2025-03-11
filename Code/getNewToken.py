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
    """
    Ví dụ về hàm lấy token từ API.
    Thay đổi URL và credentials theo yêu cầu của API thực tế.
    """
    env = self.envCombobox.currentText().strip()
    if env == "STG":
        url = API_HOME_STG + URL
    elif env == "TEST":
        url = API_HOME_TEST + URL
    else:
        update_message_status_box(self, "Invalid environment selected")
        return
                
    credentials = config_data.get("bearertoken", {})
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    basic_auth_str = username+':'+password
    encoded_auth = base64.b64encode(basic_auth_str.encode("utf-8")).decode("utf-8")
    config_data["bearertoken"]["Authorization"] = f"Basic {encoded_auth}"
        
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)
    try:
        response = requests.post(url, headers=credentials)
        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("access_token")  # Giả sử token được trả về trong key "token"
            if token:
                update_message_status_box(self, f"New token is: {token}")
                return token
            else:
                raise Exception("Token not found in response")
        else:
            update_message_status_box(self, f"Token request failed with status code: {response.text}")
            raise Exception(f"Token request failed with status code {response.status_code}")
    except Exception as e:
        update_message_status_box(self, f"Error getting token: {response.text}")
        raise Exception(f"Error getting token: {str(e)}")

def updateConfigToken(self, config_file="config.json"):
    """
    Đọc file config.json, lấy token mới từ API và cập nhật vào phần headers:
        "Authorization": "Bearer {new_token}"
    Sau đó ghi đè file config.json với dữ liệu cập nhật.
    Trả về cấu hình đã cập nhật hoặc None nếu có lỗi.
    """
    try:
        new_token = get_new_token(self)
        config_data["headers"]["Authorization"] = f"Bearer {new_token}"
        
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        
        update_message_status_box(self, "Token updated successfully")
        return config_data
    except Exception as e:
        update_message_status_box(self, f"Error updating token: {str(e)}")
        return None
