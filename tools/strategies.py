import json
import shutil
import tarfile
import tempfile

from .settings import BASE


def archive_permissions(info):
    if not (info.isdir() or info.isfile()):
        raise ValueError('Неподдерживаемый файл архива: ' + info.name)
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mode = 0o755 if info.isdir() or info.name.endswith('.sh') or info.name == 'router/tpws' else 0o644
    return info


def strategies():
    result = {}
    for directory in sorted((BASE / 'strategies').iterdir()):
        if directory.is_dir() and (directory / 'info.json').is_file():
            metadata = json.loads((directory / 'info.json').read_text(encoding='utf-8'))
            result[directory.name] = metadata
    return result


def prepare_payload(destination, strategy):
    if strategy not in strategies():
        raise ValueError('Неизвестная стратегия: ' + strategy)
    selected = BASE / 'strategies' / strategy
    destination.mkdir(parents=True)
    for source in (BASE / 'router').iterdir():
        if source.is_file():
            shutil.copyfile(source, destination / source.name)
    shared = sorted((BASE / 'router/lists').glob('*.txt'))
    groups = {'@HOSTLISTS@': [], '@IPSETS@': [], '@EXCLUDES@': []}
    for path in shared:
        name = path.name
        if name.startswith('list-exclude'):
            group, option = '@EXCLUDES@', '--hostlist-exclude'
        elif name.startswith('ipset-exclude'):
            group, option = '@EXCLUDES@', '--ipset-exclude'
        elif name.startswith('list-'):
            group, option = '@HOSTLISTS@', '--hostlist'
        elif name.startswith('ipset-'):
            group, option = '@IPSETS@', '--ipset'
        else:
            raise ValueError('Неизвестный тип списка: ' + name)
        if path.is_symlink():
            raise ValueError('Список не должен быть символической ссылкой: ' + name)
        groups[group].append(f'{option}=@ROOT@/lists/{name}')
    configuration = (selected / 'transparent.conf').read_text(encoding='utf-8')
    for token, options in groups.items():
        if token not in configuration:
            raise ValueError('В стратегии отсутствует общий набор списков: ' + token)
        configuration = configuration.replace(token, '\n'.join(options))
    (destination / 'transparent.conf').write_bytes(configuration.encode('utf-8'))
    lists = destination / 'lists'
    lists.mkdir()
    for path in shared:
        shutil.copyfile(path, lists / path.name)
    (destination / 'strategy').write_bytes((strategy + '\n').encode())


def upload(router, stage, payload):
    with tempfile.TemporaryFile() as archive:
        with tarfile.open(fileobj=archive, mode='w:gz', format=tarfile.GNU_FORMAT) as package:
            package.add(payload, arcname='router', filter=archive_permissions)
        archive.seek(0)
        router.run('tar', '-xzf', '-', '-C', stage, stream=archive)
    router.chmod('755', stage)
