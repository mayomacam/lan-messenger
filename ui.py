import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, Menu
import socket
import os
import threading
import time
import shutil
import json
import audit
from concurrent.futures import ThreadPoolExecutor
from db import Database
from network import NetworkManager, DiscoveryManager
from file_transfer import FileTransferManager
from config import load_settings, save_settings

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class LANMessengerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("LAN Messenger")
        self.geometry("1100x700")

        self._chat_history_after_id = None

        # Load Settings
        self.settings = load_settings()

        # State
        self.username = self.settings.get("username", "")

        # Prompt for username if not set
        if not self.username or self.username.startswith("User_"):
            self.prompt_username()

        self.db = Database()
        audit.init_logger(self.db)
        self.logger = audit.get_logger()
        self.logger.log("APP_START", f"Application started for user {self.username}")

        # Thread pool for non-blocking network calls
        self.executor = ThreadPoolExecutor(max_workers=5)

        # Init Networking with Configured Ports
        # Initialize managers with security configuration from settings
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

        # Periodic Updates
        self.after(2000, self.refresh_peers)
        self.load_chat_history()
        self.after(100, lambda: self.msg_entry.focus_set())

        # Start Message Reaper
        self.reaper_thread = threading.Thread(target=self.message_reaper_loop, daemon=True)
        self.reaper_thread.start()

    def message_reaper_loop(self):
        while True:
            try:
                # Reap messages
                msg_count = self.db.reap_expired_messages()
                if msg_count > 0:
                    self.logger.log("DATA_RETENTION", f"Automatically reaped {msg_count} expired messages.")
                    # Background loop triggers UI updates via thread-safe after(0, ...)
                    self.after(0, self.load_chat_history)
                    # Also reload private chat if open
                    if self.current_private_peer:
                        self.after(0, lambda p=self.current_private_peer: self.load_private_chat(p))

                # Reap files
                file_count = self.db.delete_expired_files()
                if file_count > 0:
                    self.logger.log("DATA_RETENTION", f"Automatically reaped {file_count} expired file shares.")
                    if self.current_file_view_source == "Local":
                        self.after(0, self.refresh_files_view)
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

            # Check if this is a NEW peer (not just a name update)
            is_new_peer = ip not in self.peers

            # Update peer (handles both new peer and name change)
            self.peers[ip] = name

            # Only send HELLO back if this was a new peer
            if is_new_peer:
                self.executor.submit(self.network.send_hello, ip, self.username)
        elif event_type == 'MSG':
             self.load_chat_history()
        elif event_type == 'MSG_PRIV':
             # args: (msg_id, sender, content, peer_ip)
             peer_ip = args[3]
             if peer_ip in self.private_chats:
                 self.load_private_chat(peer_ip)
             else:
                 sender_name = self.peers.get(peer_ip, args[1])
                 self.open_private_chat(peer_ip, sender_name)
        elif event_type in ['EDIT', 'DELETE']:
             self.load_chat_history()
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

        self.settings_btn = ctk.CTkButton(self.sidebar_frame, text="Settings", command=self.open_settings)
        self.settings_btn.grid(row=4, column=0, padx=20, pady=(20, 10))

        self.add_peer_btn = ctk.CTkButton(self.sidebar_frame, text="Info / Connect IP", command=self.add_manual_peer)
        self.add_peer_btn.grid(row=5, column=0, padx=20, pady=(0, 20))

        self.sidebar_frame.grid_rowconfigure(3, weight=1)

    def create_main_area(self):
        self.tabview = ctk.CTkTabview(self, command=self.on_tab_change)
        self.tabview.grid(row=0, column=1, padx=20, pady=10, sticky="nsew")

        self.chat_tab = self.tabview.add("Global Chat")
        self.files_tab = self.tabview.add("Files")
        self.audit_tab = self.tabview.add("Audit Logs")

        # -- Chat Tab --
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(0, weight=1)

        self.chat_display = ctk.CTkTextbox(self.chat_tab, state="disabled")
        self.chat_display.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.chat_display.tag_config("search_info", foreground="#3B8ED0", font=ctk.CTkFont(slant="italic"))

        self.input_frame = ctk.CTkFrame(self.chat_tab, height=50)
        self.input_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.msg_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Type message...")
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

        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Search messages...")
        self.search_entry.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self.load_chat_history())
        self.search_entry.bind("<KeyRelease>", self.on_search_key)
        self.search_entry.bind("<Escape>", lambda e: self.clear_search() or "break")

        self.search_btn = ctk.CTkButton(self.search_frame, text="Search", width=80, command=self.load_chat_history)
        self.search_btn.grid(row=0, column=1, padx=5, pady=5)

        self.clear_search_btn = ctk.CTkButton(self.search_frame, text="X", width=30, fg_color="gray", command=self.clear_search)
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

        self.audit_controls = ctk.CTkFrame(self.audit_tab)
        self.audit_controls.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.refresh_audit_btn = ctk.CTkButton(self.audit_controls, text="Refresh Logs", command=self.load_audit_logs)
        self.refresh_audit_btn.pack(pady=5)

    def load_audit_logs(self):
        logs = self.db.get_audit_logs(200)
        self.audit_display.configure(state="normal")
        self.audit_display.delete("1.0", "end")

        lines = []
        for log in logs:
            # log: (id, event_type, details, timestamp)
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log[3]))
            lines.append(f"[{ts}] {log[1]}: {log[2]}")

        if lines:
            self.audit_display.insert("end", "\n".join(lines) + "\n")

        self.audit_display.configure(state="disabled")
        self.audit_display.see("end")

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

    def refresh_peers(self):
        # Update peer trust levels from DB in batch
        trust_levels = self.db.get_peer_trust_levels(list(self.peers.keys()))
        for ip in self.peers:
            self.peer_trust[ip] = trust_levels.get(ip, 'untrusted')

        # Prevent unnecessary UI rebuilds using snapshot comparison
        current_snapshot = json.dumps({"peers": self.peers, "trust": self.peer_trust}, sort_keys=True)
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
            row = ctk.CTkFrame(self.peers_scroll)
            row.pack(fill="x", pady=2)
            lbl = ctk.CTkLabel(row, text=f"{name}\n{ip}", font=("Arial", 10))
            lbl.pack(side="left", padx=5)

            btn_browse = ctk.CTkButton(row, text="Browse", width=60, height=20,
                              command=lambda i=ip, n=name: self.browse_peer_files(i, n))
            btn_browse.pack(side="right", padx=5)

            btn_chat = ctk.CTkButton(row, text="Chat", width=60, height=20,
                              command=lambda i=ip, n=name: self.open_private_chat(i, n))
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

    def on_tab_change(self):
        tab = self.tabview.get()
        if tab == "Global Chat":
            self.msg_entry.focus_set()
            self.load_chat_history()
        elif tab == "Audit Logs":
            self.load_audit_logs()
        elif tab.startswith("Chat: "):
            peer_ip = self.private_chat_tabs.get(tab)
            if peer_ip:
                self.current_private_peer = peer_ip
                if peer_ip in self.private_entries:
                    self.private_entries[peer_ip].focus_set()
                self.load_private_chat(peer_ip)

    def on_search_key(self, event):
        # Throttle live search
        if self._chat_history_after_id:
            self.after_cancel(self._chat_history_after_id)
        self._chat_history_after_id = self.after(300, self.load_chat_history)

    def clear_search(self):
        if self._chat_history_after_id:
            self.after_cancel(self._chat_history_after_id)
            self._chat_history_after_id = None
        self.search_entry.delete(0, "end")
        self.load_chat_history()
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

        self._last_search_query = self.search_entry.get().strip().lower()

        query = self.search_entry.get().strip().lower()
        messages = self.db.get_messages(200)
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")

        lines = []
        for msg in messages:
            sender = msg[1]
            content = msg[2]

            # Decrypted search
            if query and query not in content.lower() and query not in sender.lower():
                continue

            ts = time.strftime('%H:%M', time.localtime(msg[3]))
            lines.append(f"[{ts}] {sender}: {content}")

        if query:
            if lines:
                self.chat_display.insert("end", f"--- Found {len(lines)} results for '{query}' ---\n\n", "search_info")
            else:
                self.chat_display.insert("end", f"--- No results found for '{query}' ---\n", "search_info")

        if lines:
            self.chat_display.insert("end", "\n".join(lines) + "\n")
        elif query:
            self.chat_display.insert("end", f"\n\nNo messages found matching '{query}'", "center")
            self.chat_display.tag_config("center", justify='center')
        elif not messages:
            self.chat_display.insert("end", "\n\nNo messages yet. Say hello!", "center")
            self.chat_display._textbox.tag_config("center", justify='center')

        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def get_ttl_seconds(self, var=None):
        val = var.get() if var else self.ttl_var.get()
        if val == "1m": return 60
        if val == "10m": return 600
        if val == "1h": return 3600
        if val == "1d": return 86400
        return None

    def send_message(self, event=None):
        msg = self.msg_entry.get()
        if not msg: return
        ttl = self.get_ttl_seconds()

        expires_at = (time.time() + ttl) if ttl else None

        # If we are in a private chat tab, send private message
        current_tab = self.tabview.get()
        if current_tab.startswith("Chat: "):
            peer_ip = self.current_private_peer
            if peer_ip:
                msg_id = self.db.add_message(self.username, msg, recipient=peer_ip, expires_at=expires_at)
                threading.Thread(target=self.network.send_message, args=(peer_ip, self.username, msg, msg_id, True, ttl)).start()
                self.msg_entry.delete(0, "end")
                self.load_private_chat(peer_ip)
                return

        # Otherwise send global message
        msg_id = self.db.add_message(self.username, msg, expires_at=expires_at)
        for ip in self.peers:
            self.executor.submit(self.network.send_message, ip, self.username, msg, msg_id, False, ttl)

        self.msg_entry.delete(0, "end")
        self.load_chat_history()

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
                ttl_sec = self.get_ttl_seconds(var=tvar)

                exp_at = (time.time() + ttl_sec) if ttl_sec else None

                mid = self.db.add_message(self.username, m, recipient=i, expires_at=exp_at)
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
        if peer_ip not in self.private_chats: return

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
        except:
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
            ttl = self._get_ttl_seconds(var_name="file")
            self.db.add_file(filename, path, size, local_ip, is_folder=False, checksum=checksum, ttl=ttl)
            self.current_file_view_source = "Local"
            self.source_label.configure(text="Viewing: Local Shared Files")
            self.refresh_files_view()

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
            ttl = self._get_ttl_seconds(var_name="file")
            self.db.add_file(dirname, path, size, local_ip, is_folder=True, ttl=ttl)
            self.current_file_view_source = "Local"
            self.source_label.configure(text="Viewing: Local Shared Files")
            self.refresh_files_view()

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
                # f: (id, filename, path, size, owner_ip, is_folder, checksum)
                file_data.append({
                    'filename': f[1],
                    'path': f[2],
                    'size': f[3],
                    'is_folder': f[5],
                    'owner': "Me",
                    'checksum': f[6] if len(f) > 6 else None
                })
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
            # f can be dict (from peer) or tuple (from local db)
            # Normalize to dict
            if isinstance(f, tuple):
                # f: (id, filename, path, size, owner_ip, is_folder, checksum, expires_at)
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
                # We reuse the folder download even for single files if needed,
                # or call download_file. But download_folder is more robust now for progress.
                if f.get('is_folder'):
                    self.file_manager.download_folder(target_ip, f['path'], progress_callback=self._download_progress)
                else:
                    # For a single file, we wrap it in a mock folder download report logic if we want to share the same UI
                    # Or just call download_file. Let's make it consistent.
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
        """Thread‑safe callback from FileTransferManager to update UI progress bars."""
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

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x320")
        dialog.transient(self)

        ctk.CTkLabel(dialog, text="Chat Port (TCP):").pack(pady=(10, 0))
        entry_chat = ctk.CTkEntry(dialog)
        entry_chat.insert(0, str(self.settings["tcp_chat_port"]))
        entry_chat.pack(pady=5)

        ctk.CTkLabel(dialog, text="File Port (TCP):").pack(pady=(10, 0))
        entry_file = ctk.CTkEntry(dialog)
        entry_file.insert(0, str(self.settings["tcp_file_port"]))
        entry_file.pack(pady=5)

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
        save_btn = ctk.CTkButton(dialog, text="Save & Restart", command=save, fg_color="green")
        save_btn.pack(pady=20)
        self.after(200, lambda: entry_chat.focus_set())

    def on_closing(self):
        if hasattr(self, 'discovery'):
            self.discovery.stop()
        self.network.close()
        self.file_manager.close()
        self.db.close()
        self.executor.shutdown(wait=False)
        self.destroy()

if __name__ == "__main__":
    app = LANMessengerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
