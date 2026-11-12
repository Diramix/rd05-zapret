"""Independent Telegram WS proxy installation for an existing Router connection."""

import re
import shlex
import time
from pathlib import Path

from .settings import BASE, CRONTAB
from .strategies import upload

ROOT = '/data/rd05-tg-standalone'
LEGACY_ROOT = '/data/rd05-zapret'
PAYLOAD = BASE / 'router' / 'tg-standalone'
CRON_ENTRY = f'* * * * * /bin/sh {ROOT}/ensure.sh >/tmp/rd05-tg-standalone-ensure.log 2>&1'
MARKER = b'rd05-tg-standalone-v1\n'
SHIM = b'#!/bin/sh\n# TG moved to /data/rd05-tg-standalone; managed independently.\nexit 0\n'


def installed_status(router):
    """Return 'enabled', 'disabled', or None; reject an unrecognized root."""
    if not router.exists(ROOT):
        return None
    if not router.exists(f'{ROOT}/.owner') or router.read(f'{ROOT}/.owner') != MARKER:
        raise ValueError('Каталог TG не распознан; изменение отменено')
    return 'disabled' if router.exists(f'{ROOT}/disabled') else 'enabled'


def _root(router):
    if router.text('id', '-u') != '0':
        raise ValueError('Требуется доступ root')


def _cron(router, enable):
    original = router.read(CRONTAB) if router.exists(CRONTAB) else b''
    entry = CRON_ENTRY.encode()
    lines = original.splitlines(keepends=True)
    remaining = b''.join(line for line in lines if line.rstrip(b'\r\n') != entry)
    if enable:
        remaining = remaining.rstrip(b'\n') + (b'\n' if remaining else b'') + entry + b'\n'
    if remaining != original:
        router.write(CRONTAB, remaining)
        router.chmod('600', CRONTAB)


def migrate_shared(router):
    """Detach the exact known shared TG script, leaving zapret and its cron intact."""
    script = f'{LEGACY_ROOT}/tg-proxy.sh'
    if not router.exists(script):
        return False
    current = router.read(script)
    if current == SHIM:
        return False
    if current != (BASE / 'router' / 'tg-proxy.sh').read_bytes():
        raise ValueError('Совместная установка TG не распознана; миграция отменена')
    lock = '/tmp/rd05-ensure.lock'
    acquired = False
    for _ in range(15):
        result = router.run('mkdir', lock, check=False)
        if result.returncode == 0:
            acquired = True
            break
        time.sleep(1)
    if not acquired:
        raise ValueError('Проверка zapret занята; повторите миграцию позже')
    temporary = f'{LEGACY_ROOT}/.tg-standalone-shim'
    try:
        if router.read(script) != current:
            raise ValueError('Совместный скрипт изменился во время миграции')
        router.write(temporary, SHIM)
        router.chmod('755', temporary)
        router.run('sh', script, 'stop')
        router.run('mv', '-f', temporary, script)
    finally:
        router.remove(temporary)
        router.run('rmdir', lock)
    return True


def _stop(router):
    router.run('touch', f'{ROOT}/disabled')
    for _ in range(110):
        if not router.exists('/tmp/rd05-tg-standalone.lock'):
            router.run('sh', f'{ROOT}/proxy.sh', 'stop')
            return
        time.sleep(1)
    raise ValueError('Проверка TG ещё работает; повторите позже')


def install(router, check_only=False):
    """Install and start TG, or only validate prerequisites when check_only is true.

    router is a tools.router.Router-compatible connection. Raises on failure.
    """
    _root(router)
    installed_status(router)
    if not router.exists('/data/etc/crontabs', directory=True):
        raise ValueError('Постоянное хранилище автозапуска недоступно')
    for command in ('sh', 'tar', 'curl', 'openssl', 'awk', 'ip', 'netstat', 'readlink', 'mkdir', 'mv'):
        router.run('sh', '-c', 'command -v ' + shlex.quote(command))
    legacy = f'{LEGACY_ROOT}/tg-proxy.sh'
    if router.exists(legacy) and router.read(legacy) not in (SHIM, (BASE / 'router' / 'tg-proxy.sh').read_bytes()):
        raise ValueError('Совместная установка TG не распознана; миграция отменена')
    stage = router.text('mktemp', '-d', '/tmp/rd05-tg-install.XXXXXX')
    if not re.fullmatch(r'/tmp/rd05-tg-install\.[A-Za-z0-9]+', stage):
        raise ValueError('Роутер вернул некорректный временный каталог')
    try:
        upload(router, stage, PAYLOAD)
        for name in ('ensure.sh', 'proxy.sh'):
            router.run('sh', '-n', f'{stage}/router/{name}')
        if check_only:
            return
        if installed_status(router) is not None:
            _stop(router)
        else:
            router.run('mkdir', ROOT)
            router.write(f'{ROOT}/.owner', MARKER)
            router.run('touch', f'{ROOT}/disabled')
        router.copy(f'{stage}/router/.', ROOT + '/')
        router.chmod('755', ROOT, f'{ROOT}/ensure.sh', f'{ROOT}/proxy.sh')
        migrate_shared(router)
        router.run('mkdir', '-p', '/etc/crontabs')
        _cron(router, True)
        router.remove(f'{ROOT}/disabled')
        try:
            router.run('sh', f'{ROOT}/ensure.sh')
            router.run('kill', '-0', router.text('cat', '/tmp/rd05-tg-standalone.pid'))
        except (Exception, KeyboardInterrupt):
            _stop(router)
            raise
    finally:
        router.remove(stage)


def uninstall(router):
    """Remove only the independent proxy and its exact cron entry."""
    _root(router)
    status = installed_status(router)
    if status is not None:
        _stop(router)
    _cron(router, False)
    if status is not None:
        for name in ('', '.pid', '.tar.gz', '.new', '.log', '-ensure.log'):
            router.remove('/tmp/rd05-tg-standalone' + name)
        router.remove(ROOT)
