import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, Menu
import socket
import os
import threading
import time
import shutil
import json
import pyotp
import qrcode
from PIL import Image, ImageTk
import audit
import ssl_utils
import security_engine
from concurrent.futures import ThreadPoolExecutor
from db import Database
from network import NetworkManager, DiscoveryManager
from file_transfer import FileTransferManager
from config import load_settings, save_settings

class MasterPasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.title("Unlock LAN Messenger")
        self.geometry("400x250")
        self.callback = callback

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Master Password Required", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, pady=(30, 10))
        ctk.CTkLabel(self, text="Enter password to unlock the application and database.", font=ctk.CTkFont(size=12)).grid(row=1, column=0, pady=(0, 20))

        self.password_entry = ctk.CTkEntry(self, placeholder_text="Master Password", show="*")
        self.password_entry.grid(row=2, column=0, padx=50, pady=10, sticky="ew")
        self.password_entry.bind("<Return>", self.on_submit)

        self.submit_btn = ctk.CTkButton(self, text="Unlock", command=self.on_submit)
        self.submit_btn.grid(row=3, column=0, pady=20)

        self.after(100, lambda: self.password_entry.focus_set())
        self.grab_set()
        self.bind("<Escape>", lambda e: self.on_cancel())

    def on_submit(self, event=None):
        password = self.password_entry.get()
        if not password:
            return
        self.callback(password, self)

    def on_cancel(self):
        self.master.destroy()

class LockScreen(ctk.CTkFrame):
    def __init__(self, parent, unlock_callback):
        super().__init__(parent, fg_color=("#DBDBDB", "#2B2B2B"))
        self.unlock_callback = unlock_callback
        self.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 4), weight=1)

        ctk.CTkLabel(self, text="Application Locked", font=ctk.CTkFont(size=30, weight="bold")).grid(row=1, column=0, pady=20)

        self.pass_entry = ctk.CTkEntry(self, placeholder_text="Master Password", show="*", width=300)
        self.pass_entry.grid(row=2, column=0, pady=10)
        self.pass_entry.bind("<Return>", self.on_unlock)

        self.unlock_btn = ctk.CTkButton(self, text="Unlock App", command=self.on_unlock)
        self.unlock_btn.grid(row=3, column=0, pady=20)

        self.pass_entry.focus_set()

    def on_unlock(self, event=None):
        password = self.pass_entry.get()
        if self.unlock_callback(password):
            self.destroy()
        else:
            self.pass_entry.delete(0, "end")
            messagebox.showerror("Error", "Invalid Password")

class PeerSecurityDialog(ctk.CTkToplevel):
    def __init__(self, parent, db, peer_ip, peer_name, on_update_cb=None):
        super().__init__(parent)
        self.title(f"Security: {peer_name}")
        self.geometry("450x600")
        self.db = db
        self.peer_ip = peer_ip
        self.peer_name = peer_name
        self.on_update_cb = on_update_cb
        self.logger = audit.get_logger()

        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

        # Load current perms
        self.peer_info = self.db.get_trusted_peer(peer_ip)
        self.perms = self.db.get_peer_permissions(peer_ip)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=f"Manage Peer: {peer_name}", font=("Arial", 16, "bold")).grid(row=0, column=0, pady=20)
        ctk.CTkLabel(self, text=f"IP: {peer_ip}", font=("Arial", 12)).grid(row=1, column=0, pady=(0, 20))

        # --- Safety Number Section ---
        sn_frame = ctk.CTkFrame(self)
        sn_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        ctk.CTkLabel(sn_frame, text="Safety Number (Verification Code)", font=("Arial", 12, "bold")).pack(pady=(10, 5))

        my_fp = ssl_utils.get_local_fingerprint()
        peer_fp = self.peer_info[2] if self.peer_info else None
        safety_number = ssl_utils.get_safety_number(my_fp, peer_fp)

        sn_display = ctk.CTkLabel(sn_frame, text=safety_number, font=("Courier", 14), text_color="#3B8ED0")
        sn_display.pack(pady=5)

        self.copy_sn_btn = ctk.CTkButton(sn_frame, text="Copy", width=60, height=20,
                                        command=lambda: self.copy_safety_number(safety_number))
        self.copy_sn_btn.pack(pady=5)

        ctk.CTkLabel(sn_frame, text="Verify this code with the peer out-of-band.", font=("Arial", 10, "italic")).pack(pady=(0, 10))

        # Verified Toggle
        self.verified_var = ctk.BooleanVar(value=bool(self.perms.get('is_verified', False)))
        self.verify_chk = ctk.CTkSwitch(self, text="VERIFIED IDENTITY", variable=self.verified_var, progress_color="green")
        self.verify_chk.grid(row=3, column=0, pady=10, padx=40, sticky="w")

        # Blocked
        self.blocked_var = ctk.BooleanVar(value=bool(self.perms.get('is_blocked', False)))
        self.block_chk = ctk.CTkSwitch(self, text="BLOCK PEER", variable=self.blocked_var, progress_color="red")
        self.block_chk.grid(row=4, column=0, pady=10, padx=40, sticky="w")

        ctk.CTkLabel(self, text="Granular Permissions:", font=("Arial", 12, "bold")).grid(row=5, column=0, pady=(20, 10), padx=40, sticky="w")

        # Chat
        self.chat_var = ctk.BooleanVar(value=bool(self.perms.get('can_chat', True)))
        self.chat_chk = ctk.CTkSwitch(self, text="Can Chat", variable=self.chat_var)
        self.chat_chk.grid(row=6, column=0, pady=5, padx=60, sticky="w")

        # List Files
        self.list_var = ctk.BooleanVar(value=bool(self.perms.get('can_list_files', True)))
        self.list_chk = ctk.CTkSwitch(self, text="Can Browse Files", variable=self.list_var)
        self.list_chk.grid(row=7, column=0, pady=5, padx=60, sticky="w")

        # Download Files
        self.down_var = ctk.BooleanVar(value=bool(self.perms.get('can_download_files', True)))
        self.down_chk = ctk.CTkSwitch(self, text="Can Download Files", variable=self.down_var)
        self.down_chk.grid(row=8, column=0, pady=5, padx=60, sticky="w")

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=9, column=0, pady=30)

        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="gray", command=self.destroy).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Save", width=100, command=self.save).pack(side="left", padx=10)

    def copy_safety_number(self, number):
        self.clipboard_clear()
        self.clipboard_append(number)
        self.copy_sn_btn.configure(text="Copied!", fg_color="#2ecc71")

        def reset():
            if self.copy_sn_btn.winfo_exists():
                self.copy_sn_btn.configure(text="Copy", fg_color=("#3B8ED0", "#1F6AA5"))
        self.after(2000, reset)

    def save(self):
        new_perms = {
            'is_blocked': 1 if self.blocked_var.get() else 0,
            'can_chat': 1 if self.chat_var.get() else 0,
            'can_list_files': 1 if self.list_var.get() else 0,
            'can_download_files': 1 if self.down_var.get() else 0,
            'is_verified': 1 if self.verified_var.get() else 0
        }
        self.db.update_peer_permissions(self.peer_ip, new_perms)

        if self.logger:
            self.logger.log("SECURITY_POLICY_CHANGE", f"Updated permissions for {self.peer_name} ({self.peer_ip}): {new_perms}")

        if self.on_update_cb:
            self.on_update_cb()
        elif hasattr(self.master, 'refresh_peers'):
            self.master.refresh_peers()
        self.destroy()

