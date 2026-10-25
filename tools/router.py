import re
import shlex
import subprocess

from .auth import PasswordSession, prompt_credentials, save_credentials
from .settings import ROOT


class Router:
    def __init__(self, target, password=None):
        self.target = target
        self.authentication = PasswordSession(password) if password is not None else None

    def close(self):
        if self.authentication is not None:
            self.authentication.close()
            self.authentication = None

    def run(self, *args, data=None, stream=None, check=True):
        result = subprocess.run(
            ['ssh', '-T', '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
             '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
             '-o', 'NumberOfPasswordPrompts=1', '-o', 'LogLevel=ERROR', self.target, shlex.join(args)],
            input=data, stdin=stream, capture_output=True, check=check,
            env=self.authentication.environment if self.authentication is not None else None, timeout=120 if args and (args[0].endswith('/tpws') or (args[0] == 'sh' and len(args) > 1 and args[1].endswith('.sh'))) else 30,
        )
        if self.authentication is not None and result.returncode == 0 and not getattr(self, '_credentials_saved', False):
            save_credentials(self.target, self.authentication.password)
            self._credentials_saved = True
        return result

    def text(self, *args):
        return self.run(*args).stdout.decode('utf-8').strip()

    def exists(self, path, directory=False):
        result = self.run('test', '-d' if directory else '-e', path, check=False)
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
        return result.returncode == 0

    def read(self, path):
        return self.run('cat', path).stdout

    def write(self, path, data):
        self.run('sh', '-c', 'cat > ' + shlex.quote(path), data=data)

    def copy(self, source, destination):
        self.run('cp', '-R', source, destination)

    def remove(self, path):
        self.run('rm', '-rf', path)

    def chmod(self, mode, *paths):
        self.run('chmod', mode, *paths)

    def service(self, name, root=ROOT):
        self.run('sh', f'{root}/{name}.sh')


def validate_target(target):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:@%\[\]-]*', target):
        raise ValueError('Некорректный адрес SSH')
    return target


def connect_router(target=None):
    target, password = prompt_credentials(target)
    return Router(validate_target(target), password)
