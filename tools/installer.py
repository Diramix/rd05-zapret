import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .progress import Spinner
from .settings import CRON_ENTRY, CRONTAB, REQUIRED_COMMANDS, ROOT
from .strategies import prepare_payload, upload


def check_device(router, source, payload):
    if router.text('id', '-u') != '0':
        raise ValueError('Требуется доступ root')
    version = router.text('cat', '/usr/share/xiaoqiang/xiaoqiang_version')
    if not re.search(r"option\s+HARDWARE\s+'RD05'", version):
        raise ValueError('Эта программа предназначена для Xiaomi RD05')
    for command in REQUIRED_COMMANDS:
        router.run('sh', '-c', 'command -v ' + shlex.quote(command))
    for tool in ('iptables', 'ip6tables'):
        router.run(tool, '-t', 'nat', '-L', 'PREROUTING', '-n')
    for interface in ('br-lan', 'eth2'):
        router.run('ip', 'link', 'show', interface)
    if not router.exists('/data/etc/crontabs', directory=True):
        raise ValueError('Постоянное хранилище автозапуска недоступно')
    for script in sorted(payload.glob('*.sh')):
        router.run('sh', '-n', f'{source}/{script.name}')
    configuration = (payload / 'transparent.conf').read_text(encoding='utf-8').replace('@ROOT@', source)
    router.run(f'{source}/tpws', '--dry-run', *shlex.split(configuration))
    required = int(router.text('du', '-sk', source).split()[0])
    available = int(router.text('df', '-k', '/data').splitlines()[-1].split()[3])
    if available < required + 128:
        raise ValueError('Недостаточно свободного места в /data')


def stop_service(router):
    if router.exists(f'{ROOT}/disable.sh'):
        router.service('disable')
        time.sleep(1)


def quiesce(router):
    stop_service(router)
    for attempt in range(15):
        if not router.exists('/tmp/rd05-ensure.lock'):
            stop_service(router)
            return
        time.sleep(1)
    raise ValueError('Фоновая проверка автозапуска ещё работает; повторите позже')


def apply(router, source, payload):
    quiesce(router)
    router.remove(ROOT)
    router.run('mkdir', '-p', ROOT)
    router.copy(f'{source}/.', ROOT + '/')
    router.chmod('755', ROOT, f'{ROOT}/lists', f'{ROOT}/tpws',
                 *(f'{ROOT}/{p.name}' for p in sorted(payload.glob('*.sh'))))
    router.chmod('644', f'{ROOT}/transparent.conf', f'{ROOT}/strategy',
                 *(f'{ROOT}/lists/{p.name}' for p in sorted((payload / 'lists').glob('*.txt'))))
    router.run('mkdir', '-p', '/etc/crontabs')
    cron = router.read(CRONTAB) if router.exists(CRONTAB) else b''
    if f'{ROOT}/ensure.sh'.encode() not in cron:
        router.write(CRONTAB, cron.rstrip(b'\n') + b'\n' + CRON_ENTRY.encode() + b'\n')
    router.chmod('600', CRONTAB)
    router.service('enable')
    router.run('kill', '-0', router.text('cat', '/tmp/rd05-transparent.pid'))
    for tool in ('iptables', 'ip6tables'):
        router.run(tool, '-t', 'nat', '-C', 'PREROUTING', '-i', 'br-lan', '-p', 'tcp', '-j', 'RD05_TPWS')


def install(router, check_only=False, strategy='full'):
    with tempfile.TemporaryDirectory(prefix='rd05-payload-') as directory:
        payload = Path(directory) / 'router'
        prepare_payload(payload, strategy)
        install_payload(router, check_only, payload)


def install_payload(router, check_only, payload):
    stage = router.text('mktemp', '-d', '/tmp/rd05-zapret-install.XXXXXX')
    source = f'{stage}/router'
    if not re.fullmatch(r'/tmp/rd05-zapret-install\.[A-Za-z0-9]+', stage):
        raise ValueError('Роутер вернул некорректный временный каталог')
    changed = False
    try:
        with Spinner('Передача выбранной стратегии в ОЗУ роутера'):
            upload(router, stage, payload)
        with Spinner('Проверка модели, команд, IPv4/IPv6 и конфигурации'):
            check_device(router, source, payload)
        if check_only:
            return
        installed_status(router)
        changed = True
        with Spinner('Установка файлов и включение автозапуска'):
            apply(router, source, payload)
        changed = False
        print('Установлено в /data/rd05-zapret; автозапуск включён')
        print('Переподключите Wi-Fi на устройствах и перезапустите приложения, чтобы обновить DNS и соединения.')
    except (Exception, KeyboardInterrupt):
        if changed:
            try:
                if router.exists(ROOT, directory=True):
                    router.run('touch', f'{ROOT}/disabled')
                router.service('disable', root=source)
            except (OSError, subprocess.SubprocessError) as error:
                print(f'Не удалось отключить незавершённую установку: {error}', file=sys.stderr)
        raise
    finally:
        try:
            router.remove(stage)
        except (OSError, subprocess.SubprocessError) as error:
            print(f'Не удалось удалить временный каталог {stage}: {error}', file=sys.stderr)


def installed_status(router):
    if not router.exists(ROOT, directory=True):
        return None
    if not router.exists(f'{ROOT}/transparent-off.sh'):
        raise ValueError('Каталог установки не распознан; изменение отменено')
    strategy = router.text('cat', f'{ROOT}/strategy') if router.exists(f'{ROOT}/strategy') else 'legacy'
    disabled = router.exists(f'{ROOT}/disabled')
    return strategy + (' (disabled)' if disabled else ' (enabled)')


def uninstall(router):
    if router.text('id', '-u') != '0':
        raise ValueError('Требуется доступ root')
    installed_status(router)
    if router.exists(CRONTAB):
        original = router.read(CRONTAB)
        remaining = b''.join(line for line in original.splitlines(keepends=True)
                             if (ROOT + '/').encode() not in line)
        if remaining != original:
            router.write(CRONTAB, remaining)
    quiesce(router)
    for name in ('RD05_TARGET4', 'RD05_TARGET6', 'RD05_EXCLUDE4', 'RD05_EXCLUDE6'):
        exists = router.run('ipset', 'list', name, check=False)
        if exists.returncode == 0:
            router.run('ipset', 'destroy', name)
        elif exists.returncode != 1:
            raise subprocess.CalledProcessError(exists.returncode, exists.args)
    temporary = (
        'transparent.active', 'transparent.pid', 'transparent-runtime.conf', 'transparent.log',
        'watchdog.pid', 'watchdog.log', 'seed.pid', 'seed.updated',
        'dns-seed.log', 'dnsmasq-restart.log', 'dnsmasq.new', 'ipsets.signature',
        'domains.include', 'domains.exclude', 'ensure.log', 'ensure.lock',
    )
    for name in temporary:
        router.remove('/tmp/rd05-' + name)
    router.remove('/tmp/dnsmasq.d/rd05-zapret.conf')
    router.remove(ROOT)
    print('Программа, автозапуск, правила сети и временные файлы удалены')
