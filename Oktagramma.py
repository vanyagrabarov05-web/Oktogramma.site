#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Чат-мессенджер со всеми лёгкими улучшениями:
- темы (светлая/тёмная)
- упоминания @nick
- стикеры
- реакции (текстовые уведомления)
- статусы пользователей (онлайн, отошёл, не беспокоить)
- сохранение черновика
- пересылка сообщений
- автоустановка библиотек
"""

import subprocess
import sys
import os

def install_package(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def ensure_modules():
    missing = []
    try:
        import cryptography
    except ImportError:
        missing.append("cryptography")
    try:
        import PIL
    except ImportError:
        missing.append("pillow")
    if missing:
        print(f"📦 Устанавливаю: {', '.join(missing)} ...")
        for pkg in missing:
            install_package(pkg)
        print("✅ Перезапуск...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

if __name__ == "__main__":
    ensure_modules()

import socket
import threading
import json
import hashlib
import secrets
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog, ttk
from datetime import datetime
import base64
import io
import re
import time
import random

from cryptography.fernet import Fernet
from PIL import Image

# ====================== СЕРВЕР ======================
clients = {}
clients_lock = threading.Lock()
history = []
private_history = {}
user_statuses = {}  # email -> status

HISTORY_FILE = "chat_history.json"
USERS_FILE = "users.json"
PRIVATE_HISTORY_FILE = "private_history.json"
MAX_HISTORY = 200
MAX_PRIVATE = 100

def hash_password(password):
    salt = secrets.token_hex(8)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"

def verify_password(stored, provided):
    if '$' not in stored:
        return False
    salt, hash_val = stored.split('$')
    check_hash = hashlib.pbkdf2_hmac('sha256', provided.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return check_hash == hash_val

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def save_history():
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-MAX_HISTORY:], f, ensure_ascii=False, indent=2)

def load_history():
    global history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if len(history) > MAX_HISTORY:
                    history = history[-MAX_HISTORY:]
        except:
            history = []

def save_private_history():
    with open(PRIVATE_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(private_history, f, ensure_ascii=False, indent=2)

def load_private_history():
    global private_history
    if os.path.exists(PRIVATE_HISTORY_FILE):
        try:
            with open(PRIVATE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                private_history = json.load(f)
        except:
            private_history = {}

def add_private_message(sender_email, target_email, msg_data):
    for email in [sender_email, target_email]:
        if email not in private_history:
            private_history[email] = {}
        if target_email not in private_history[email]:
            private_history[email][target_email] = []
        private_history[email][target_email].append(msg_data)
        if len(private_history[email][target_email]) > MAX_PRIVATE:
            private_history[email][target_email] = private_history[email][target_email][-MAX_PRIVATE:]
    save_private_history()

def broadcast(message_dict, exclude_sock=None):
    data = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
    with clients_lock:
        for sock in list(clients.keys()):
            if sock != exclude_sock:
                try:
                    sock.send(data)
                except:
                    pass

def send_user_list():
    with clients_lock:
        user_list = []
        for info in clients.values():
            status = user_statuses.get(info["email"], "online")
            user_list.append({
                "nick": info["nick"],
                "realname": info["realname"],
                "email": info["email"],
                "status": status
            })
    data = json.dumps({"type": "user_list", "users": user_list}).encode('utf-8')
    with clients_lock:
        for sock in clients:
            try:
                sock.send(data)
            except:
                pass

def authenticate_or_register(client_sock):
    try:
        raw = client_sock.recv(4096).decode('utf-8')
        if not raw:
            return None
        data = json.loads(raw)
        action = data.get("action")
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        realname = data.get("realname", "").strip()
        users = load_users()
        if action == "register":
            if email in users:
                client_sock.send(json.dumps({"type": "auth", "success": False, "msg": "Email уже зарегистрирован"}).encode('utf-8'))
                return None
            if not realname:
                realname = email.split('@')[0]
            nick = f"user_{secrets.token_hex(4)}"
            users[email] = {
                "password": hash_password(password),
                "realname": realname,
                "nick": nick
            }
            save_users(users)
            client_sock.send(json.dumps({"type": "auth", "success": True, "msg": "Регистрация успешна", "realname": realname, "nick": nick, "email": email}).encode('utf-8'))
            return {"email": email, "realname": realname, "nick": nick}
        elif action == "login":
            if email not in users:
                client_sock.send(json.dumps({"type": "auth", "success": False, "msg": "Email не найден"}).encode('utf-8'))
                return None
            if not verify_password(users[email]["password"], password):
                client_sock.send(json.dumps({"type": "auth", "success": False, "msg": "Неверный пароль"}).encode('utf-8'))
                return None
            realname = users[email]["realname"]
            nick = users[email]["nick"]
            client_sock.send(json.dumps({"type": "auth", "success": True, "msg": "Вход выполнен", "realname": realname, "nick": nick, "email": email}).encode('utf-8'))
            return {"email": email, "realname": realname, "nick": nick}
        else:
            client_sock.send(json.dumps({"type": "auth", "success": False, "msg": "Неизвестное действие"}).encode('utf-8'))
            return None
    except Exception as e:
        print(f"Auth error: {e}")
        return None

def handle_client(client_sock, addr):
    user_info = None
    try:
        client_sock.settimeout(30)
        user_info = authenticate_or_register(client_sock)
        if not user_info:
            client_sock.close()
            return
        nick = user_info["nick"]
        realname = user_info["realname"]
        email = user_info["email"]
        with clients_lock:
            for sock, info in clients.items():
                if info.get("email") == email:
                    client_sock.send(json.dumps({"type": "system", "msg": "Вы уже подключены с другого устройства"}).encode('utf-8'))
                    client_sock.close()
                    return
            clients[client_sock] = {"nick": nick, "realname": realname, "email": email}
        user_statuses[email] = "online"
        print(f"[+] {realname} ({nick}) {addr} подключился")
        for msg in history:
            try:
                client_sock.send(json.dumps(msg).encode('utf-8'))
            except:
                break
        for target_email, msgs in private_history.get(email, {}).items():
            for msg in msgs:
                client_sock.send(json.dumps(msg).encode('utf-8'))
        broadcast({"type": "system", "msg": f"{realname} присоединился к чату", "time": datetime.now().strftime("%H:%M:%S")})
        send_user_list()
        while True:
            raw = client_sock.recv(8192).decode('utf-8')
            if not raw:
                break
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type == "message":
                text = data["msg"]
                if text.strip():
                    words = text.split()
                    mentioned = []
                    for word in words:
                        if word.startswith('@') and len(word) > 1:
                            target_nick = word[1:]
                            with clients_lock:
                                for sock, info in clients.items():
                                    if info["nick"] == target_nick:
                                        mentioned.append((target_nick, sock))
                                        break
                    for target_nick, target_sock in mentioned:
                        if target_sock != client_sock:
                            try:
                                target_sock.send(json.dumps({
                                    "type": "system",
                                    "msg": f"{realname} упомянул вас в сообщении: {text[:50]}...",
                                    "time": datetime.now().strftime("%H:%M:%S")
                                }).encode('utf-8'))
                            except:
                                pass
                    entry = {
                        "type": "message",
                        "id": f"{int(time.time()*1000)}_{random.randint(1000,9999)}",
                        "nick": nick,
                        "realname": realname,
                        "msg": text,
                        "time": datetime.now().strftime("%H:%M:%S")
                    }
                    history.append(entry)
                    if len(history) > MAX_HISTORY:
                        history = history[-MAX_HISTORY:]
                    save_history()
                    broadcast(entry)
            elif msg_type == "private":
                target_nick = data["to"]
                priv_msg = data["msg"]
                target_sock = None
                target_info = None
                with clients_lock:
                    for sock, info in clients.items():
                        if info["nick"] == target_nick:
                            target_sock = sock
                            target_info = info
                            break
                if target_sock:
                    priv_entry = {
                        "type": "private",
                        "id": f"{int(time.time()*1000)}_{random.randint(1000,9999)}",
                        "from_nick": nick,
                        "from_name": realname,
                        "from_email": email,
                        "to_nick": target_nick,
                        "to_email": target_info["email"],
                        "msg": priv_msg,
                        "time": datetime.now().strftime("%H:%M:%S")
                    }
                    add_private_message(email, target_info["email"], priv_entry)
                    target_sock.send(json.dumps(priv_entry).encode('utf-8'))
                    client_sock.send(json.dumps({
                        "type": "private_sent",
                        "id": priv_entry["id"],
                        "to": target_nick,
                        "msg": priv_msg,
                        "time": priv_entry["time"]
                    }).encode('utf-8'))
                else:
                    client_sock.send(json.dumps({
                        "type": "system",
                        "msg": f"Пользователь {target_nick} не в сети",
                        "time": datetime.now().strftime("%H:%M:%S")
                    }).encode('utf-8'))
            elif msg_type == "image":
                entry = {
                    "type": "image",
                    "id": f"{int(time.time()*1000)}_{random.randint(1000,9999)}",
                    "nick": nick,
                    "realname": realname,
                    "data": data["data"],
                    "filename": data.get("filename", "image.png"),
                    "time": datetime.now().strftime("%H:%M:%S")
                }
                history.append(entry)
                if len(history) > MAX_HISTORY:
                    history = history[-MAX_HISTORY:]
                save_history()
                broadcast(entry)
            elif msg_type == "reaction":
                # reaction: { "msg_id": str, "reaction": str }
                msg_id = data["msg_id"]
                reaction = data["reaction"]
                # Отправим системное сообщение всем, у кого есть это сообщение в истории
                # Упрощённо: просто отправляем уведомление в общий чат
                broadcast({
                    "type": "system",
                    "msg": f"{realname} поставил(а) {reaction} на сообщение",
                    "time": datetime.now().strftime("%H:%M:%S")
                })
            elif msg_type == "status":
                new_status = data["status"]
                user_statuses[email] = new_status
                send_user_list()
            elif msg_type == "typing":
                target_nick = data.get("to")
                if target_nick:
                    with clients_lock:
                        for sock, info in clients.items():
                            if info["nick"] == target_nick:
                                sock.send(json.dumps({"type": "typing", "from": realname, "from_nick": nick}).encode('utf-8'))
                                break
                else:
                    broadcast({"type": "typing", "from": realname, "from_nick": nick})
            elif msg_type == "forward":
                # forward: { "original_msg": str, "target_type": "public"/"private", "target_nick": str or None }
                original = data["original_msg"]
                target_type = data["target_type"]
                target_nick = data.get("target_nick")
                forward_text = f"📨 Переслано от {realname}: {original}"
                if target_type == "public":
                    entry = {
                        "type": "message",
                        "id": f"{int(time.time()*1000)}_{random.randint(1000,9999)}",
                        "nick": nick,
                        "realname": realname,
                        "msg": forward_text,
                        "time": datetime.now().strftime("%H:%M:%S")
                    }
                    history.append(entry)
                    if len(history) > MAX_HISTORY:
                        history = history[-MAX_HISTORY:]
                    save_history()
                    broadcast(entry)
                else:  # private
                    target_sock = None
                    target_info = None
                    with clients_lock:
                        for sock, info in clients.items():
                            if info["nick"] == target_nick:
                                target_sock = sock
                                target_info = info
                                break
                    if target_sock:
                        priv_entry = {
                            "type": "private",
                            "id": f"{int(time.time()*1000)}_{random.randint(1000,9999)}",
                            "from_nick": nick,
                            "from_name": realname,
                            "from_email": email,
                            "to_nick": target_nick,
                            "to_email": target_info["email"],
                            "msg": forward_text,
                            "time": datetime.now().strftime("%H:%M:%S")
                        }
                        add_private_message(email, target_info["email"], priv_entry)
                        target_sock.send(json.dumps(priv_entry).encode('utf-8'))
                        client_sock.send(json.dumps({
                            "type": "private_sent",
                            "id": priv_entry["id"],
                            "to": target_nick,
                            "msg": forward_text,
                            "time": priv_entry["time"]
                        }).encode('utf-8'))
                    else:
                        client_sock.send(json.dumps({
                            "type": "system",
                            "msg": f"Пользователь {target_nick} не в сети",
                            "time": datetime.now().strftime("%H:%M:%S")
                        }).encode('utf-8'))
    except (socket.timeout, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        with clients_lock:
            if client_sock in clients:
                info = clients[client_sock]
                realname = info.get("realname", "?")
                email = info.get("email")
                del clients[client_sock]
                if email in user_statuses:
                    del user_statuses[email]
                print(f"[-] {realname} отключился")
                broadcast({"type": "system", "msg": f"{realname} покинул чат", "time": datetime.now().strftime("%H:%M:%S")})
                send_user_list()
        client_sock.close()

def start_server(host='0.0.0.0', port=5555):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    load_history()
    load_private_history()
    print(f"🚀 СЕРВЕР ЗАПУЩЕН на {host}:{port}")
    while True:
        client_sock, addr = server.accept()
        threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True).start()

# ====================== КЛИЕНТ ======================
class AuthDialog:
    def __init__(self, parent, saved_creds=None):
        self.parent = parent
        self.result = None
        self.saved_creds = saved_creds or {}
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Авторизация в чате")
        self.dialog.geometry("400x380")
        self.dialog.configure(bg="#2b2d31")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        login_frame = tk.Frame(notebook, bg="#2b2d31")
        notebook.add(login_frame, text="Вход")
        tk.Label(login_frame, text="Email:", bg="#2b2d31", fg="white").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.login_email = tk.Entry(login_frame, width=30, bg="#1e1f22", fg="white")
        self.login_email.insert(0, self.saved_creds.get("email", ""))
        self.login_email.grid(row=0, column=1, padx=10, pady=10)
        tk.Label(login_frame, text="Пароль:", bg="#2b2d31", fg="white").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.login_password = tk.Entry(login_frame, width=30, bg="#1e1f22", fg="white", show="*")
        self.login_password.insert(0, self.saved_creds.get("password", ""))
        self.login_password.grid(row=1, column=1, padx=10, pady=10)
        self.remember_var = tk.IntVar(value=1)
        tk.Checkbutton(login_frame, text="Запомнить меня", variable=self.remember_var, bg="#2b2d31", fg="white", selectcolor="#2b2d31").grid(row=2, column=0, columnspan=2, pady=5)
        tk.Button(login_frame, text="Войти", bg="#5865f2", fg="white", command=self.do_login).grid(row=3, column=0, columnspan=2, pady=20)
        reg_frame = tk.Frame(notebook, bg="#2b2d31")
        notebook.add(reg_frame, text="Регистрация")
        tk.Label(reg_frame, text="Email:", bg="#2b2d31", fg="white").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.reg_email = tk.Entry(reg_frame, width=30, bg="#1e1f22", fg="white")
        self.reg_email.grid(row=0, column=1, padx=10, pady=5)
        tk.Label(reg_frame, text="Настоящее имя:", bg="#2b2d31", fg="white").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.reg_realname = tk.Entry(reg_frame, width=30, bg="#1e1f22", fg="white")
        self.reg_realname.grid(row=1, column=1, padx=10, pady=5)
        tk.Label(reg_frame, text="Пароль:", bg="#2b2d31", fg="white").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.reg_password = tk.Entry(reg_frame, width=30, bg="#1e1f22", fg="white", show="*")
        self.reg_password.grid(row=2, column=1, padx=10, pady=5)
        tk.Label(reg_frame, text="Повторите пароль:", bg="#2b2d31", fg="white").grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.reg_password2 = tk.Entry(reg_frame, width=30, bg="#1e1f22", fg="white", show="*")
        self.reg_password2.grid(row=3, column=1, padx=10, pady=5)
        tk.Button(reg_frame, text="Зарегистрироваться", bg="#5865f2", fg="white", command=self.do_register).grid(row=4, column=0, columnspan=2, pady=20)
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_close)
        self.parent.wait_window(self.dialog)
    def do_login(self):
        email = self.login_email.get().strip()
        password = self.login_password.get()
        if not email or not password:
            messagebox.showerror("Ошибка", "Заполните все поля")
            return
        self.result = {"action": "login", "email": email, "password": password, "remember": bool(self.remember_var.get())}
        self.dialog.destroy()
    def do_register(self):
        email = self.reg_email.get().strip()
        realname = self.reg_realname.get().strip()
        pwd = self.reg_password.get()
        pwd2 = self.reg_password2.get()
        if not email or not pwd:
            messagebox.showerror("Ошибка", "Email и пароль обязательны")
            return
        if pwd != pwd2:
            messagebox.showerror("Ошибка", "Пароли не совпадают")
            return
        if not realname:
            realname = email.split('@')[0]
        self.result = {"action": "register", "email": email, "password": pwd, "realname": realname, "remember": False}
        self.dialog.destroy()
    def on_close(self):
        self.result = None
        self.dialog.destroy()

class ChatClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("✨ Vibe Chat ✨")
        self.root.geometry("950x700")
        self.socket = None
        self.realname = ""
        self.nick = ""
        self.email = ""
        self.private_target = None
        self.running = True
        self.cipher = None
        self.reconnect_attempts = 0
        self.typing_timer = None
        self.last_typing_sent = 0
        self.saved_creds = self.load_credentials()
        self.theme = self.load_theme()
        self.draft_file = "draft.txt"
        self.last_received_message = ""  # для пересылки
        
        self.set_theme_colors()
        self.root.configure(bg=self.bg_main)
        self.create_widgets()
        self.apply_theme()
        self.load_draft()
        
    def load_theme(self):
        if os.path.exists("theme.json"):
            with open("theme.json", "r") as f:
                return json.load(f).get("theme", "dark")
        return "dark"
    def save_theme(self):
        with open("theme.json", "w") as f:
            json.dump({"theme": self.theme}, f)
    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.save_theme()
        self.set_theme_colors()
        self.apply_theme()
    def set_theme_colors(self):
        if self.theme == "dark":
            self.bg_main = "#1e1f22"
            self.bg_top = "#2b2d31"
            self.bg_left = "#2b2d31"
            self.bg_input = "#383a40"
            self.bg_chat = "#1e1f22"
            self.fg_text = "#dbdee1"
            self.fg_label = "white"
            self.fg_userlist = "white"
            self.btn_bg = "#5865f2"
            self.entry_bg = "#1e1f22"
            self.mention_color = "#e6b800"
            self.system_color = "#e67e22"
            self.private_color = "#9b59b6"
            self.private_sent_color = "#1abc9c"
        else:
            self.bg_main = "#f0f0f0"
            self.bg_top = "#e0e0e0"
            self.bg_left = "#e8e8e8"
            self.bg_input = "#ffffff"
            self.bg_chat = "#ffffff"
            self.fg_text = "#000000"
            self.fg_label = "#000000"
            self.fg_userlist = "#000000"
            self.btn_bg = "#4a6da8"
            self.entry_bg = "#ffffff"
            self.mention_color = "#0066cc"
            self.system_color = "#cc6600"
            self.private_color = "#8e44ad"
            self.private_sent_color = "#16a085"
    def apply_theme(self):
        self.root.configure(bg=self.bg_main)
        self.top_frame.configure(bg=self.bg_top)
        self.left_frame.configure(bg=self.bg_left)
        self.right_frame.configure(bg=self.bg_main)
        self.input_frame.configure(bg=self.bg_top)
        self.chat_area.configure(bg=self.bg_chat, fg=self.fg_text, insertbackground=self.fg_text)
        self.users_listbox.configure(bg=self.bg_left, fg=self.fg_userlist)
        self.input_field.configure(bg=self.bg_input, fg=self.fg_text, insertbackground=self.fg_text)
        self.status_label.configure(bg=self.bg_top, fg=self.fg_label)
        self.private_label.configure(bg=self.bg_main, fg=self.system_color)
        self.typing_status_label.configure(bg=self.bg_chat, fg="#888")
        self.connect_btn.configure(bg=self.btn_bg, fg="white")
        self.emoji_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.image_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.sticker_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.send_btn.configure(bg=self.btn_bg, fg="white")
        self.theme_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.status_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.forward_btn.configure(bg=self.bg_input, fg=self.fg_text)
        self.chat_area.tag_config("system", foreground=self.system_color)
        self.chat_area.tag_config("private", foreground=self.private_color)
        self.chat_area.tag_config("private_sent", foreground=self.private_sent_color)
        self.chat_area.tag_config("mention", foreground=self.mention_color, font=("Segoe UI", 10, "bold"))
    def create_widgets(self):
        self.top_frame = tk.Frame(self.root, height=60)
        self.top_frame.pack(fill=tk.X, side=tk.TOP)
        tk.Label(self.top_frame, text="Сервер:", bg=self.bg_top, fg=self.fg_label).pack(side=tk.LEFT, padx=5)
        self.server_ip = tk.Entry(self.top_frame, width=15, bg=self.entry_bg, fg=self.fg_text, insertbackground=self.fg_text)
        self.server_ip.insert(0, "127.0.0.1")
        self.server_ip.pack(side=tk.LEFT, padx=5)
        tk.Label(self.top_frame, text="Порт:", bg=self.bg_top, fg=self.fg_label).pack(side=tk.LEFT, padx=5)
        self.server_port = tk.Entry(self.top_frame, width=6, bg=self.entry_bg, fg=self.fg_text, insertbackground=self.fg_text)
        self.server_port.insert(0, "5555")
        self.server_port.pack(side=tk.LEFT, padx=5)
        self.connect_btn = tk.Button(self.top_frame, text="Подключиться", bg=self.btn_bg, fg="white", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=10)
        self.theme_btn = tk.Button(self.top_frame, text="🌙" if self.theme == "dark" else "☀️", bg=self.bg_input, fg=self.fg_text, command=self.toggle_theme)
        self.theme_btn.pack(side=tk.LEFT, padx=5)
        self.status_btn = tk.Button(self.top_frame, text="🟢 Онлайн", bg=self.bg_input, fg=self.fg_text, command=self.change_status)
        self.status_btn.pack(side=tk.LEFT, padx=5)
        self.status_label = tk.Label(self.top_frame, text="Не подключен", bg=self.bg_top, fg=self.fg_label)
        self.status_label.pack(side=tk.RIGHT, padx=10)
        
        main_pane = tk.PanedWindow(self.root, bg=self.bg_main, sashwidth=5)
        main_pane.pack(fill=tk.BOTH, expand=True)
        self.left_frame = tk.Frame(main_pane, bg=self.bg_left, width=200)
        main_pane.add(self.left_frame, width=200)
        tk.Label(self.left_frame, text="👥 Онлайн", bg=self.bg_left, fg=self.fg_label, font=("Segoe UI", 10, "bold")).pack(pady=5)
        self.users_listbox = tk.Listbox(self.left_frame, bg=self.bg_left, fg=self.fg_userlist, selectbackground=self.btn_bg, bd=0)
        self.users_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.users_listbox.bind("<Double-Button-1>", self.on_user_double_click)
        self.right_frame = tk.Frame(main_pane, bg=self.bg_main)
        main_pane.add(self.right_frame, width=750)
        self.chat_area = scrolledtext.ScrolledText(self.right_frame, wrap=tk.WORD, bg=self.bg_chat, fg=self.fg_text,
                                                   font=("Segoe UI", 10), insertbackground=self.fg_text, bd=0)
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.chat_area.config(state=tk.DISABLED)
        self.typing_status_label = tk.Label(self.right_frame, text="", bg=self.bg_chat, fg="#888", anchor="w", font=("Segoe UI", 8))
        self.typing_status_label.pack(fill=tk.X, padx=10, pady=(0,5))
        self.input_frame = tk.Frame(self.right_frame, bg=self.bg_top, height=80)
        self.input_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=10)
        self.emoji_btn = tk.Button(self.input_frame, text="😊", bg=self.bg_input, fg=self.fg_text, font=("Segoe UI", 12), command=self.show_emoji_picker)
        self.emoji_btn.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        self.sticker_btn = tk.Button(self.input_frame, text="🎨", bg=self.bg_input, fg=self.fg_text, font=("Segoe UI", 12), command=self.show_sticker_picker)
        self.sticker_btn.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        self.image_btn = tk.Button(self.input_frame, text="🖼️", bg=self.bg_input, fg=self.fg_text, font=("Segoe UI", 12), command=self.send_image)
        self.image_btn.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        self.input_field = tk.Text(self.input_frame, height=3, bg=self.bg_input, fg=self.fg_text, insertbackground=self.fg_text,
                                   font=("Segoe UI", 10), bd=0, padx=5, pady=5)
        self.input_field.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,5))
        self.input_field.bind("<KeyRelease>", self.on_typing)
        self.input_field.bind("<Return>", self.send_event)
        self.input_field.bind("<Shift-Return>", lambda e: None)
        self.send_btn = tk.Button(self.input_frame, text="➤", bg=self.btn_bg, fg="white", font=("Segoe UI", 12, "bold"), command=self.send_message)
        self.send_btn.pack(side=tk.RIGHT, fill=tk.Y)
        # Кнопка пересылки
        self.forward_btn = tk.Button(self.input_frame, text="↪️", bg=self.bg_input, fg=self.fg_text, font=("Segoe UI", 12), command=self.forward_last_message)
        self.forward_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        self.private_label = tk.Label(self.root, text="", bg=self.bg_main, fg=self.system_color, anchor="w")
        self.private_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)
        self.stickers = ["😀", "😂", "🥰", "😎", "🥳", "😭", "🔥", "❤️", "👍", "🎉", "✨", "🍕", "🍺", "🐱", "🐶", "💩"]
        self.emoji_list = ["😀", "😂", "😍", "😎", "🥲", "😭", "😡", "👍", "❤️", "🔥", "🎉", "✨", "🍕", "☕", "💀", "👀"]
        self.original_title = self.root.title()
        self.user_nick_map = {}
    
    def load_credentials(self):
        if os.path.exists("chat_creds.json"):
            with open("chat_creds.json", "r") as f:
                return json.load(f)
        return {}
    def save_credentials(self, email, password):
        with open("chat_creds.json", "w") as f:
            json.dump({"email": email, "password": password}, f)
    def get_cipher_from_password(self, password):
        if not password:
            return None
        key = hashlib.sha256(password.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))
    def save_draft(self):
        text = self.input_field.get("1.0", tk.END).strip()
        with open(self.draft_file, "w", encoding="utf-8") as f:
            f.write(text)
    def load_draft(self):
        if os.path.exists(self.draft_file):
            with open(self.draft_file, "r", encoding="utf-8") as f:
                draft = f.read()
                if draft:
                    self.input_field.insert("1.0", draft)
    def change_status(self):
        if not self.socket:
            return
        status = simpledialog.askstring("Статус", "Выберите статус: online / away / dnd", initialvalue="online")
        if status in ["online", "away", "dnd"]:
            self.socket.send(json.dumps({"type": "status", "status": status}).encode('utf-8'))
            if status == "online":
                self.status_btn.config(text="🟢 Онлайн")
            elif status == "away":
                self.status_btn.config(text="🌙 Отошёл")
            else:
                self.status_btn.config(text="🔴 Не беспокоить")
    def show_sticker_picker(self):
        picker = tk.Toplevel(self.root)
        picker.title("Выберите стикер")
        picker.geometry("300x200")
        picker.configure(bg=self.bg_left)
        frame = tk.Frame(picker, bg=self.bg_left)
        frame.pack(fill=tk.BOTH, expand=True)
        for i, sticker in enumerate(self.stickers):
            btn = tk.Button(frame, text=sticker, font=("Segoe UI", 20), bg=self.bg_input, fg=self.fg_text,
                            command=lambda s=sticker: self.send_sticker(s, picker))
            btn.grid(row=i//4, column=i%4, padx=5, pady=5, sticky="nsew")
            frame.grid_columnconfigure(i%4, weight=1)
        for i in range((len(self.stickers)+3)//4):
            frame.grid_rowconfigure(i, weight=1)
    def send_sticker(self, sticker, picker):
        picker.destroy()
        self.send_text(sticker)
    def send_text(self, text):
        if not self.socket:
            return
        encrypted = self.encrypt_text(text) if self.cipher else text
        if self.private_target:
            self.socket.send(json.dumps({"type": "private", "to": self.private_target, "msg": encrypted}).encode('utf-8'))
        else:
            self.socket.send(json.dumps({"type": "message", "msg": encrypted}).encode('utf-8'))
    def forward_last_message(self):
        if not self.socket:
            messagebox.showwarning("Нет соединения", "Вы не подключены")
            return
        if not self.last_received_message:
            self.append_message("Нет сообщений для пересылки", tag="system", sound=False)
            return
        target = simpledialog.askstring("Переслать", "Введите ник получателя (или 'public' для общего чата):")
        if not target:
            return
        if target.lower() == "public":
            target_type = "public"
            target_nick = None
        else:
            target_type = "private"
            target_nick = target
        forward_data = {
            "type": "forward",
            "original_msg": self.last_received_message,
            "target_type": target_type,
            "target_nick": target_nick
        }
        try:
            self.socket.send(json.dumps(forward_data).encode('utf-8'))
            self.append_message(f"[Система] Сообщение переслано", tag="system", sound=False)
        except:
            self.append_message("Ошибка пересылки", tag="system", sound=False)
    def show_emoji_picker(self):
        picker = tk.Toplevel(self.root)
        picker.title("Выберите эмодзи")
        picker.geometry("220x220")
        picker.configure(bg=self.bg_left)
        frame = tk.Frame(picker, bg=self.bg_left)
        frame.pack(fill=tk.BOTH, expand=True)
        for i, emoji in enumerate(self.emoji_list):
            btn = tk.Button(frame, text=emoji, font=("Segoe UI", 14), bg=self.bg_input, fg=self.fg_text,
                            command=lambda e=emoji: self.insert_emoji(e, picker))
            btn.grid(row=i//5, column=i%5, padx=3, pady=3, sticky="nsew")
            frame.grid_columnconfigure(i%5, weight=1)
        for i in range((len(self.emoji_list)+4)//5):
            frame.grid_rowconfigure(i, weight=1)
    def insert_emoji(self, emoji, picker):
        self.input_field.insert(tk.END, emoji)
        picker.destroy()
    def append_message(self, text, tag=None, sound=True):
        self.chat_area.config(state=tk.NORMAL)
        if tag is None:
            parts = re.split(r'(@\S+)', text)
            for part in parts:
                if part.startswith('@') and len(part) > 1:
                    nick = part[1:]
                    if hasattr(self, 'user_nick_map') and any(nick == u['nick'] for u in self.user_nick_map.values() if isinstance(u, dict)):
                        self.chat_area.insert(tk.END, part, "mention")
                    else:
                        self.chat_area.insert(tk.END, part)
                else:
                    self.chat_area.insert(tk.END, part)
            self.chat_area.insert(tk.END, "\n")
        else:
            self.chat_area.insert(tk.END, text + "\n", tag)
        self.chat_area.see(tk.END)
        self.chat_area.config(state=tk.DISABLED)
        if sound and self.root.focus_get() != self.root:
            self.play_notification()
            self.flash_window()
    def play_notification(self):
        try:
            import winsound
            winsound.Beep(1000, 200)
        except ImportError:
            print('\a', end='', flush=True)
    def flash_window(self):
        for _ in range(2):
            self.root.title("❗ Новое сообщение!")
            self.root.update()
            time.sleep(0.2)
            self.root.title(self.original_title)
            self.root.update()
            time.sleep(0.2)
    def send_image(self):
        if not self.socket:
            messagebox.showwarning("Нет соединения", "Вы не подключены")
            return
        filepath = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if not filepath:
            return
        try:
            img = Image.open(filepath)
            img.thumbnail((400, 400))
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            b64_data = base64.b64encode(buffer.getvalue()).decode()
            filename = os.path.basename(filepath)
            self.socket.send(json.dumps({"type": "image", "data": b64_data, "filename": filename}).encode('utf-8'))
            self.append_message(f"[{datetime.now().strftime('%H:%M:%S')}] 🖼️ Вы отправили изображение: {filename}", sound=False)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось отправить изображение: {e}")
    def handle_image(self, data):
        try:
            b64_data = data["data"]
            filename = data.get("filename", "image.png")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved_file = f"received_{timestamp}_{filename}"
            img_data = base64.b64decode(b64_data)
            with open(saved_file, "wb") as f:
                f.write(img_data)
            display_name = data.get("realname", data.get("nick", "?"))
            self.append_message(f"[{data['time']}] 🖼️ {display_name} отправил изображение: {saved_file} (сохранено)", sound=True)
        except Exception as e:
            self.append_message(f"[Ошибка] Не удалось обработать изображение: {e}", sound=False)
    def replace_smileys(self, text):
        replacements = {r':\)': '😊', r':\(': '😞', r':D': '😃', r':P': '😛', r':p': '😛', r';\)': '😉', r'<3': '❤️', r':/': '😕'}
        for pattern, emoji in replacements.items():
            text = re.sub(pattern, emoji, text)
        return text
    def encrypt_text(self, text):
        if self.cipher:
            return self.cipher.encrypt(text.encode()).decode()
        return text
    def decrypt_text(self, text):
        if self.cipher:
            try:
                return self.cipher.decrypt(text.encode()).decode()
            except:
                return "[Зашифрованное сообщение, неверный пароль]"
        return text
    def on_typing(self, event=None):
        if not self.socket:
            return
        now = time.time()
        if now - self.last_typing_sent > 2:
            self.last_typing_sent = now
            msg = {"type": "typing"}
            if self.private_target:
                msg["to"] = self.private_target
            try:
                self.socket.send(json.dumps(msg).encode('utf-8'))
            except:
                pass
        if self.typing_timer:
            self.root.after_cancel(self.typing_timer)
        self.typing_timer = self.root.after(2000, self.clear_typing_indicator)
        self.save_draft()
    def clear_typing_indicator(self):
        self.typing_status_label.config(text="")
    def show_typing(self, from_name):
        self.typing_status_label.config(text=f"✏️ {from_name} печатает...")
        if self.typing_timer:
            self.root.after_cancel(self.typing_timer)
        self.typing_timer = self.root.after(3000, self.clear_typing_indicator)
    def connect(self, is_reconnect=False):
        if self.socket and not is_reconnect:
            return
        host = self.server_ip.get().strip()
        try:
            port = int(self.server_port.get().strip())
        except:
            if not is_reconnect:
                messagebox.showerror("Ошибка", "Неверный порт")
            return
        if not is_reconnect:
            auth = AuthDialog(self.root, self.saved_creds)
            if not auth.result:
                return
            auth_data = auth.result
            if auth_data.get("remember"):
                self.save_credentials(auth_data["email"], auth_data["password"])
            self.auth_data = auth_data
            self.email = auth_data["email"]
        else:
            if not hasattr(self, 'auth_data'):
                return
        room_password = simpledialog.askstring("Шифрование", "Введите пароль комнаты (оставьте пустым для обычного режима):", show='*')
        self.cipher = self.get_cipher_from_password(room_password) if room_password else None
        try:
            if self.socket:
                self.socket.close()
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((host, port))
            self.socket.send(json.dumps(self.auth_data).encode('utf-8'))
            self.socket.settimeout(3)
            raw = self.socket.recv(4096).decode('utf-8')
            resp = json.loads(raw)
            if resp.get("type") == "auth" and resp.get("success"):
                self.realname = resp["realname"]
                self.nick = resp["nick"]
                self.email = resp.get("email", self.email)
                self.socket.settimeout(None)
                self.running = True
                self.reconnect_attempts = 0
                threading.Thread(target=self.receive_messages, daemon=True).start()
                if not is_reconnect:
                    self.connect_btn.config(state=tk.DISABLED, text="Подключено")
                self.status_label.config(text=f"Подключен как {self.realname}")
                if not is_reconnect:
                    self.append_message(f"=== Добро пожаловать, {self.realname}! ===")
                    if self.cipher:
                        self.append_message("=== Режим шифрования включен ===")
                    self.append_message("Команды: /users, /clear, /cancel. Упоминание: @ник. Двойной клик по нику - приват.")
                else:
                    self.append_message("=== Соединение восстановлено ===")
            else:
                if not is_reconnect:
                    messagebox.showerror("Ошибка авторизации", resp.get("msg", "Неизвестная ошибка"))
                self.socket.close()
                self.socket = None
                if is_reconnect:
                    self.schedule_reconnect()
        except Exception as e:
            if not is_reconnect:
                messagebox.showerror("Ошибка", f"Не удалось подключиться:\n{e}")
            if self.socket:
                self.socket.close()
            self.socket = None
            if is_reconnect:
                self.schedule_reconnect()
            else:
                self.connect_btn.config(state=tk.NORMAL, text="Подключиться")
    def schedule_reconnect(self):
        if not self.running:
            return
        self.reconnect_attempts += 1
        delay = min(30, 5 * self.reconnect_attempts)
        self.append_message(f"⚠️ Попытка переподключения через {delay} сек...", sound=False)
        self.root.after(delay * 1000, self.try_reconnect)
    def try_reconnect(self):
        if self.running and not self.socket:
            self.connect(is_reconnect=True)
    def receive_messages(self):
        while self.running and self.socket:
            try:
                raw = self.socket.recv(8192).decode('utf-8')
                if not raw:
                    break
                data = json.loads(raw)
                typ = data.get("type")
                if typ == "message":
                    msg = self.decrypt_text(data["msg"])
                    display_name = data.get("realname", data.get("nick", "?"))
                    full_msg = f"[{data['time']}] {display_name}: {msg}"
                    self.append_message(full_msg)
                    self.last_received_message = full_msg
                elif typ == "system":
                    self.append_message(f"[{data['time']}] 🔔 {data['msg']}", tag="system")
                elif typ == "private":
                    msg = self.decrypt_text(data["msg"])
                    from_name = data.get("from_name", data.get("from_nick", "?"))
                    full_msg = f"[{data['time']}] 🔒 Приват от {from_name}: {msg}"
                    self.append_message(full_msg, tag="private")
                    self.last_received_message = full_msg
                elif typ == "private_sent":
                    msg = self.decrypt_text(data["msg"])
                    self.append_message(f"[{data['time']}] ✉️ Приват для {data['to']}: {msg}", tag="private_sent")
                elif typ == "image":
                    self.handle_image(data)
                elif typ == "typing":
                    self.show_typing(data.get("from", "Кто-то"))
                elif typ == "user_list":
                    self.users_listbox.delete(0, tk.END)
                    self.user_nick_map = {}
                    for user in data["users"]:
                        status_icon = {"online":"🟢", "away":"🌙", "dnd":"🔴"}.get(user["status"], "⚪")
                        display = f"{status_icon} {user['realname']} (@{user['nick']})"
                        self.users_listbox.insert(tk.END, display)
                        self.user_nick_map[display] = user['nick']
            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError):
                break
            except json.JSONDecodeError:
                continue
        self.append_message("!!! Соединение потеряно !!!")
        self.root.after(0, self.disconnect)
        self.schedule_reconnect()
    def disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.running = False
        self.connect_btn.config(state=tk.NORMAL, text="Подключиться")
        self.status_label.config(text="Не подключен")
        self.private_target = None
        self.private_label.config(text="")
    def send_event(self, event):
        if not event.state & 0x1:
            self.send_message()
        return "break"
    def send_message(self):
        if not self.socket:
            messagebox.showwarning("Нет соединения", "Вы не подключены")
            return
        text = self.input_field.get("1.0", tk.END).strip()
        if not text:
            return
        self.input_field.delete("1.0", tk.END)
        # Удаляем черновик
        if os.path.exists(self.draft_file):
            os.remove(self.draft_file)
        if text.startswith('/'):
            if text == "/cancel":
                self.private_target = None
                self.private_label.config(text="")
                self.append_message("[Система] Вы вышли из приватного режима", tag="system", sound=False)
                return
            elif text == "/clear":
                self.chat_area.config(state=tk.NORMAL)
                self.chat_area.delete(1.0, tk.END)
                self.chat_area.config(state=tk.DISABLED)
                return
            elif text == "/users":
                self.append_message("[Система] Список пользователей слева", tag="system", sound=False)
                return
            else:
                self.append_message(f"[Система] Неизвестная команда: {text}", tag="system", sound=False)
                return
        text = self.replace_smileys(text)
        encrypted = self.encrypt_text(text) if self.cipher else text
        if self.private_target:
            self.socket.send(json.dumps({"type": "private", "to": self.private_target, "msg": encrypted}).encode('utf-8'))
            self.append_message(f"[{datetime.now().strftime('%H:%M:%S')}] ✉️ Вы -> {self.private_target}: {text}", tag="private_sent", sound=False)
            return
        self.socket.send(json.dumps({"type": "message", "msg": encrypted}).encode('utf-8'))
    def on_user_double_click(self, event):
        selection = self.users_listbox.curselection()
        if not selection:
            return
        selected = self.users_listbox.get(selection[0])
        # Убираем статус-иконку
        if '(' in selected and ')' in selected:
            parts = selected.split('@')
            if len(parts) > 1:
                nick = parts[-1].replace(')', '')
            else:
                nick = selected.split('@')[-1].replace(')', '')
        else:
            nick = selected
        if nick == self.nick:
            self.append_message("Нельзя отправлять сообщения самому себе", tag="system", sound=False)
            return
        self.private_target = nick
        self.private_label.config(text=f"💬 Приватный режим: пишете {selected.split('(')[0].strip().split(' ',1)[-1]}. Напишите /cancel для выхода.")

def main():
    print("\n=== Чат-мессенджер (все лёгкие улучшения) ===")
    print("1. Запустить сервер")
    print("2. Запустить клиент")
    choice = input("Выберите (1 или 2): ").strip()
    if choice == "1":
        host = input("IP (Enter для 0.0.0.0): ") or "0.0.0.0"
        try:
            port = int(input("Порт (Enter для 5555): ") or "5555")
        except:
            port = 5555
        start_server(host, port)
    elif choice == "2":
        root = tk.Tk()
        app = ChatClientGUI(root)
        def on_closing():
            app.running = False
            if app.socket:
                app.socket.close()
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", on_closing)
        root.mainloop()
    else:
        print("Неверный выбор")

if __name__ == "__main__":
    main()