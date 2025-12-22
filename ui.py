import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, Menu
import socket
import os
import threading
import time
import shutil
import json
from db import Database
from network import NetworkManager, PeerDiscovery
from file_transfer import FileTransferManager
from config import load_settings, save_settings

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class LANMessengerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("LAN Messenger")
        self.geometry("1100x700")
        
        # Load Settings
        self.settings = load_settings()
        
        # State
        self.username = self.settings.get("username", "User_" + str(int(time.time()))[-4:])
        self.db = Database()
        
        # Init Networking with Configured Ports
        self.file_manager = FileTransferManager(self.db, port=self.settings["tcp_file_port"])
        self.network = NetworkManager(self.db, port=self.settings["tcp_chat_port"], callback_update_ui=self.on_network_event)
        self.discovery = PeerDiscovery(self.username, 
                                     broadcast_port=self.settings["broadcast_port"],
                                     broadcast_ip=self.settings["broadcast_ip"])
        
        self.peers = {} # ip -> username
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

    def create_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LAN Messenger", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.username_entry = ctk.CTkEntry(self.sidebar_frame, placeholder_text="Username")
        self.username_entry.insert(0, self.username)
        self.username_entry.grid(row=1, column=0, padx=20, pady=10)
        self.username_entry.bind("<Return>", self.update_username)
        
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
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=20, pady=10, sticky="nsew")
        
        # ... (rest of create_main_area is same until we need to change something else)
        
        self.chat_tab = self.tabview.add("Global Chat")
        self.files_tab = self.tabview.add("Files")
        
        # -- Chat Tab --
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(0, weight=1)
        
        self.chat_display = ctk.CTkTextbox(self.chat_tab, state="disabled")
        self.chat_display.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.input_frame = ctk.CTkFrame(self.chat_tab, height=50)
        self.input_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        
        self.msg_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Type message...")
        self.msg_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.msg_entry.bind("<Return>", self.send_message)
        
        self.send_btn = ctk.CTkButton(self.input_frame, text="Send", width=100, command=self.send_message)
        self.send_btn.grid(row=0, column=1, padx=10, pady=10)

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
        
        self.download_btn = ctk.CTkButton(self.file_controls, text="Download Selected", command=self.download_selected, fg_color="green")
        self.download_btn.pack(side="right", padx=5)

        self.file_source_frame = ctk.CTkFrame(self.files_tab, height=40)
        self.file_source_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        self.source_label = ctk.CTkLabel(self.file_source_frame, text="Viewing: Local Shared Files")
        self.source_label.pack(side="left", padx=10)
        
        self.refresh_files_btn = ctk.CTkButton(self.file_source_frame, text="Refresh", width=80, command=self.refresh_files_view)
        self.refresh_files_btn.pack(side="right", padx=5)

        self.files_scroll = ctk.CTkScrollableFrame(self.files_tab, label_text="Files")
        self.files_scroll.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        
        self.file_checkboxes = [] # (checkbox_widget, file_data)

    def update_username(self, event=None):
        new_name = self.username_entry.get()
        if new_name:
            self.username = new_name
            self.discovery.username = new_name
            self.settings["username"] = new_name
            save_settings(self.settings)
            
    def refresh_peers(self):
        # Merge discovery peers and manually known peers
        # For now, self.discovery.peers is the source of truth for UI display?
        # But discovery.peers is purely from UDP.
        # We need a unified list.
        # Let's add 'self.manual_peers' or just update 'self.peers' dictionary directly.
        
        discovered = self.discovery.get_peers()
        # Merge logic:
        # We want to keep manual peers even if they don't broadcast.
        for ip, name in discovered.items():
            self.peers[ip] = name
            
        # Rebuild peer list UI
        # Check delta to avoid flickering?
        # Rebuilding is fine for low count.
        for widget in self.peers_scroll.winfo_children():
            widget.destroy()
            
        for ip, name in self.peers.items():
            row = ctk.CTkFrame(self.peers_scroll)
            row.pack(fill="x", pady=2)
            lbl = ctk.CTkLabel(row, text=f"{name}\n{ip}", font=("Arial", 10))
            lbl.pack(side="left", padx=5)
            
            btn = ctk.CTkButton(row, text="Browse", width=60, height=20, 
                              command=lambda i=ip, n=name: self.browse_peer_files(i, n))
            btn.pack(side="right", padx=5)
        self.after(2000, self.refresh_peers)
    
    def on_network_event(self, event_type, *args):
        if event_type == 'NEW_PEER':
            ip, name = args[0], args[1]
            if ip not in self.peers:
                self.peers[ip] = name
                # Reply hello if we don't know them?
                # If they said hello, they know us.
                # If we didn't initiate, we should ensure they have our name.
                # NetworkManager doesn't reply automatically.
                # Let's just send a HELLO back to be sure.
                threading.Thread(target=self.network.send_hello, args=(ip, self.username)).start()
        elif event_type == 'MSG':
             msg_id, sender, content = args[0], args[1], args[2]
             self.after(0, self.load_chat_history)
        elif event_type in ['EDIT', 'DELETE']:
             self.after(0, self.load_chat_history)

    def add_manual_peer(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Connect to IP")
        dialog.geometry("300x250")
        dialog.transient(self)
        
        ctk.CTkLabel(dialog, text="My IP: " + socket.gethostbyname(socket.gethostname())).pack(pady=10)
        
        ctk.CTkLabel(dialog, text="Enter Peer IP:").pack(pady=5)
        entry = ctk.CTkEntry(dialog)
        entry.pack(pady=5)
        
        def connect():
            ip = entry.get()
            if ip:
                # Send Hello
                threading.Thread(target=self.try_manual_connect, args=(ip,)).start()
                dialog.destroy()
        
        ctk.CTkButton(dialog, text="Connect", command=connect).pack(pady=20)

    def try_manual_connect(self, ip):
        success = self.network.send_hello(ip, self.username)
        if success:
           # We wait for them to reply HELLO to show up in list, 
           # OR we can tentatively add them as "Unknown" if we want?
           # Better to wait for reply or add as "Requested..."
           pass
        else:
           messagebox.showerror("Connection Failed", f"Could not connect to {ip}")

    def load_chat_history(self):
        messages = self.db.get_messages(100)
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        for msg in messages:
            # id, sender, content, timestamp, is_deleted
            sender = msg[1]
            content = msg[2]
            ts = time.strftime('%H:%M', time.localtime(msg[3]))
            self.chat_display.insert("end", f"[{ts}] {sender}: {content}\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def send_message(self, event=None):
        msg = self.msg_entry.get()
        if not msg: return
        
        msg_id = self.db.add_message(self.username, msg)
        
        for ip in self.peers:
            threading.Thread(target=self.network.send_message, args=(ip, self.username, msg, msg_id)).start()
            
        self.msg_entry.delete(0, "end")
        self.load_chat_history()

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
        # Find last message sent by me
        msgs = self.db.get_messages(100)
        my_msgs = [m for m in msgs if m[1] == self.username]
        if not my_msgs:
            messagebox.showinfo("Info", "No messages to edit.")
            return
            
        last_msg = my_msgs[-1] # List is reversed in get_messages, so first item?
        # get_messages returns [::-1] -> Descending order (newest first). 
        # So my_msgs[0] is the newest.
        last_msg = my_msgs[0]
        msg_id, content = last_msg[0], last_msg[2]
        
        dialog = ctk.CTkInputDialog(text="Edit your last message:", title="Edit Message")
        new_content = dialog.get_input()
        if new_content:
            self.db.edit_message(msg_id, new_content)
            for ip in self.peers:
                threading.Thread(target=self.network.send_edit, args=(ip, msg_id, new_content)).start()
            self.load_chat_history()

    def delete_last_message(self):
        msgs = self.db.get_messages(100)
        my_msgs = [m for m in msgs if m[1] == self.username]
        if not my_msgs: return
        
        last_msg = my_msgs[0]
        msg_id = last_msg[0]
        
        if messagebox.askyesno("Delete", "Delete this message?"):
            self.db.delete_message(msg_id)
            for ip in self.peers:
                threading.Thread(target=self.network.send_delete, args=(ip, msg_id)).start()
            self.load_chat_history()

    def share_file(self):
        path = filedialog.askopenfilename()
        if path:
            filename = os.path.basename(path)
            size = os.path.getsize(path)
            self.db.add_file(filename, path, size, "127.0.0.1", is_folder=False)
            if self.current_file_view_source == "Local":
                self.refresh_files_view()

    def share_folder(self):
        path = filedialog.askdirectory()
        if path:
            dirname = os.path.basename(path)
            self.db.add_file(dirname, path, 0, "127.0.0.1", is_folder=True)
            if self.current_file_view_source == "Local":
                self.refresh_files_view()

    def browse_peer_files(self, ip, name):
        self.current_file_view_source = ip
        self.source_label.configure(text=f"Viewing: {name}'s Files")
        self.refresh_files_view()

    def refresh_files_view(self):
        # Clear list
        self.file_checkboxes = []
        for w in self.files_scroll.winfo_children():
            w.destroy()
            
        if self.current_file_view_source == "Local":
            files = self.db.get_files()
            # Convert to dict format for unified rendering
            file_data = []
            for f in files:
                file_data.append({
                    'filename': f[1], 'path': f[2], 'size': f[3], 'is_folder': f[5], 'owner': "Me"
                })
            self.render_file_list(file_data)
        else:
            # Fetch from peer
            threading.Thread(target=self.fetch_peer_files, args=(self.current_file_view_source,)).start()

    def fetch_peer_files(self, ip):
        file_list = self.file_manager.get_shared_files(ip)
        # Check if view hasn't changed
        if self.current_file_view_source == ip:
            self.after(0, lambda: self.render_file_list(file_list))

    def render_file_list(self, files):
        for w in self.files_scroll.winfo_children():
            w.destroy()
        self.file_checkboxes = []
        
        for f in files:
            row = ctk.CTkFrame(self.files_scroll)
            row.pack(fill="x", pady=2)
            
            chk_var = ctk.IntVar()
            chk = ctk.CTkCheckBox(row, text=f"[{'DIR' if f.get('is_folder') else 'FILE'}] {f['filename']}", variable=chk_var)
            chk.pack(side="left", padx=5)
            
            size_mb = f['size'] / (1024*1024)
            info = ctk.CTkLabel(row, text=f"{size_mb:.2f} MB")
            info.pack(side="right", padx=10)
            
            self.file_checkboxes.append((chk_var, f))

    def download_selected(self):
        if self.current_file_view_source == "Local":
            return # Can't download own files
            
        target_ip = self.current_file_view_source
        count = 0
        for var, f in self.file_checkboxes:
            if var.get() == 1:
                count += 1
                remote_path = f['path']
                threading.Thread(target=self.start_download, args=(target_ip, remote_path, f.get('is_folder'))).start()
        
        if count > 0:
            messagebox.showinfo("Download", f"Started downloading {count} items.")

    def start_download(self, ip, path, is_folder):
        if is_folder:
            self.file_manager.download_folder(ip, path)
        else:
            self.file_manager.download_file(ip, path)

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x400")
        dialog.transient(self) # Make modal-like
        
        ctk.CTkLabel(dialog, text="Broadcast Port (UDP):").pack(pady=(10, 0))
        entry_broadcast = ctk.CTkEntry(dialog)
        entry_broadcast.insert(0, str(self.settings["broadcast_port"]))
        entry_broadcast.pack(pady=5)
        
        ctk.CTkLabel(dialog, text="Chat Port (TCP):").pack(pady=(10, 0))
        entry_chat = ctk.CTkEntry(dialog)
        entry_chat.insert(0, str(self.settings["tcp_chat_port"]))
        entry_chat.pack(pady=5)
        
        ctk.CTkLabel(dialog, text="File Port (TCP):").pack(pady=(10, 0))
        entry_file = ctk.CTkEntry(dialog)
        entry_file.insert(0, str(self.settings["tcp_file_port"]))
        entry_file.pack(pady=5)
        
        ctk.CTkLabel(dialog, text="Broadcast IP:").pack(pady=(10, 0))
        entry_ip = ctk.CTkEntry(dialog)
        entry_ip.insert(0, str(self.settings["broadcast_ip"]))
        entry_ip.pack(pady=5)
        
        def save():
            try:
                self.settings["broadcast_port"] = int(entry_broadcast.get())
                self.settings["tcp_chat_port"] = int(entry_chat.get())
                self.settings["tcp_file_port"] = int(entry_file.get())
                self.settings["broadcast_ip"] = entry_ip.get()
                self.settings["username"] = self.username
                save_settings(self.settings)
                messagebox.showinfo("Saved", "Settings saved. Please restart the application to apply changes.")
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Error", "Ports must be numbers.")
        
        ctk.CTkButton(dialog, text="Save & Restart", command=save, fg_color="green").pack(pady=20)

    def on_closing(self):
        self.discovery.stop()
        self.network.close()
        self.file_manager.close()
        self.db.close()
        self.destroy()

if __name__ == "__main__":
    app = LANMessengerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
