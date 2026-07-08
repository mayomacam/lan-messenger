
import os
import time
import threading
from PIL import ImageGrab
from db import Database
from ui import LANMessengerApp

def take_screenshot(name):
    # Ensure display is set (caller should do this, but just in case)
    os.system(f"import -window root /home/jules/verification/screenshots/{name}.png")

def run_app_and_screenshot():
    db_file = "verify_ui.db"
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(".master.key"): os.remove(".master.key")

    app = LANMessengerApp()

    def actions():
        time.sleep(5) # Wait for app to start and LockScreen to show
        print("Capturing LockScreen (Initial Setup)...")
        img = ImageGrab.grab()
        img.save("/home/jules/verification/screenshots/lock_screen_setup.png")

        # Simulate typing password and clicking setup
        # Since I can't easily simulate input to CustomTkinter from here without more tools,
        # I will manually call the unlock logic if possible or just use mocks for the screenshot script
        # Alternatively, I'll just capture the LockScreen as it is.

        # To show the main app, I'll bypass the lock screen in a separate run or by calling methods
        app.db.setup("password")
        app.after(0, app.after_unlock)

        time.sleep(2)
        print("Capturing Main App...")
        img = ImageGrab.grab()
        img.save("/home/jules/verification/screenshots/main_app.png")

        app.after(0, app.lock_app)
        time.sleep(2)
        print("Capturing LockScreen (Locked)...")
        img = ImageGrab.grab()
        img.save("/home/jules/verification/screenshots/lock_screen_locked.png")

        app.after(0, app.on_closing)

    threading.Thread(target=actions, daemon=True).start()
    app.mainloop()

    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(".master.key"): os.remove(".master.key")

if __name__ == "__main__":
    os.makedirs("/home/jules/verification/screenshots", exist_ok=True)
    run_app_and_screenshot()
