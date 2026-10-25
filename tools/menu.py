import os
import subprocess
import sys
import tarfile

from .installer import install, installed_status, uninstall
from .progress import Spinner
from .router import connect_router
from .strategies import strategies

BANNER = r"""
░▒▓████████▓▒░░▒▓██████▓▒░░▒▓███████▓▒░░▒▓███████▓▒░░▒▓████████▓▒░▒▓████████▓▒░
       ░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░         ░▒▓█▓▒░
     ░▒▓██▓▒░░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░         ░▒▓█▓▒░
   ░▒▓██▓▒░  ░▒▓████████▓▒░▒▓███████▓▒░░▒▓███████▓▒░░▒▓██████▓▒░    ░▒▓█▓▒░
 ░▒▓██▓▒░    ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░         ░▒▓█▓▒░
░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░         ░▒▓█▓▒░
░▒▓████████▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓████████▓▒░  ░▒▓█▓▒░
"""


def choose_strategy():
    available = list(strategies().items())
    print('\nДоступные стратегии:')
    for index, (slug, metadata) in enumerate(available, 1):
        name = metadata['name']
        description = metadata['description']
        print(f'{index}) {name} [{slug}]\n   {description}')
    print('0) Назад')
    choice = input('Выберите стратегию: ').strip()
    if choice == '0':
        return None
    if not choice.isdigit() or not 1 <= int(choice) <= len(available):
        raise ValueError('Неверный номер стратегии')
    return available[int(choice) - 1][0]


def clear_console():
    if sys.stdout.isatty():
        print('\033[2J\033[H', end='', flush=True)


def print_menu(target, status):
    clear_console()
    color = sys.stdout.isatty() and not os.environ.get('NO_COLOR')
    if color:
        print('\033[96m', end='')
    print(BANNER)
    print('=' * 78)
    print(f'Роутер: {target.rsplit("@", 1)[-1]} | Состояние: {status_label(status)}')
    print('1) Переустановить / обновить' if status else '1) Установить')
    print('2) Проверить подключение и состояние')
    if status and status != 'not checked':
        print('3) Полностью удалить программу')
    print('0) Выход')
    print('=' * 78)
    if color:
        print('\033[0m', end='')


def auto_check(router):
    with Spinner('Проверка подключения к роутеру'):
        user = router.text('id', '-u')
    if user != '0':
        raise ValueError('Нужен доступ root')
    with Spinner('Проверка установленной программы'):
        status = installed_status(router)
    print('Проверка завершена: ' + status_label(status), flush=True)
    return status


def status_label(status):
    if status == 'not checked':
        return 'нет подключения / состояние неизвестно'
    if status is None:
        return 'не установлено'
    return status.replace('legacy', 'прежняя версия').replace('(enabled)', '(включено)').replace('(disabled)', '(отключено)')


def show_error(error):
    if isinstance(error, subprocess.TimeoutExpired):
        message = 'Истекло время ожидания SSH. Проверьте адрес, соединение и ввод пароля.'
    elif isinstance(error, subprocess.CalledProcessError) and error.returncode == 255:
        message = 'Не удалось подключиться по SSH: проверьте пароль, доступность роутера или ключ сервера.'
    else:
        message = str(error)
    print('Ошибка: ' + message, file=sys.stderr, flush=True)
    details = getattr(error, 'stderr', None)
    if details:
        print(details.decode('utf-8', errors='replace').strip(), file=sys.stderr, flush=True)


def menu(target=None):
    router = connect_router(target)
    target = router.target
    try:
        try:
            status = auto_check(router)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            show_error(error)
            return 1
        while True:
            print_menu(target, status)
            choice = input('Выберите действие: ').strip()
            if choice == '0':
                return
            try:
                if choice == '1':
                    selected = choose_strategy()
                    if selected:
                        status = auto_check(router)
                        print('Начинается установка стратегии…', flush=True)
                        install(router, False, selected)
                        status = auto_check(router)
                        print('Готово.', flush=True)
                elif choice == '2':
                    status = auto_check(router)
                elif choice == '3' and status and status != 'not checked':
                    print('Удаление программы и автозапуска…', flush=True)
                    uninstall(router)
                    status = auto_check(router)
                else:
                    print('Неверный пункт меню')
            except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
                show_error(error)
                if isinstance(error, (OSError, subprocess.SubprocessError)) or status == 'not checked':
                    return 1
            input('\nНажмите Enter, чтобы вернуться в меню…')
    finally:
        router.close()
