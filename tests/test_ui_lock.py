
import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Mocking ctk before importing ui
mock_ctk = MagicMock()
sys.modules['customtkinter'] = mock_ctk
import customtkinter as ctk

# Mocking other dependencies
sys.modules['audit'] = MagicMock()
import audit

from db import Database
import ui

class TestUILockLogic(unittest.TestCase):
    def setUp(self):
        self.db_file = "test_ui_lock.db"
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
        # Force remove .master.key to ensure clean state
        if os.path.exists(".master.key"):
            os.remove(".master.key")
        self.db = Database(self.db_file)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
        if os.path.exists(".master.key"):
            os.remove(".master.key")

    def test_lock_screen_setup_flow(self):
        parent = MagicMock()
        on_unlock = MagicMock()

        # Test setup
        ls = ui.LockScreen(parent, self.db, on_unlock)
        ls.password_entry = MagicMock()
        ls.password_entry.get.return_value = "new_password"

        self.assertTrue(self.db.needs_setup())
        ls.attempt_unlock()

        self.assertFalse(self.db.needs_setup())
        self.assertFalse(self.db.is_locked())
        on_unlock.assert_called_once()

    def test_lock_screen_unlock_flow(self):
        password = "secret_password"
        self.db.setup(password)
        self.db.lock_db()
        self.assertTrue(self.db.is_locked())

        parent = MagicMock()
        on_unlock = MagicMock()

        ls = ui.LockScreen(parent, self.db, on_unlock)
        ls.password_entry = MagicMock()

        # Wrong password
        ls.password_entry.get.return_value = "wrong"
        ls.attempt_unlock()
        self.assertTrue(self.db.is_locked())
        on_unlock.assert_not_called()

        # Correct password
        ls.password_entry.get.return_value = password
        ls.attempt_unlock()
        self.assertFalse(self.db.is_locked())
        on_unlock.assert_called_once()

    @patch('ui.LANMessengerApp.check_lock')
    def test_inactivity_timer_trigger(self, mock_check_lock):
        with patch('ui.load_settings', return_value={"username": "test", "tcp_chat_port": 1, "tcp_file_port": 2}):
            # Mock complex objects that __init__ tries to create
            with patch('ui.FileTransferManager'), patch('ui.NetworkManager'), patch('ui.DiscoveryManager'), patch('ui.ThreadPoolExecutor'):
                app = ui.LANMessengerApp()
                app.db = self.db
                self.db.setup("pass")

                self.assertFalse(self.db.is_locked())
                app._on_inactivity()
                self.assertTrue(self.db.is_locked())
                mock_check_lock.assert_called()

if __name__ == "__main__":
    unittest.main()
