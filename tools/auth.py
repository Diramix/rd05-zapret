import getpass
import ipaddress
import json
import os
import secrets
import shlex
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

from .progress import pause_progress


class PasswordSession:
    def __init__(self, password):
        self.password = password
        self.token = secrets.token_hex(32)
        session = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(10)
                request = json.loads(self.rfile.readline(16384))
                if not secrets.compare_digest(request.get('token', ''), session.token):
                    return
                prompt = request.get('prompt', '')
                if 'password' in prompt.lower():
                    answer = session.password
                elif 'yes/no' in prompt.lower():
                    with pause_progress():
                        answer = input('\n' + prompt + '\nПодтвердите ключ SSH (yes/no): ').strip()
                else:
                    print('\nНе удалось автоматически ответить на запрос SSH: ' + prompt, flush=True)
                    answer = ''
                self.wfile.write(json.dumps(answer).encode() + b'\n')

        self.directory = tempfile.TemporaryDirectory(prefix='rd05-auth-')
        self.server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.server.timeout = 1
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        helper = Path(__file__).with_name('askpass.py')
        launcher = Path(self.directory.name) / ('askpass.cmd' if os.name == 'nt' else 'askpass')
        if os.name == 'nt':
            launcher.write_text(f'@echo off\n"{sys.executable}" "{helper}" %*\n', encoding='utf-8')
        else:
            launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                                + shlex.quote(str(helper)) + ' "$@"\n', encoding='utf-8')
            launcher.chmod(0o700)
        self.environment = os.environ.copy()
        self.environment.update({
            'SSH_ASKPASS': str(launcher),
            'SSH_ASKPASS_REQUIRE': 'force',
            'DISPLAY': os.environ.get('DISPLAY') or 'rd05:0',
            'RD05_AUTH_PORT': str(self.server.server_address[1]),
            'RD05_AUTH_TOKEN': self.token,
        })

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()
        self.password = ''
        self.environment.clear()


def connection_file():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.config')
    return base / 'rd05-zapret' / 'connection.json'


def load_credentials():
    defaults = {'ip': '192.168.31.1', 'username': 'root', 'password': 'root'}
    path = connection_file()
    if not path.exists():
        return defaults
    saved = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(saved, dict) or any(not isinstance(saved.get(key), str) for key in defaults):
        raise ValueError('Некорректный файл данных подключения: ' + str(path))
    return {key: saved[key] for key in defaults}


def save_credentials(target, password):
    username, _, host = target.rpartition('@')
    path = connection_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='connection-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump({'ip': host.strip('[]'), 'username': username, 'password': password}, output, ensure_ascii=False)
            output.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prompt_credentials(target=None):
    defaults = load_credentials()
    if target:
        username, separator, host = target.rpartition('@')
        defaults['ip'] = (host if separator else target).strip('[]')
        if separator:
            defaults['username'] = username
    host = input(f"IP роутера [{defaults['ip']}]: ").strip() or defaults['ip']
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError('Введите корректный IP-адрес роутера') from None
    username = input(f"Имя пользователя на роутере [{defaults['username']}]: ").strip() or defaults['username']
    if not username or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for char in username):
        raise ValueError('Некорректное имя пользователя')
    label = 'root' if defaults['password'] == 'root' else 'сохранённый'
    password = getpass.getpass(f'Пароль роутера [{label}] (ввод скрыт): ') or defaults['password']
    host = f'[{address}]' if address.version == 6 else str(address)
    return username + '@' + host, password
