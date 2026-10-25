import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REVISION = '87e058624c72863db53bdaf7fb6f16576dddb6ab'


def build(source, compiler, dependencies, output, shared=False, libc_headers=None):
    if shared and libc_headers is None:
        raise ValueError('Shared builds require --libc-headers matching the router musl ABI')
    source = source.resolve()
    dependencies = dependencies.resolve()
    revision = subprocess.run(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if revision != REVISION:
        raise ValueError('Unexpected upstream revision: ' + revision)
    with tempfile.TemporaryDirectory(prefix='rd05-tpws-build-') as directory:
        work = Path(directory)
        target = work / 'tpws'
        shutil.copytree(source / 'tpws', target)
        subprocess.run(['git', 'apply', str(BASE / 'tools/tpws/raw-fake.patch')], cwd=work, check=True)
        for name in ('raw_fake.c', 'raw_fake.h'):
            shutil.copyfile(BASE / 'tools/tpws' / name, target / name)
        executable = work / 'tpws-rd05'
        subprocess.run(
            [compiler, '-std=gnu99', '-Os', '-flto=auto', '-ffunction-sections',
             '-fdata-sections', '-Wl,--gc-sections', '-s',
             *([] if shared else ['-static']),
             *(['-isystem', str(libc_headers.resolve())] if libc_headers else []),
             '-I' + str(dependencies / 'include'),
             *(str(path) for path in sorted(target.glob('*.c'))),
             '-L' + str(dependencies / 'lib'),
             *(['-Wl,-Bstatic', '-lz', '-Wl,-Bdynamic', '-lpthread'] if shared else ['-lz', '-lpthread']),
             '-o', str(executable)],
            check=True,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(executable, output)
        output.chmod(0o755)
    print('Built ' + str(output))


def main():
    parser = argparse.ArgumentParser(description='Build the RD05 tpws client with raw TLS injection')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=BASE / 'router/tpws')
    parser.add_argument('--shared', action='store_true', help='Use the router system musl library')
    parser.add_argument('--libc-headers', type=Path, help='Installed musl headers matching the router ABI')
    args = parser.parse_args()
    build(args.source, args.cc, args.dependencies, args.output, args.shared, args.libc_headers)


if __name__ == '__main__':
    main()
