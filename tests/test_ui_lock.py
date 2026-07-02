import os
import time
import threading
import tkinter as tk
from db import Database
from ui import LANMessengerApp
import unittest

class TestUILock(unittest.TestCase):
    def setUp(self):
        self.db_name = "test_ui_lock.db"
        self.key_file = ".master.key"
        if os.path.exists(self.db_name): os.remove(self.db_name)
        if os.path.exists(self.key_file): os.remove(self.key_file)

    def tearDown(self):
        if os.path.exists(self.db_name): os.remove(self.db_name)
        if os.path.exists(self.key_file): os.remove(self.key_file)

    def test_app_lock_logic(self):
        # We can't easily test the GUI interaction in headless environment
        # but we can test the state transitions if we mock the UI components
        # For now, we will verify that the app initializes correctly with a password.
        password = "test_password"

        # We'll use a mock for the dialog to simulate user input
        class MockDialog:
            def __init__(self, parent, callback):
                self.callback = callback
            def destroy(self):
                pass

        # Test the initial_unlock method directly
        app = LANMessengerApp.__new__(LANMessengerApp)
        app.db_name = self.db_name
        app.key_file = self.key_file
        app.password_hash = None
        app.db = None
        app.withdraw = lambda: None
        app.deiconify = lambda: None
        app.initialize_app = lambda: None

        # Case 1: Correct Password
        mock_dialog = MockDialog(None, None)
        app.initial_unlock(password, mock_dialog)
        self.assertIsNotNone(app.password_hash)
        self.assertIsNotNone(app.db)
        app.db.close()

        # Case 2: Incorrect Password (should not set app.db/master_password and show error)
        # Re-initialize to clear state
        app.master_password = None
        app.db = None
        import tkinter.messagebox
        old_show_error = tkinter.messagebox.showerror
        tkinter.messagebox.showerror = lambda title, msg: None

        app.initial_unlock("wrong_password", mock_dialog)
        self.assertIsNone(app.master_password)
        self.assertIsNone(app.db)

        tkinter.messagebox.showerror = old_show_error

    def test_manual_unlock(self):
        app = LANMessengerApp.__new__(LANMessengerApp)
        app.master_password = "secure_pass"
        app.locked = True
        app.reset_inactivity = lambda: None
        app.logger = type('MockLogger', (), {'log': lambda self, x, y: None})()

        # Successful unlock
        self.assertTrue(app.manual_unlock("secure_pass"))
        self.assertFalse(app.locked)

        # Failed unlock
        app.locked = True
        self.assertFalse(app.manual_unlock("wrong_pass"))
        self.assertTrue(app.locked)

if __name__ == "__main__":
    unittest.main()