class MFASetupDialog(ctk.CTkToplevel):
    def __init__(self, parent, db, on_complete_cb=None):
        super().__init__(parent)
        self.title("MFA Setup")
        self.geometry("450x650")
        self.db = db
        self.on_complete_cb = on_complete_cb
        self.secret = pyotp.random_base32()
        self.logger = audit.get_logger()

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Multi-Factor Authentication Setup", font=("Arial", 20, "bold")).grid(row=0, column=0, pady=20)
        ctk.CTkLabel(self, text="1. Scan the QR code with your Authenticator app", font=("Arial", 12)).grid(row=1, column=0, pady=10)

        # Generate QR Code
        totp_uri = pyotp.totp.TOTP(self.secret).provisioning_uri(name="User", issuer_name="LAN Messenger")
        qr = qrcode.QRCode(version=1, box_size=5, border=2)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Convert to PhotoImage
        self.qr_photo = ImageTk.PhotoImage(qr_img)
        self.qr_label = ctk.CTkLabel(self, image=self.qr_photo, text="")
        self.qr_label.grid(row=2, column=0, pady=10)

        ctk.CTkLabel(self, text=f"Secret Key: {self.secret}", font=("Courier", 12)).grid(row=3, column=0, pady=5)

        ctk.CTkLabel(self, text="2. Enter the 6-digit code to verify", font=("Arial", 12)).grid(row=4, column=0, pady=(20, 5))
        self.verify_entry = ctk.CTkEntry(self, placeholder_text="000000", width=150)
        self.verify_entry.grid(row=5, column=0, pady=5)
        self.verify_entry.bind("<Return>", lambda e: self.verify_and_save())

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.grid(row=6, column=0, pady=5)

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.grid(row=7, column=0, pady=20)

        ctk.CTkButton(self.btn_frame, text="Cancel", fg_color="gray", command=self.destroy).pack(side="left", padx=10)
        self.save_btn = ctk.CTkButton(self.btn_frame, text="Verify & Enable", command=self.verify_and_save)
        self.save_btn.pack(side="left", padx=10)

        self.transient(parent)
        self.grab_set()

    def verify_and_save(self):
        code = self.verify_entry.get().strip()
        totp = pyotp.TOTP(self.secret)
        if totp.verify(code):
            self.db.set_config("mfa_secret", self.secret, encrypt=True)
            self.db.set_config("mfa_enabled", "1")
            if self.logger:
                self.logger.log("MFA_ENABLED", "TOTP Multi-Factor Authentication enabled.")
            messagebox.showinfo("Success", "MFA has been successfully enabled!")
            if self.on_complete_cb:
                self.on_complete_cb()
            self.destroy()
        else:
            self.status_label.configure(text="Invalid code. Please try again.", text_color="red")
            self.verify_entry.delete(0, "end")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="Authentication Required"):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x200")
        self.result = None

        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Enter Master Password:", font=("Arial", 14)).grid(row=0, column=0, pady=20)

        self.entry = ctk.CTkEntry(self, show="*", width=300)
        self.entry.grid(row=1, column=0, padx=20, pady=10)
        self.entry.bind("<Return>", self.on_ok)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=20)

        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="gray", command=self.on_cancel).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="OK", width=100, command=self.on_ok).pack(side="left", padx=10)

        self.transient(parent)
        self.grab_set()
        self.entry.focus_set()
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.master.wait_window(self)

    def on_ok(self, event=None):
        self.result = self.entry.get()
        self.destroy()

    def on_cancel(self):
        self.destroy()

class LockScreen(ctk.CTkFrame):
    def __init__(self, parent, password_callback):
        super().__init__(parent, fg_color="#1a1a1a")
        self.password_callback = password_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 4), weight=1)

        ctk.CTkLabel(self, text="LAN Messenger Locked", font=("Arial", 24, "bold")).grid(row=1, column=0, pady=40)

        self.entry = ctk.CTkEntry(self, show="*", width=300, height=40, placeholder_text="Master Password")
        self.entry.grid(row=2, column=0, pady=10)
        self.entry.bind("<Return>", self.on_unlock)

        self.unlock_btn = ctk.CTkButton(self, text="Unlock", width=150, height=40, command=self.on_unlock)
        self.unlock_btn.grid(row=3, column=0, pady=20)

        self.entry.focus_set()

        self.configure(fg_color="#1a1a1a")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 4), weight=1)

        ctk.CTkLabel(self, text="LAN Messenger Locked", font=("Arial", 24, "bold")).grid(row=1, column=0, pady=40)

        self.entry = ctk.CTkEntry(self, show="*", width=300, height=40, placeholder_text="Master Password")
        self.entry.grid(row=2, column=0, pady=10)
        self.entry.bind("<Return>", self.on_unlock)

        self.unlock_btn = ctk.CTkButton(self, text="Unlock", width=150, height=40, command=self.on_unlock)
        self.unlock_btn.grid(row=3, column=0, pady=20)

        self.entry.focus_set()
        self.grab_set()

    def on_unlock(self, event=None):
        pw = self.entry.get()
        if self.password_callback(pw):
            self.destroy()
        else:
            self.entry.delete(0, "end")
            self.entry.configure(placeholder_text="Invalid Password!", placeholder_text_color="red")

class LockScreen(ctk.CTkFrame):
    def __init__(self, parent, db, on_unlock):
        super().__init__(parent, fg_color=parent._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"]))
        self.db = db
        self.on_unlock = on_unlock
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 1, 2, 3), weight=1)

        inner_frame = ctk.CTkFrame(self)
        inner_frame.grid(row=1, column=0, padx=20, pady=20)

        self.title_label = ctk.CTkLabel(inner_frame, text="Application Locked", font=("Arial", 24, "bold"))
        self.title_label.pack(pady=20, padx=40)

        self.info_label = ctk.CTkLabel(inner_frame, text="Please enter your Master Password")
        self.info_label.pack(pady=10)

        self.password_entry = ctk.CTkEntry(inner_frame, show="*", width=250, placeholder_text="Master Password")
        self.password_entry.pack(pady=10, padx=40)
        self.password_entry.bind("<Return>", lambda e: self.attempt_unlock())

        # MFA Entry (Initially hidden)
        self.mfa_entry = ctk.CTkEntry(inner_frame, width=250, placeholder_text="TOTP Code (6-digits)")
        self.mfa_enabled = self.db.get_config("mfa_enabled") == "1"
        if self.mfa_enabled:
            self.mfa_entry.pack(pady=10, padx=40)
            self.mfa_entry.bind("<Return>", lambda e: self.attempt_unlock())

        self.btn = ctk.CTkButton(inner_frame, text="Unlock", command=self.attempt_unlock)
        self.btn.pack(pady=20)

        if self.db.needs_setup():
            self.title_label.configure(text="Initial Security Setup")
            self.info_label.configure(text="Create a Master Password to protect your database")
            self.btn.configure(text="Setup & Unlock")

        self.password_entry.focus_set()

    def attempt_unlock(self):
        password = self.password_entry.get()
        if not password:
            return

        if self.db.needs_setup():
            self.db.setup(password)
            audit.get_logger().log("MASTER_PASSWORD_SETUP", "Initial master password configured.")
            self.on_unlock()
            self.destroy()
        else:
            if self.db.unlock(password):
                # Check MFA if enabled
                if self.mfa_enabled:
                    mfa_code = self.mfa_entry.get().strip()
                    mfa_secret = self.db.get_config("mfa_secret", decrypt=True)
                    if not mfa_secret:
                        # Fallback if secret is missing but enabled
                        audit.get_logger().log("APP_UNLOCKED", "Application successfully unlocked (MFA Secret Missing).")
                        self.on_unlock()
                        self.destroy()
                        return

                    totp = pyotp.TOTP(mfa_secret)
                    if totp.verify(mfa_code):
                        audit.get_logger().log("APP_UNLOCKED", "Application successfully unlocked with MFA.")
                        self.on_unlock()
                        self.destroy()
                    else:
                        audit.get_logger().log("MFA_VERIFY_FAILURE", "Failed MFA verification attempt.")
                        self.info_label.configure(text="Invalid TOTP Code! Try again.", text_color="red")
                        self.mfa_entry.delete(0, "end")
                        # Re-lock the DB because password was correct but MFA failed
                        self.db.lock_db()
                else:
                    audit.get_logger().log("APP_UNLOCKED", "Application successfully unlocked.")
                    self.on_unlock()
                    self.destroy()
            else:
                audit.get_logger().log("INVALID_PASSWORD_ATTEMPT", "Failed unlock attempt.")
                self.info_label.configure(text="Invalid Password! Try again.", text_color="red")
                self.password_entry.delete(0, "end")

class LANMessengerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw() # Hide main window until unlocked
        self.title("LAN Messenger")
        self.geometry("1100x700")

        self._chat_history_after_id = None
        self._lock_timer_id = None
        self._inactivity_timeout = 300000 # 5 minutes in ms

        # Load Settings
        self.settings = load_settings()
        self._master_password = None
        self._last_activity = time.time()
        self._lock_timeout = 300
        self._locked = False

        # Prompt for password
        while True:
            password = self._prompt_password()
            if not password:
                self.destroy()
                return

            try:
                self.db = Database(password)
                self._master_password = password
                break
            except ValueError as e:
                messagebox.showerror("Error", f"Authentication failed: {e}")

        self.deiconify() # Show app
        self._chat_history_after_id = None

        # State
        self.username = self.settings.get("username", "")

        # Prompt for username if not set
        if not self.username or self.username.startswith("User_"):
            self.prompt_username()

        audit.init_logger(self.db)
        self.logger = audit.get_logger()
        security_engine.init_engine(self.db)
        self.logger.log("APP_START", f"Application started for user {self.username}")

        # Thread pool for non-blocking network calls
        self.executor = ThreadPoolExecutor(max_workers=5)

        # Init Networking with Configured Ports
        self.file_manager = FileTransferManager(
            self.db,
            port=self.settings["tcp_file_port"],
            bind_ip=self.settings.get("bind_ip", "0.0.0.0"),
            auth_token=self.settings.get("auth_token") or None,
            allowed_ips=self.settings.get("allowed_ips") or None,
        )
        self.network = NetworkManager(
            self.db,
            port=self.settings["tcp_chat_port"],
            callback_update_ui=self.on_network_event,
            auth_token=self.settings.get("auth_token") or None,
            allowed_ips=self.settings.get("allowed_ips") or None,
        )

        self.discovery = DiscoveryManager(
            username=self.username,
            chat_port=self.settings["tcp_chat_port"],
            callback_new_peer=lambda ip, name: self.on_network_event('NEW_PEER', ip, name),
            auth_token=self.settings.get("auth_token") or None
        )

        self.peers = {} # ip -> username
        self.peer_trust = {} # ip -> trust_level
        self.private_chats = {} # ip -> CTkTextbox
        self.private_chat_tabs = {} # tab_name -> ip
        self.private_entries = {} # ip -> CTkEntry
        self._private_chat_after_ids = {} # ip -> after_id
        self._last_peers_snapshot = ""
        self._last_search_query = ""
        self.current_private_peer = None
        self.current_file_view_source = "Local" # "Local" or IP

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # UI Components
        self.create_sidebar()
        self.create_main_area()

        # App Locking
        self.lock_screen = None
        self.check_lock()

        # Inactivity tracking
        self.bind("<Any-KeyPress>", self._reset_lock_timer)
        self.bind("<Any-Button>", self._reset_lock_timer)
        self._reset_lock_timer()

        # Periodic Updates
        self.after(2000, self.refresh_peers)
        self.load_chat_history()
        self.after(100, lambda: self.msg_entry.focus_set())
        self.bind("<Control-f>", self.focus_search)
        self.bind("<Control-F>", self.focus_search)

        # Activity Tracking
        self.bind_all("<KeyPress>", self._update_activity)
        self.bind_all("<Button>", self._update_activity)

        # Start Message Reaper
        self.reaper_thread = threading.Thread(target=self.message_reaper_loop, daemon=True)
        self.reaper_thread.start()

        # Start inactivity checker
        self.after(10000, self._check_inactivity)

    def _update_activity(self, event=None):
        self._last_activity = time.time()

    def _check_inactivity(self):
        if time.time() - self._last_activity > self._lock_timeout:
            self.lock_app()
        self.after(10000, self._check_inactivity)

    def lock_app(self):
        if not self._locked:
            self._locked = True
            LockScreen(self, self._verify_unlock)

    def _verify_unlock(self, password):
        if password == self._master_password:
            self._locked = False
            self._update_activity()
            return True
        return False

    def _prompt_password(self):
        pw_dialog = PasswordDialog(self)
        return pw_dialog.result

    def focus_search(self, event=None):
        self.tabview.set("Global Chat")
        self.search_entry.focus_set()

    def _refresh_after_reap(self):
        """Thread-safe UI refresh after background reaping."""
        if not self.winfo_exists():
            return
        # Only refresh visible chat tabs to save resources
        current_tab = self.tabview.get()
        if current_tab == "Global Chat":
            self.load_chat_history(debounce=True)
        elif current_tab.startswith("Chat: "):
            if self.current_private_peer:
                self.load_private_chat(self.current_private_peer)

    def message_reaper_loop(self):
        """Background thread for periodic database maintenance (runs every 15s)."""
        while True:
            try:
                # Reap messages and files in background
                msg_count = self.db.reap_expired_messages()
                file_count = self.db.delete_expired_files()

                if msg_count > 0 or file_count > 0:
                    if msg_count > 0:
                        self.logger.log("DATA_RETENTION", f"Automatically reaped {msg_count} expired messages.")
                    if file_count > 0:
                        self.logger.log("DATA_RETENTION", f"Automatically reaped {file_count} expired file shares.")

                    # Schedule UI refresh on main thread
                    self.after(0, lambda: self._refresh_after_reap(msg_count))
            except Exception as e:
                print(f"[DEBUG] Reaper error: {e}")
            time.sleep(15)

    def prompt_username(self):
        dialog = ctk.CTkInputDialog(text="Enter your username:", title="Set Username")
        name = dialog.get_input()
        if name and name.strip():
            self.username = name.strip()
            self.settings["username"] = self.username
            save_settings(self.settings)
        else:
            # Fallback to default
            self.username = "User_" + str(int(time.time()))[-4:]
            self.settings["username"] = self.username
            save_settings(self.settings)

    def on_network_event(self, event_type, *args):
        # Dispatch to main thread
        if self.winfo_exists():
            self.after(0, lambda: self._handle_event(event_type, *args))

    def _handle_event(self, event_type, *args):
        if event_type == 'NEW_PEER':
            ip, name = args[0], args[1]
            is_new_peer = ip not in self.peers
            self.peers[ip] = name
            if is_new_peer:
                self.executor.submit(self.network.send_hello, ip, self.username)
        elif event_type == 'MSG':
             self.load_chat_history(debounce=True)
        elif event_type == 'MSG_PRIV':
             peer_ip = args[3]
             if peer_ip in self.private_chats:
                 self.load_private_chat(peer_ip)
             else:
                 sender_name = self.peers.get(peer_ip, args[1])
                 self.open_private_chat(peer_ip, sender_name)
        elif event_type in ['EDIT', 'DELETE']:
             self.load_chat_history(debounce=True)
        elif event_type == 'SECURITY_ALERT':
             msg = args[0]
             messagebox.showwarning("Security Alert", msg)

    def create_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LAN Messenger", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        username_frame = ctk.CTkFrame(self.sidebar_frame)
        username_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(username_frame, text="User:").pack(side="left", padx=(5, 2))
        self.username_entry = ctk.CTkEntry(username_frame, placeholder_text="Username")
        self.username_entry.insert(0, self.username)
        self.username_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.username_entry.bind("<Return>", self.update_username)

        self.change_name_btn = ctk.CTkButton(username_frame, text="Set", width=50, command=self.update_username)
        self.change_name_btn.pack(side="right")

        self.peers_label = ctk.CTkLabel(self.sidebar_frame, text="Active Peers:", anchor="w")
        self.peers_label.grid(row=2, column=0, padx=20, pady=(10, 0))

        self.peers_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, width=180, label_text="Peers")
        self.peers_scroll.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")

        self.lock_btn = ctk.CTkButton(self.sidebar_frame, text="Lock App", fg_color="#e74c3c", hover_color="#c0392b", command=self.lock_app)
        self.lock_btn.grid(row=4, column=0, padx=20, pady=5)

        self.settings_btn = ctk.CTkButton(self.sidebar_frame, text="Settings", command=self.open_settings)
        self.settings_btn.grid(row=5, column=0, padx=20, pady=5)

        self.add_peer_btn = ctk.CTkButton(self.sidebar_frame, text="Info / Connect IP", command=self.add_manual_peer)
        self.add_peer_btn.grid(row=6, column=0, padx=20, pady=(0, 20))

        self.sidebar_frame.grid_rowconfigure(3, weight=1)

    def focus_search(self, event=None):
        self.tabview.set("Global Chat")
        self.search_entry.focus_set()

    def create_main_area(self):
        self.tabview = ctk.CTkTabview(self, command=self.on_tab_change)
        self.tabview.grid(row=0, column=1, padx=20, pady=10, sticky="nsew")

        self.chat_tab = self.tabview.add("Global Chat")
        self.files_tab = self.tabview.add("Files")
        self.security_tab = self.tabview.add("Security")
        self.audit_tab = self.tabview.add("Audit Logs")

        # -- Chat Tab --
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(0, weight=1)

        self.chat_display = ctk.CTkTextbox(self.chat_tab, state="disabled")
        self.chat_display.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.chat_display.tag_config("search_info", foreground="#3B8ED0")
        self.chat_display.tag_config("timestamp", foreground="#888888")
        self.chat_display.tag_config("sender", foreground="#3B8ED0", font=ctk.CTkFont(weight="bold"))

        self.input_frame = ctk.CTkFrame(self.chat_tab, height=50)
        self.input_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.msg_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Type message... (Enter to send)")
        self.msg_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.msg_entry.bind("<Return>", self.send_message)

        # -- TTL Selector --
        self.ttl_var = ctk.StringVar(value="Off")
        ctk.CTkLabel(self.input_frame, text="Burn:").grid(row=0, column=1, padx=(10, 0))
        self.ttl_menu = ctk.CTkOptionMenu(self.input_frame, values=["Off", "1m", "10m", "1h", "1d"], variable=self.ttl_var, width=80)
        self.ttl_menu.grid(row=0, column=2, padx=5, pady=10)

        self.send_btn = ctk.CTkButton(self.input_frame, text="Send", width=80, command=self.send_message)
        self.send_btn.grid(row=0, column=3, padx=10, pady=10)

        # -- Search Bar --
        self.search_frame = ctk.CTkFrame(self.chat_tab)
        self.search_frame.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.search_frame.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Search messages... (Ctrl+F)")
        self.search_entry.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self.load_chat_history())
        self.search_entry.bind("<KeyRelease>", self.on_search_key)
        self.search_entry.bind("<Escape>", lambda e: self.clear_search() or "break")

        self.search_btn = ctk.CTkButton(self.search_frame, text="Search", width=80, command=self.load_chat_history)
        self.search_btn.grid(row=0, column=1, padx=5, pady=5)

        self.clear_search_btn = ctk.CTkButton(self.search_frame, text="Clear", width=60, fg_color="gray", command=self.clear_search)
        self.clear_search_btn.grid(row=0, column=2, padx=5, pady=5)

        # Context Menu for Message Actions
        self.context_menu = Menu(self, tearoff=0)
        self.context_menu.add_command(label="Copy", command=self.copy_message)
        self.context_menu.add_command(label="Edit (Last Sent)", command=self.edit_last_message)
        self.context_menu.add_command(label="Delete (Last Sent)", command=self.delete_last_message)

        self.chat_display.bind("<Button-3>", self.show_context_menu)

        # -- Files Tab --
        self.files_tab.grid_columnconfigure(0, weight=1)
        self.files_tab.grid_rowconfigure(2, weight=1)

        self.file_controls = ctk.CTkFrame(self.files_tab)
        self.file_controls.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.share_btn = ctk.CTkButton(self.file_controls, text="Share File", command=self.share_file)
        self.share_btn.pack(side="left", padx=5)

        self.share_folder_btn = ctk.CTkButton(self.file_controls, text="Share Folder", command=self.share_folder)
        self.share_folder_btn.pack(side="left", padx=5)

        # File TTL
        self.file_ttl_var = ctk.StringVar(value="Off")
        self.file_ttl_dropdown = ctk.CTkOptionMenu(self.file_controls, values=["Off", "1m", "10m", "1h", "1d"], variable=self.file_ttl_var, width=80)
        self.file_ttl_dropdown.pack(side="left", padx=5)
        ctk.CTkLabel(self.file_controls, text="Burn:").pack(side="left", padx=(0, 5))

        self.my_files_btn = ctk.CTkButton(self.file_controls, text="My Shared Files", command=self.show_my_files)
        self.my_files_btn.pack(side="left", padx=5)

        self.download_btn = ctk.CTkButton(self.file_controls, text="Download Selected", command=self.download_selected, fg_color="green", state="disabled")
        self.download_btn.pack(side="right", padx=5)

        self.file_source_frame = ctk.CTkFrame(self.files_tab, height=40)
        self.file_source_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        self.source_label = ctk.CTkLabel(self.file_source_frame, text="Viewing: Local Shared Files")
        self.source_label.pack(side="left", padx=10)

        self.refresh_files_btn = ctk.CTkButton(self.file_source_frame, text="Refresh", width=80, command=self.refresh_files_view)
        self.refresh_files_btn.pack(side="right", padx=5)

        self.select_all_btn = ctk.CTkButton(self.file_source_frame, text="Select All", width=80, command=self.select_all_files, state="disabled")
        self.select_all_btn.pack(side="right", padx=5)

        self.files_scroll = ctk.CTkScrollableFrame(self.files_tab, label_text="Files")
        self.files_scroll.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")

        # -- Progress UI --
        self.progress_frame = ctk.CTkFrame(self.files_tab)
        self.progress_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_overall_lbl = ctk.CTkLabel(self.progress_frame, text="Overall Progress:", font=("Arial", 11))
        self.progress_overall_lbl.grid(row=0, column=0, padx=5, sticky="w")
        self.overall_progress = ctk.CTkProgressBar(self.progress_frame)
        self.overall_progress.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")
        self.overall_progress.set(0)

        self.progress_file_lbl = ctk.CTkLabel(self.progress_frame, text="Current File: Idle", font=("Arial", 11))
        self.progress_file_lbl.grid(row=2, column=0, padx=5, sticky="w")
        self.file_progress = ctk.CTkProgressBar(self.progress_frame)
        self.file_progress.grid(row=3, column=0, padx=5, pady=(0, 5), sticky="ew")
        self.file_progress.set(0)

        self.file_checkboxes = [] # (checkbox_widget, file_data)

        # -- Audit Tab --
        self.audit_tab.grid_columnconfigure(0, weight=1)
        self.audit_tab.grid_rowconfigure(0, weight=1)

        self.audit_display = ctk.CTkTextbox(self.audit_tab, state="disabled")
        self.audit_display.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.audit_display.tag_config("alert", foreground="#e74c3c")
        self.audit_display.tag_config("warning", foreground="#e67e22")
        self.audit_display.tag_config("info", foreground="#2ecc71")
        self.audit_display.tag_config("center", justify='center')

        self.audit_controls = ctk.CTkFrame(self.audit_tab)
        self.audit_controls.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.refresh_audit_btn = ctk.CTkButton(self.audit_controls, text="Refresh Logs", command=self.refresh_audit_view)
        self.refresh_audit_btn.pack(side="left", padx=10, pady=5)

        self.export_audit_btn = ctk.CTkButton(self.audit_controls, text="Export Logs (SOC 2)", command=self.export_audit_logs, fg_color="#34495e")
        self.export_audit_btn.pack(side="right", padx=10, pady=5)

        # -- Security Tab --
        self.security_tab.grid_columnconfigure(0, weight=1)
        self.security_tab.grid_rowconfigure(1, weight=1)

        # Stats Header
        self.sec_stats_frame = ctk.CTkFrame(self.security_tab)
        self.sec_stats_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.sec_stats_frame.grid_columnconfigure((0, 1), weight=1)

        self.threat_label = ctk.CTkLabel(self.sec_stats_frame, text="Total Threats Intercepted: 0", font=("Arial", 14, "bold"))
        self.threat_label.grid(row=0, column=0, pady=10)

        self.block_label = ctk.CTkLabel(self.sec_stats_frame, text="Active IP Blocks: 0", font=("Arial", 14, "bold"))
        self.block_label.grid(row=0, column=1, pady=10)

        # Blocked Peers List
        self.blocked_scroll = ctk.CTkScrollableFrame(self.security_tab, label_text="Currently Blocked Peers")
        self.blocked_scroll.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    def refresh_audit_view(self):
        """Refreshes audit logs with non-blocking success feedback."""
        self.load_audit_logs()
        self.refresh_audit_btn.configure(text="Refreshed", fg_color="#2ecc71")
        def reset():
            if self.refresh_audit_btn.winfo_exists():
                self.refresh_audit_btn.configure(text="Refresh Logs", fg_color=("#3B8ED0", "#1F6AA5"))
        self.after(2000, reset)

    def export_audit_logs(self):
        logs = self.db.get_audit_logs(1000)
        try:
            with open("audit_export.txt", "w", encoding="utf-8") as f:
                f.write("LAN Messenger Security Audit Log Export\n")
                f.write("======================================\n")
                for log in logs:
                    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log[3]))
                    ip = log[4] or "N/A"
                    f.write(f"[{ts}] [{ip}] {log[1]}: {log[2]}\n")
            messagebox.showinfo("Export Successful", "Audit logs exported to audit_export.txt")
            self.logger.log("AUDIT_EXPORT", "Audit logs exported to file.")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export logs: {e}")

    def load_audit_logs(self):
        if not self.winfo_exists() or self.tabview.get() != "Audit Logs":
            return
        logs = self.db.get_audit_logs(200)
        self.audit_display.configure(state="normal")
        self.audit_display.delete("1.0", "end")

        if not logs:
            self.audit_display.insert("end", "\n\nNo audit logs found.", "center")
        else:
            # Event type mapping to semantic tags
            tag_map = {
                "SECURITY_ALERT": "alert",
                "FILE_INTEGRITY_FAILURE": "alert",
                "AUTH_FAILURE": "warning",
                "FILE_TRANSFER": "info",
                "FILE_INTEGRITY_SUCCESS": "info",
                "CONNECTION": "info",
                "APP_START": "info",
                "DATA_RETENTION": "info",
                "SETTINGS_CHANGE": "info",
                "TOFU_TRUST": "info",
                "SECURITY_INFO": "info"
            }

            for log in logs:
                # log: (id, event_type, details, timestamp)
                event_type = log[1]
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log[3]))
                tag = tag_map.get(event_type, "")
                self.audit_display.insert("end", f"[{ts}] {event_type}: {log[2]}\n", tag)

        self.audit_display.configure(state="disabled")
        self.audit_display.see("1.0")

        # Provide success feedback
        original_fg = self.refresh_audit_btn.cget("fg_color")
        self.refresh_audit_btn.configure(text="Refreshed", fg_color="#2ecc71")
        self.after(1500, lambda: self.refresh_audit_btn.configure(text="Refresh Logs", fg_color=original_fg) if self.refresh_audit_btn.winfo_exists() else None)

    def update_username(self, event=None):
        new_name = self.username_entry.get().strip()
        if new_name and new_name != self.username:
            old_name = self.username
            self.username = new_name
            if hasattr(self, 'discovery'):
                self.discovery.username = new_name
            self.settings["username"] = new_name
            save_settings(self.settings)
            self.logger.log("SETTINGS_CHANGE", f"Username changed from {old_name} to {new_name}")

            # Notify all connected peers of name change
            for ip in self.peers:
                self.executor.submit(self.network.send_hello, ip, self.username)

            # Non-blocking success feedback
            self.change_name_btn.configure(text="Saved", fg_color="#2ecc71")
            self.after(2000, lambda: self.change_name_btn.configure(text="Set", fg_color=("#3B8ED0", "#1F6AA5")))


    def show_trust_warning(self, ip):
        if messagebox.askyesno("Security Warning", f"Fingerprint mismatch detected for {ip}!\nThis could be a Man-in-the-Middle attack or the user reinstalled the app.\n\nDo you want to trust this new identity?"):
            self.db.update_peer_trust(ip, 'trusted')
            self.peer_trust[ip] = 'trusted'
            self.refresh_peers()

    def open_peer_security(self, ip, name):
        PeerSecurityDialog(self, self.db, ip, name, self.refresh_peers)

    def refresh_peers(self):
        # Batch fetch peer data from DB to reduce lock contention and roundtrips
        peer_ips = list(self.peers.keys())
        trust_levels = self.db.get_peer_trust_levels(peer_ips)
        all_perms = self.db.get_peers_permissions(peer_ips)

        # Update internal state from batch results
        for ip in self.peers:
            self.peer_trust[ip] = trust_levels.get(ip, 'untrusted')

        # Also include blocked status in snapshot for UI refreshes
        all_perms = self.db.get_peers_permissions(list(self.peers.keys()))

        # Prevent unnecessary UI rebuilds using snapshot comparison
        current_snapshot = json.dumps({"peers": self.peers, "trust": self.peer_trust, "perms": all_perms}, sort_keys=True)
        if current_snapshot == self._last_peers_snapshot:
            self.after(2000, self.refresh_peers)
            return

        self._last_peers_snapshot = current_snapshot

        for widget in self.peers_scroll.winfo_children():
            widget.destroy()

        if not self.peers:
            lbl = ctk.CTkLabel(self.peers_scroll, text="No peers found yet...", font=("Arial", 11, "italic"), text_color="gray")
            lbl.pack(pady=20)

        for ip, name in self.peers.items():
            perms = all_perms.get(ip, {})
            is_blocked = perms.get('is_blocked', False)
            is_verified = perms.get('is_verified', False)

            row = ctk.CTkFrame(self.peers_scroll, fg_color="#333333" if is_blocked else None)
            row.pack(fill="x", pady=2)

            label_color = "gray" if is_blocked else None
            label_text = f"{name}\n{ip}"
            if is_blocked:
                label_text += " (BLOCKED)"

            lbl = ctk.CTkLabel(row, text=label_text, font=("Arial", 10), text_color=label_color)
            lbl.pack(side="left", padx=5)

            # Verification badge
            if is_verified:
                v_lbl = ctk.CTkLabel(row, text="✓", text_color="#2ecc71", font=("Arial", 12, "bold"), width=15)
                v_lbl.pack(side="left", padx=2)

            # Security button
            btn_sec = ctk.CTkButton(row, text="Sec", width=35, height=20, fg_color="#555555",
                              command=lambda i=ip, n=name: PeerSecurityDialog(self, self.db, i, n, self.refresh_peers))
            btn_sec.pack(side="right", padx=2)

            btn_browse = ctk.CTkButton(row, text="Browse", width=60, height=20,
                              command=lambda i=ip, n=name: self.browse_peer_files(i, n),
                              state="disabled" if is_blocked else "normal")
            btn_browse.pack(side="right", padx=5)

            btn_chat = ctk.CTkButton(row, text="Chat", width=60, height=20,
                              command=lambda i=ip, n=name: self.open_private_chat(i, n),
                              state="disabled" if is_blocked else "normal")
            btn_chat.pack(side="right", padx=2)

            # Trust indicator
            trust = self.peer_trust.get(ip, 'untrusted')
            color = "gray"
            if trust == 'trusted': color = "green"
            elif trust == 'mismatch': color = "red"

            trust_lbl = ctk.CTkLabel(row, text="●", text_color=color, width=10)
            trust_lbl.pack(side="right", padx=5)
            if trust == 'mismatch':
                trust_lbl.bind("<Button-1>", lambda e, i=ip: self.show_trust_warning(i))
        self.after(2000, self.refresh_peers)

    def add_manual_peer(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Connect to IP")
        dialog.geometry("300x280")
        dialog.transient(self)
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        ip_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        ip_frame.pack(pady=10)

        my_ip = socket.gethostbyname(socket.gethostname())
        ctk.CTkLabel(ip_frame, text="My IP: " + my_ip).pack(side="left", padx=5)

        def copy_ip():
            self.clipboard_clear()
            self.clipboard_append(my_ip)
            copy_btn.configure(text="Copied!", fg_color="#2ecc71")

            def reset():
                if copy_btn.winfo_exists():
                    copy_btn.configure(text="Copy", fg_color=("#3B8ED0", "#1F6AA5"))
            self.after(2000, reset)

        copy_btn = ctk.CTkButton(ip_frame, text="Copy", width=60, height=20, command=copy_ip)
        copy_btn.pack(side="left", padx=5)

        ctk.CTkLabel(dialog, text="Enter Peer IP:").pack(pady=5)
        entry = ctk.CTkEntry(dialog, placeholder_text="192.168.x.x")
        entry.pack(pady=5)

        def connect(event=None):
            ip = entry.get().strip()
            if ip:
                connect_btn.configure(text="Connecting...", state="disabled")
                threading.Thread(target=self.try_manual_connect, args=(ip, dialog, connect_btn), daemon=True).start()

        entry.bind("<Return>", connect)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        connect_btn = ctk.CTkButton(dialog, text="Connect", command=connect)
        connect_btn.pack(pady=20)
        self.after(200, lambda: entry.focus_set() if entry.winfo_exists() else None)

    def try_manual_connect(self, ip, dialog, btn):
        success = self.network.send_hello(ip, self.username)
        def update_ui():
            if not btn.winfo_exists(): return
            if success:
                btn.configure(text="Handshake Sent!", fg_color="#2ecc71")
                self.after(2000, lambda: dialog.destroy() if dialog.winfo_exists() else None)
            else:
                btn.configure(text="Failed", fg_color="#e74c3c", state="normal")
                self.after(2000, lambda: btn.configure(text="Connect", fg_color=("#3B8ED0", "#1F6AA5")) if btn.winfo_exists() else None)
        self.after(0, update_ui)

    def refresh_security_dashboard(self):
        if not self.winfo_exists() or self.tabview.get() != "Security":
            return

        # Update Stats
        logs = self.db.get_audit_logs(1000)
        suspicious = [l for l in logs if l[1] in ('AUTH_FAILURE', 'SECURITY_ALERT', 'UNAUTHORIZED_ACCESS', 'PROTOCOL_VIOLATION', 'IPS_AUTO_BLOCK')]
        self.threat_label.configure(text=f"Total Threats Intercepted: {len(suspicious)}")

        blocked = self.db.get_blocked_peers()
        self.block_label.configure(text=f"Active IP Blocks: {len(blocked)}")

        # Update List
        for widget in self.blocked_scroll.winfo_children():
            widget.destroy()

        if not blocked:
             lbl = ctk.CTkLabel(self.blocked_scroll, text="No active IP blocks.", font=("Arial", 12, "italic"), text_color="gray")
             lbl.pack(pady=40)
        else:
            for ip, name in blocked:
                row = ctk.CTkFrame(self.blocked_scroll)
                row.pack(fill="x", pady=2, padx=5)

                ctk.CTkLabel(row, text=f"{name} ({ip})").pack(side="left", padx=10)
                ctk.CTkButton(row, text="Unblock", width=80, height=24, fg_color="#27ae60", hover_color="#2ecc71",
                               command=lambda i=ip: self.unblock_ip_action(i)).pack(side="right", padx=10, pady=5)

    def unblock_ip_action(self, ip):
        self.db.unblock_peer(ip)
        self.logger.log("SECURITY_POLICY_CHANGE", f"Manually unblocked IP: {ip}")
        self.refresh_security_dashboard()
        self.refresh_peers()

    def on_tab_change(self):
        tab = self.tabview.get()
        if tab == "Global Chat":
            self.msg_entry.focus_set()
            self.load_chat_history(debounce=False)
        elif tab == "Audit Logs":
            self.load_audit_logs()
        elif tab == "Security":
            self.refresh_security_dashboard()
        elif tab.startswith("Chat: "):
            peer_ip = self.private_chat_tabs.get(tab)
            if peer_ip:
                self.current_private_peer = peer_ip
                if peer_ip in self.private_entries:
                    self.private_entries[peer_ip].focus_set()
                self.load_private_chat(peer_ip, debounce=False)

    def focus_search(self, event=None):
        """Switches to Global Chat and focuses the search entry (Ctrl+F)."""
        self.tabview.set("Global Chat")
        self.search_entry.focus_set()

    def on_search_key(self, event):
        # Throttle live search
        if self._chat_history_after_id:
            self.after_cancel(self._chat_history_after_id)
        self._chat_history_after_id = self.after(300, self.load_chat_history)

    def clear_search(self):
        if self._chat_history_after_id:
            try:
                self.after_cancel(self._chat_history_after_id)
            except Exception:
                pass
            self._chat_history_after_id = None
        self.search_entry.delete(0, "end")
        self.load_chat_history(debounce=False)
        self.search_entry.focus_set()

    def focus_search(self, event=None):
        self.tabview.set("Global Chat")
        self.search_entry.focus_set()

    def load_chat_history(self, debounce=True):
        """Debounced global chat refresh with lazy loading."""
        if not self.winfo_exists():
            return

        if debounce:
            if self._chat_history_after_id:
                try:
                    self.after_cancel(self._chat_history_after_id)
                except Exception:
                    pass
            self._chat_history_after_id = self.after(100, lambda: self.load_chat_history(debounce=False))
            return

        self._chat_history_after_id = None

        # Lazy loading: only update if Global Chat is visible
        if self.tabview.get() != "Global Chat":
            return

        query = self.search_entry.get().strip().lower()
        self._last_search_query = query

        messages = self.db.get_messages(200)
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")

        found_messages = []
        for msg in messages:
            if query and query not in msg[2].lower() and query not in msg[1].lower():
                continue
            found_messages.append(msg)

        if query:
            if found_messages:
                self.chat_display.insert("end", f"--- Found {len(found_messages)} results for '{query}' ---\n\n", "search_info")
            else:
                self.chat_display.insert("end", f"--- No results found for '{query}' ---\n", "search_info")

        for msg in found_messages:
            sender = msg[1]
            content = msg[2]
            ts = time.strftime('%H:%M', time.localtime(msg[3]))
            self.chat_display.insert("end", f"[{ts}] ", "timestamp")
            self.chat_display.insert("end", f"{sender}: ", "sender")
            self.chat_display.insert("end", f"{content}\n")

        if not found_messages and query:
            self.chat_display.insert("end", f"\n\nNo messages found matching '{query}'", "center")
        elif not messages:
            self.chat_display.insert("end", "\n\nNo messages yet. Say hello!", "center")

        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def _get_ttl_seconds(self, var=None):
        val = var.get() if var else self.ttl_var.get()
        if val == "1m": return 60
        if val == "10m": return 600
        if val == "1h": return 3600
        if val == "1d": return 86400
        return None

    def send_message(self, event=None):
        msg = self.msg_entry.get()
        if not msg: return
        ttl = self._get_ttl_seconds()

        # If we are in a private chat tab, send private message
        current_tab = self.tabview.get()
        if current_tab.startswith("Chat: "):
            peer_ip = self.current_private_peer
            if peer_ip:
                msg_id = self.db.add_message(self.username, msg, recipient=peer_ip, ttl=ttl)
                threading.Thread(target=self.network.send_message, args=(peer_ip, self.username, msg, msg_id, True, ttl)).start()
                self.msg_entry.delete(0, "end")
                self.load_private_chat(peer_ip)
                return

        # Otherwise send global message
        msg_id = self.db.add_message(self.username, msg, ttl=ttl)
        for ip in self.peers:
            self.executor.submit(self.network.send_message, ip, self.username, msg, msg_id, False, ttl)

        self.msg_entry.delete(0, "end")
        self.load_chat_history()

    def open_security_dialog(self, ip, name):
        def on_update():
            self._last_peers_snapshot = ""
            self.refresh_peers()
        PeerSecurityDialog(self, self.db, ip, name, on_update)

    def open_private_chat(self, ip, name):
        # Find if we already have a tab for this IP
        tab_name = None
        for tname, tip in self.private_chat_tabs.items():
            if tip == ip:
                tab_name = tname
                break

        if not tab_name:
            tab_name = f"Chat: {name}"
            # Handle name collisions
            if tab_name in self.tabview._tab_dict.keys():
                tab_name = f"Chat: {name} ({ip})"

            self.tabview.add(tab_name)
            # Create UI for the new tab
            tab_frame = self.tabview.tab(tab_name)
            tab_frame.grid_columnconfigure(0, weight=1)
            tab_frame.grid_rowconfigure(0, weight=1)

            display = ctk.CTkTextbox(tab_frame, state="disabled")
            display.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

            input_frame = ctk.CTkFrame(tab_frame, height=50)
            input_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
            input_frame.grid_columnconfigure(0, weight=1)

            entry = ctk.CTkEntry(input_frame, placeholder_text=f"Message {name}...")
            entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

            # Private TTL
            priv_ttl_var = ctk.StringVar(value=self.ttl_var.get())
            ctk.CTkLabel(input_frame, text="Burn:").grid(row=0, column=1, padx=(10, 0))
            priv_ttl_dropdown = ctk.CTkOptionMenu(input_frame, values=["Off", "1m", "10m", "1h", "1d"], variable=priv_ttl_var, width=80)
            priv_ttl_dropdown.grid(row=0, column=2, padx=5, pady=10)

            def send_priv(e=None, i=ip, ent=entry, tvar=priv_ttl_var):
                m = ent.get()
                if not m: return

                # Get TTL
                ttl_sec = self._get_ttl_seconds(var=tvar)

                mid = self.db.add_message(self.username, m, recipient=i, ttl=ttl_sec)
                threading.Thread(target=self.network.send_message, args=(i, self.username, m, mid, True, ttl_sec)).start()
                ent.delete(0, "end")
                self.load_private_chat(i)

            entry.bind("<Return>", send_priv)
            btn = ctk.CTkButton(input_frame, text="Send", width=80, command=send_priv)
            btn.grid(row=0, column=3, padx=10, pady=10)

            self.private_chats[ip] = display
            self.private_entries[ip] = entry
            self.private_chat_tabs[tab_name] = ip

        self.current_private_peer = ip
        self.tabview.set(tab_name)
        self.load_private_chat(ip)

    def load_private_chat(self, peer_ip, debounce=True):
        """Debounced private chat refresh with batched insertions and lazy loading."""
        if not self.winfo_exists():
            return

        # Lazy loading: only update if this peer's tab is currently visible
        current_tab = self.tabview.get()
        if self.private_chat_tabs.get(current_tab) != peer_ip:
            return

        if debounce:
            if peer_ip in self._private_chat_after_ids:
                try:
                    self.after_cancel(self._private_chat_after_ids[peer_ip])
                except Exception:
                    pass
            self._private_chat_after_ids[peer_ip] = self.after(100, lambda: self.load_private_chat(peer_ip, debounce=False))
            return

        self._private_chat_after_ids.pop(peer_ip, None)
        messages = self.db.get_messages(100, peer_ip=peer_ip)
        display = self.private_chats[peer_ip]
        display.configure(state="normal")
        display.delete("1.0", "end")

        lines = []
        for msg in messages:
            sender = msg[1]
            content = msg[2]
            ts = time.strftime('%H:%M', time.localtime(msg[3]))
            lines.append(f"[{ts}] {sender}: {content}")

        if lines:
            display.insert("end", "\n".join(lines) + "\n")

        display.configure(state="disabled")
        display.see("end")

    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def copy_message(self):
        try:
            text = self.chat_display.selection_get()
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def edit_last_message(self):
        msgs = self.db.get_messages(100)
        my_msgs = [m for m in msgs if m[1] == self.username]
        if not my_msgs:
            messagebox.showinfo("Info", "No messages to edit.")
            return
        last_msg = my_msgs[0]
        msg_id, content = last_msg[0], last_msg[2]

        dialog = ctk.CTkInputDialog(text="Edit your last message:", title="Edit Message")
        new_content = dialog.get_input()
        if new_content:
            self.db.edit_message(msg_id, new_content)
            for ip in self.peers:
                self.executor.submit(self.network.send_edit, ip, msg_id, new_content)
            self.load_chat_history()

    def delete_last_message(self):
        msgs = self.db.get_messages(100)
        my_msgs = [m for m in msgs if m[1] == self.username]
        if not my_msgs: return
        last_msg = my_msgs[0]
        msg_id, content = last_msg[0], last_msg[2]
        if messagebox.askyesno("Delete", "Delete this message?"):
            self.db.delete_message(msg_id)
            for ip in self.peers:
                self.executor.submit(self.network.send_delete, ip, msg_id)
            self.load_chat_history()

    def share_file(self):
        path = filedialog.askopenfilename()
        if path:
            filename = os.path.basename(path)
            size = os.path.getsize(path)
            checksum = FileTransferManager.calculate_sha256(path)
            local_ip = socket.gethostbyname(socket.gethostname())
            ttl = self._get_ttl_seconds(var=self.file_ttl_var)
            self.db.add_file(filename, path, size, local_ip, is_folder=False, checksum=checksum, ttl=ttl)
            self.current_file_view_source = "Local"
            self.source_label.configure(text="Viewing: Local Shared Files")
            self.refresh_files_view()

            # Visual feedback
            self.share_btn.configure(text="Shared!", fg_color="#2ecc71")
            def reset_share_btn():
                if self.share_btn.winfo_exists():
                    self.share_btn.configure(text="Share File", fg_color=("#3B8ED0", "#1F6AA5"))
            self.after(2000, reset_share_btn)

    def get_folder_size(self, path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    def share_folder(self):
        path = filedialog.askdirectory()
        if path:
            dirname = os.path.basename(path)
            size = self.get_folder_size(path)
            local_ip = socket.gethostbyname(socket.gethostname())
            ttl = self._get_ttl_seconds(var=self.file_ttl_var)
            self.db.add_file(dirname, path, size, local_ip, is_folder=True, ttl=ttl)
            self.current_file_view_source = "Local"
            self.source_label.configure(text="Viewing: Local Shared Files")
            self.refresh_files_view()

            # Visual feedback
            self.share_folder_btn.configure(text="Shared!", fg_color="#2ecc71")
            def reset_share_folder_btn():
                if self.share_folder_btn.winfo_exists():
                    self.share_folder_btn.configure(text="Share Folder", fg_color=("#3B8ED0", "#1F6AA5"))
            self.after(2000, reset_share_folder_btn)

    def show_my_files(self):
        self.current_file_view_source = "Local"
        self.source_label.configure(text="Viewing: Local Shared Files")
        self.select_all_btn.configure(state="disabled")
        self.refresh_files_view()

    def select_all_files(self):
        for chk_var, _ in self.file_checkboxes:
            chk_var.set(1)

    def browse_peer_files(self, ip, name):
        self.current_file_view_source = ip
        self.source_label.configure(text=f"Viewing: {name}'s Files")
        self.select_all_btn.configure(state="normal")
        self.tabview.set("Files")
        self.refresh_files_view()

    def refresh_files_view(self):
        # Non-blocking success feedback
        self.refresh_files_btn.configure(text="Refreshed", fg_color="#2ecc71")
        def reset():
            if self.refresh_files_btn.winfo_exists():
                self.refresh_files_btn.configure(text="Refresh", fg_color=("#3B8ED0", "#1F6AA5"))
        self.after(1500, reset)

        self.file_checkboxes = []
        for w in self.files_scroll.winfo_children():
            w.destroy()
        if self.current_file_view_source == "Local":
            self.download_btn.configure(state="disabled")
            self.select_all_btn.configure(state="disabled")
            files = self.db.get_files()
            file_data = []
            for f in files:
                # f can be dict (from peer) or tuple (from local db)
                if isinstance(f, tuple):
                     file_data.append({
                        'filename': f[1],
                        'path': f[2],
                        'size': f[3],
                        'is_folder': f[5],
                        'owner': "Me",
                        'checksum': f[6] if len(f) > 6 else None
                    })
                else:
                     file_data.append(f)
            self.render_file_list(file_data)
        else:
            self.download_btn.configure(state="normal")
            threading.Thread(target=self.fetch_peer_files, args=(self.current_file_view_source,)).start()

    def fetch_peer_files(self, ip):
        file_list = self.file_manager.get_shared_files(ip)
        if not file_list and self.current_file_view_source == ip:
             self.after(0, lambda: messagebox.showerror("Error", f"Could not fetch file list from {ip}"))

        if self.current_file_view_source == ip:
            self.after(0, lambda: self.render_file_list(file_list))

    def render_file_list(self, files):
        for w in self.files_scroll.winfo_children():
            w.destroy()
        self.file_checkboxes = []

        if not files:
            msg = "No files shared yet..." if self.current_file_view_source == "Local" else "No files found on this peer."
            lbl = ctk.CTkLabel(self.files_scroll, text=msg, font=("Arial", 12, "italic"), text_color="gray")
            lbl.pack(pady=40)

        now = time.time()
        for f in files:
            # Normalize to dict
            if isinstance(f, tuple):
                f = {
                    'id': f[0],
                    'filename': f[1],
                    'path': f[2],
                    'size': f[3],
                    'owner': f[4],
                    'is_folder': f[5],
                    'checksum': f[6],
                    'expires_at': f[7] if len(f) > 7 else None
                }

            row = ctk.CTkFrame(self.files_scroll)
            row.pack(fill="x", pady=2)
            chk_var = ctk.IntVar()

            # Label with expiration info
            label_text = f"[{'DIR' if f.get('is_folder') else 'FILE'}] {f['filename']}"
            expires_at = f.get('expires_at')
            if expires_at:
                remaining = expires_at - now
                if remaining > 0:
                    if remaining > 3600:
                        time_str = f"{remaining/3600:.1f}h"
                    elif remaining > 60:
                        time_str = f"{remaining/60:.1f}m"
                    else:
                        time_str = f"{int(remaining)}s"
                    label_text += f" (Exp: {time_str})"
                else:
                    label_text += " (Expired)"

            chk = ctk.CTkCheckBox(row, text=label_text, variable=chk_var)
            chk.pack(side="left", padx=5)

            size_mb = f['size'] / (1024*1024)
            info = ctk.CTkLabel(row, text=f"{size_mb:.2f} MB")
            info.pack(side="right", padx=10)
            self.file_checkboxes.append((chk_var, f))

    def download_selected(self):
        if self.current_file_view_source == "Local": return
        target_ip = self.current_file_view_source

        items = [(var, f) for var, f in self.file_checkboxes if var.get() == 1]
        if not items: return

        def worker():
            self.after(0, lambda: self.overall_progress.set(0))
            self.after(0, lambda: self.file_progress.set(0))

            for var, f in items:
                if f.get('is_folder'):
                    self.file_manager.download_folder(target_ip, f['path'], progress_callback=self._download_progress)
                else:
                    self.file_manager.download_file(target_ip, f['path'], expected_checksum=f.get('checksum'))
                    self.after(0, lambda p=f['filename']: self.progress_file_lbl.configure(text=f"Downloaded {p}"))

            def reset():
                if self.download_btn.winfo_exists():
                    self.download_btn.configure(text="Finished!", fg_color="#2ecc71")
                    self.after(3000, lambda: self.download_btn.configure(text="Download Selected", fg_color="green") if self.download_btn.winfo_exists() else None)
            self.after(0, reset)
            self.after(0, lambda: self.progress_file_lbl.configure(text="Idle"))

        threading.Thread(target=worker, daemon=True).start()

    def _download_progress(self, rel_path, status, file_ratio, overall_ratio):
        def update():
            if status == "START":
                self.progress_file_lbl.configure(text=f"Downloading: {rel_path}")
                self.file_progress.set(0)
            elif status == "PROGRESS":
                self.file_progress.set(file_ratio)
            elif status in ("DONE", "ERROR"):
                self.file_progress.set(1.0 if status == "DONE" else 0)
                self.progress_file_lbl.configure(text=f"{'Finished' if status=='DONE' else 'Failed'}: {rel_path}")

            self.overall_progress.set(overall_ratio)

        if self.winfo_exists():
            self.after(0, update)

    def start_download(self, ip, path, is_folder):
        if is_folder:
            self.file_manager.download_folder(ip, path)
        else:
            self.file_manager.download_file(ip, path)

    def open_peer_security(self, ip, name):
        PeerSecurityDialog(self, self.db, ip, name, self.logger)

    def check_lock(self):
        if self.db.is_locked():
            if not self.lock_screen:
                self.lock_screen = LockScreen(self, self.db, self.after_unlock)
        else:
            if self.lock_screen:
                self.lock_screen.destroy()
                self.lock_screen = None

    def after_unlock(self):
        self.lock_screen = None
        self.load_chat_history()
        self.refresh_peers()
        self._reset_lock_timer()

    def lock_app(self):
        if not self.db.is_locked():
            self.db.lock_db()
            self.logger.log("APP_LOCKED", "Application manually locked.")
            self.check_lock()

    def _reset_lock_timer(self, event=None):
        if self._lock_timer_id:
            self.after_cancel(self._lock_timer_id)
        if not self.db.is_locked():
            self._lock_timer_id = self.after(self._inactivity_timeout, self._on_inactivity)

    def _on_inactivity(self):
        if not self.db.is_locked():
            self.db.lock_db()
            self.logger.log("APP_LOCKED", "Application locked due to inactivity.")
            self.check_lock()

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("500x550")
        dialog.transient(self)

        # Tabview for settings
        st_tabs = ctk.CTkTabview(dialog)
        st_tabs.pack(fill="both", expand=True, padx=10, pady=10)

        gen_tab = st_tabs.add("General")
        sec_tab = st_tabs.add("Security")

        # -- General Tab --
        ctk.CTkLabel(gen_tab, text="Chat Port (TCP):").pack(pady=(10, 0))
        entry_chat = ctk.CTkEntry(gen_tab)
        entry_chat.insert(0, str(self.settings["tcp_chat_port"]))
        entry_chat.pack(pady=5)

        ctk.CTkLabel(gen_tab, text="File Port (TCP):").pack(pady=(10, 0))
        entry_file = ctk.CTkEntry(gen_tab)
        entry_file.insert(0, str(self.settings["tcp_file_port"]))
        entry_file.pack(pady=5)

        # -- Security Tab --
        ctk.CTkLabel(sec_tab, text="Multi-Factor Authentication (MFA)", font=("Arial", 14, "bold")).pack(pady=10)

        mfa_status = "Enabled" if self.db.get_config("mfa_enabled") == "1" else "Disabled"
        status_lbl = ctk.CTkLabel(sec_tab, text=f"Status: {mfa_status}")
        status_lbl.pack(pady=5)

        def toggle_mfa():
            if self.db.get_config("mfa_enabled") == "1":
                # Disable MFA (needs confirmation/password)
                if messagebox.askyesno("Disable MFA", "Are you sure you want to disable Multi-Factor Authentication?"):
                    # Request master password for critical action
                    pw_dialog = PasswordDialog(dialog, title="Verify Master Password")
                    if pw_dialog.result:
                        # Try to unlock with this password to verify
                        temp_db_mgr = self.db.cipher # Just use existing cipher state
                        # Since db is already unlocked, we can just check if password is correct by trying to re-unlock
                        # or better, check against the master password provided at startup.
                        if pw_dialog.result == self._master_password:
                            self.db.set_config("mfa_enabled", "0")
                            self.db.set_config("mfa_secret", None)
                            self.logger.log("MFA_DISABLED", "TOTP Multi-Factor Authentication disabled.")
                            status_lbl.configure(text="Status: Disabled")
                            mfa_btn.configure(text="Enable MFA", fg_color=("#3B8ED0", "#1F6AA5"))
                            messagebox.showinfo("Success", "MFA has been disabled.")
                        else:
                            messagebox.showerror("Error", "Incorrect Master Password.")
            else:
                # Enable MFA
                MFASetupDialog(dialog, self.db, on_complete_cb=lambda: [
                    status_lbl.configure(text="Status: Enabled"),
                    mfa_btn.configure(text="Disable MFA", fg_color="#e74c3c")
                ])

        mfa_btn_text = "Disable MFA" if mfa_status == "Enabled" else "Enable MFA"
        mfa_btn_color = "#e74c3c" if mfa_status == "Enabled" else ("#3B8ED0", "#1F6AA5")
        mfa_btn = ctk.CTkButton(sec_tab, text=mfa_btn_text, fg_color=mfa_btn_color, command=toggle_mfa)
        mfa_btn.pack(pady=20)

        def save(event=None):
            try:
                self.settings["tcp_chat_port"] = int(entry_chat.get())
                self.settings["tcp_file_port"] = int(entry_file.get())
                self.settings["username"] = self.username
                save_settings(self.settings)
                save_btn.configure(text="Saved! Please Restart App", fg_color="#2ecc71")
                self.after(2000, dialog.destroy)
            except ValueError:
                messagebox.showerror("Error", "Ports must be numbers.")

        entry_chat.bind("<Return>", save)
        entry_file.bind("<Return>", save)
        save_btn = ctk.CTkButton(gen_tab, text="Save & Restart", command=save, fg_color="green")
        save_btn.pack(pady=20)
        self.after(200, lambda: entry_chat.focus_set())

    def on_closing(self):
        if hasattr(self, 'discovery'):
            self.discovery.stop()
        if hasattr(self, 'network'):
            self.network.close()
        if hasattr(self, 'file_manager'):
            self.file_manager.close()
        if hasattr(self, 'db'):
            self.db.close()
        self.executor.shutdown(wait=False)
        self.destroy()

if __name__ == "__main__":
    app = LANMessengerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
