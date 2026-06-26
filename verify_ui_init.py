import customtkinter as ctk
import os
from ui import LANMessengerApp

# Set environment to allow running without a real display
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

def test_ui_init():
    try:
        app = LANMessengerApp()
        print("UI Initialized successfully")
        app.update()
        app.destroy()
        return True
    except Exception as e:
        print(f"UI Initialization failed: {e}")
        return False

if __name__ == "__main__":
    test_ui_init()
