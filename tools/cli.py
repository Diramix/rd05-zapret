import argparse
import shutil
import subprocess
import sys
import tarfile

from .installer import install, installed_status, uninstall
from .menu import menu
from .router import connect_router, validate_target


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Управление стратегиями Zapret на RD05 через SSH')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Проверить выбранную стратегию без установки')
    mode.add_argument('--install', action='store_true', help='Установить выбранную стратегию с автозапуском')
    mode.add_argument('--uninstall', action='store_true', help='Удалить программу и автозапуск')
    mode.add_argument('--status', action='store_true', help='Определить установленную стратегию')
    parser.add_argument('--strategy', default='full', help='Название стратегии (по умолчанию: full)')
    parser.add_argument('target', nargs='?', default=None, help='Адрес SSH (необязательно)')
    args = parser.parse_args(argv)
    try:
        if args.target:
            validate_target(args.target)
        if shutil.which('ssh') is None:
            parser.error('Требуется клиент OpenSSH')
        if not any((args.uninstall, args.status, args.check, args.install)):
            return menu(args.target) or 0
        else:
            router = connect_router(args.target)
            try:
                if args.uninstall:
                    uninstall(router)
                elif args.status:
                    print(installed_status(router) or 'Не установлено')
                else:
                    install(router, args.check, args.strategy)
            finally:
                router.close()
    except (KeyboardInterrupt, EOFError):
        print('Выход')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stdout:
            print(error.stdout.decode('utf-8', errors='replace'), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode('utf-8', errors='replace').strip(), file=sys.stderr)
        print(f'Ошибка: {error}', file=sys.stderr)
        return 1
    return 0
