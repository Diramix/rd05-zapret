import subprocess
import unittest
from unittest.mock import Mock, patch

from tools import tg_installer as tg


class TgInstallerTests(unittest.TestCase):
    def test_cron_preserves_other_jobs_and_is_idempotent(self):
        router = Mock()
        router.exists.return_value = True
        router.read.return_value = b'0 0 * * * echo keep\n' + tg.CRON_ENTRY.encode() + b'\n'
        tg._cron(router, True)
        router.write.assert_not_called()
        tg._cron(router, False)
        router.write.assert_called_once_with(tg.CRONTAB, b'0 0 * * * echo keep\n')

    def test_unknown_shared_script_is_not_modified(self):
        router = Mock()
        router.exists.return_value = True
        router.read.return_value = b'custom script'
        with self.assertRaises(ValueError):
            tg.migrate_shared(router)
        router.write.assert_not_called()
        router.remove.assert_not_called()

    def test_known_shared_script_is_stopped_and_replaced_under_lock(self):
        router = Mock()
        router.exists.return_value = True
        router.read.return_value = (tg.BASE / 'router' / 'tg-proxy.sh').read_bytes()
        router.run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(tg.migrate_shared(router))
        router.run.assert_any_call('sh', tg.LEGACY_ROOT + '/tg-proxy.sh', 'stop')
        router.run.assert_any_call('mv', '-f', tg.LEGACY_ROOT + '/.tg-standalone-shim', tg.LEGACY_ROOT + '/tg-proxy.sh')
        router.run.assert_any_call('rmdir', '/tmp/rd05-ensure.lock')

    def test_unknown_root_is_not_removed(self):
        router = Mock()
        router.text.return_value = '0'
        router.exists.return_value = True
        router.read.return_value = b'other'
        with self.assertRaises(ValueError):
            tg.uninstall(router)
        router.remove.assert_not_called()
        router.write.assert_not_called()

    def test_check_only_does_not_migrate_or_install(self):
        router = Mock()
        router.exists.side_effect = lambda path, directory=False: path == '/data/etc/crontabs'
        router.text.side_effect = ['0', '/tmp/rd05-tg-install.ABC123']
        with patch.object(tg, 'upload'), patch.object(tg, 'migrate_shared') as migrate:
            tg.install(router, check_only=True)
        migrate.assert_not_called()
        router.remove.assert_called_once_with('/tmp/rd05-tg-install.ABC123')


if __name__ == '__main__':
    unittest.main()
