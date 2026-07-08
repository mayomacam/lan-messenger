import os
import threading
import time
import tkinter as tk
from ui import LANMessengerApp
from PIL import ImageGrab
import subprocess

def run_verification():
    # Ensure fresh state
    if os.path.exists("lan_messenger.db"): os.remove("lan_messenger.db")
    if os.path.exists(".master.key"): os.remove(".master.key")

    app = None
    def start_app():
        nonlocal app
        try:
            app = LANMessengerApp()
            app.mainloop()
        except Exception as e:
            print(f"Error starting app: {e}")

    t = threading.Thread(target=start_app, daemon=True)
    t.start()

    time.sleep(5) # Wait for password dialog

    # Try to find the password dialog and type "password"
    # In Linux/X11 we can use xdotool
    try:
        subprocess.run(["xdotool", "type", "password"], check=True)
        subprocess.run(["xdotool", "key", "Return"], check=True)
    except Exception as e:
        print(f"xdotool failed: {e}")

    time.sleep(5) # Wait for main UI

    try:
        img = ImageGrab.grab()
        img.save("main_ui_screenshot.png")
        print("Main UI screenshot saved.")
    except Exception as e:
        print(f"Main UI screenshot failed: {e}")

    # Now test lock
    try:
        subprocess.run(["xdotool", "key", "ctrl+l"], check=True) # I didn't add this shortcut but I can click button
        # Actually I added a "Lock App" button. Finding it with xdotool is hard.
        # I'll just call lock_app directly if I have the app object.
        if app:
            app.after(0, app.lock_app)
    except Exception as e:
        print(f"Lock app failed: {e}")

    time.sleep(2)
    try:
        img = ImageGrab.grab()
        img.save("locked_ui_screenshot.png")
        print("Locked UI screenshot saved.")
    except Exception as e:
        print(f"Locked UI screenshot failed: {e}")

if __name__ == "__main__":
    run_verification()
