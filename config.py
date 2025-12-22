import json
import os

DEFAULT_SETTINGS = {
    "username": "User",
    "broadcast_port": 12345,
    "tcp_chat_port": 12347,
    "tcp_file_port": 12346,
    "broadcast_ip": "<broadcast>"
}

SETTINGS_FILE = "settings.json"

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except:
        return DEFAULT_SETTINGS

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
