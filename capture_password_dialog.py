import customtkinter as ctk
from ui import LANMessengerApp
import threading
import time
from PIL import ImageGrab
import os

def capture_ui():
    # Set DISPLAY if not set
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":100"

    print("Starting LAN Messenger in a thread...")
    # Clean up old data to ensure fresh run
    if os.path.exists("lan_messenger.db"): os.remove("lan_messenger.db")
    if os.path.exists(".master.key"): os.remove(".master.key")

    def run_app():
        try:
            app = LANMessengerApp()
            app.mainloop()
        except Exception as e:
            print(f"App error: {e}")

    t = threading.Thread(target=run_app, daemon=True)
    t.start()

    print("Waiting for Password Dialog to appear...")
    time.sleep(5)

    print("Capturing screenshot...")
    try:
        img = ImageGrab.grab()
        img.save("password_dialog_screenshot.png")
        print("Screenshot saved to password_dialog_screenshot.png")
    except Exception as e:
        print(f"Screenshot failed: {e}")

if __name__ == "__main__":
    capture_ui()
