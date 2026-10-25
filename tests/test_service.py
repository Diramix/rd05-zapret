import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import auth, build_tpws, cli, installer, menu, strategies
from tools.router import Router

BASE = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        for module in (cli, menu):
            login = patch.object(module, 'connect_router', side_effect=lambda target: Router(target))
            login.start()
            self.addCleanup(login.stop)

    def test_shared_build_requires_explicit_libc_headers(self):
        with self.assertRaisesRegex(ValueError, 'libc-headers'):
            build_tpws.build(BASE, 'compiler', BASE, BASE / 'unused', shared=True)

    def test_ssh_output_is_captured(self):
        with patch('tools.router.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'ok', b'warning')) as run:
            Router('root@router').run('id', '-u')
        self.assertTrue(run.call_args.kwargs['capture_output'])
        self.assertIn('LogLevel=ERROR', run.call_args.args[0])

    def test_ssh_error_details_are_displayed(self):
        error = subprocess.CalledProcessError(255, 'ssh', stderr=b'Host key verification failed')
        with patch('builtins.print') as output:
            menu.show_error(error)
        self.assertTrue(any('Host key verification failed' in str(call) for call in output.call_args_list))

    def test_saved_connection_defaults(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(auth, 'connection_file', return_value=Path(directory) / 'connection.json'):
            auth.save_credentials('admin@192.168.31.2', 'changed')
            with patch('builtins.input', return_value=''), patch.object(auth.getpass, 'getpass', return_value=''):
                self.assertEqual(auth.prompt_credentials(), ('admin@192.168.31.2', 'changed'))

    def test_default_username_and_hidden_password(self):
        with patch.object(auth, 'load_credentials', return_value={'ip': '192.168.31.1', 'username': 'root', 'password': 'root'}), patch('builtins.input', return_value=''), patch.object(auth.getpass, 'getpass', return_value='secret') as password:
            self.assertEqual(auth.prompt_credentials('root@192.168.31.1'), ('root@192.168.31.1', 'secret'))
        password.assert_called_once()

    def test_password_helper_uses_private_channel(self):
        import sys
        session = auth.PasswordSession('special $ password')
        try:
            result = subprocess.run([sys.executable, str(BASE / 'tools/askpass.py'), 'root password:'], env=session.environment, capture_output=True, check=True)
            self.assertEqual(result.stdout.decode().strip(), 'special $ password')
            self.assertNotIn('special $ password', str(session.environment))
        finally:
            session.close()


    def test_strategy_contains_only_referenced_lists(self):
        for strategy in strategies.strategies():
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as directory:
                payload = Path(directory) / 'router'
                strategies.prepare_payload(payload, strategy)
                configuration = (payload / 'transparent.conf').read_text()
                expected = set(re.findall(r'@ROOT@/lists/([A-Za-z0-9_.-]+)', configuration))
                self.assertEqual(expected, {path.name for path in (payload / 'lists').iterdir()})
                self.assertEqual((payload / 'strategy').read_text().strip(), strategy)
                self.assertFalse((payload / 'strategies').exists())
                self.assertEqual(expected, {path.name for path in (BASE / 'router/lists').glob('*.txt')})

    def test_only_verified_strategy_is_available(self):
        self.assertEqual(set(strategies.strategies()), {'full'})
        with patch('builtins.input', return_value='1') as prompt, patch('builtins.print'):
            self.assertEqual(menu.choose_strategy(), 'full')
        prompt.assert_called_once_with('Выберите стратегию: ')
        with patch('builtins.input', return_value='0'), patch('builtins.print'):
            self.assertIsNone(menu.choose_strategy())

    def test_strategy_menu_uses_metadata(self):
        metadata = {'full': {'name': 'Custom name', 'description': 'Custom description'}}
        with patch.object(menu, 'strategies', return_value=metadata), patch('builtins.input', return_value='1'), patch('builtins.print') as output:
            self.assertEqual(menu.choose_strategy(), 'full')
        text = '\n'.join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn('Custom name [full]', text)
        self.assertIn('Custom description', text)

    def test_youtube_api_profile_does_not_capture_entire_google_list(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / 'router'
            strategies.prepare_payload(payload, 'full')
            configuration = (payload / 'transparent.conf').read_text()
        profiles = configuration.split('--new')
        api = next(profile for profile in profiles if '--tlsrec=sni' in profile)
        self.assertIn('--hostlist-domains=youtubei.googleapis.com,jnn-pa.googleapis.com', api)
        self.assertNotIn('--hostlist=', api)
        general = next(profile for profile in profiles if '--filter-l7=tls' in profile and '--hostlist=' in profile)
        self.assertIn('--raw-fake=@ROOT@/clienthello.bin', general)

    def test_unknown_strategy_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            strategies.prepare_payload(Path(directory) / 'router', '../router')

    def test_install_replaces_previous_directory(self):
        router = Mock()
        router.exists.return_value = True
        router.read.return_value = b'0 0 * * * echo other\n'
        router.text.return_value = '123'
        with tempfile.TemporaryDirectory() as directory, patch.object(installer, 'quiesce'):
            payload = Path(directory) / 'router'
            strategies.prepare_payload(payload, 'full')
            installer.apply(router, '/tmp/stage/router', payload)
        calls = router.method_calls
        removal = next(i for i, call in enumerate(calls) if call[0] == 'remove')
        copy = next(i for i, call in enumerate(calls) if call[0] == 'copy')
        self.assertLess(removal, copy)
        cron = router.write.call_args.args[1]
        self.assertIn(b'echo other', cron)
        self.assertEqual(cron.count(installer.CRON_ENTRY.encode()), 1)

    def test_uninstall_preserves_other_cron_jobs(self):
        router = Mock()
        router.text.return_value = '0'
        router.exists.return_value = True
        router.read.return_value = b'0 0 * * * echo keep\n' + installer.CRON_ENTRY.encode() + b'\n'
        router.run.return_value = subprocess.CompletedProcess([], 0)
        with patch.object(installer, 'installed_status'), patch.object(installer, 'quiesce') as stop:
            installer.uninstall(router)
        stop.assert_called_once_with(router)
        router.write.assert_called_once_with(installer.CRONTAB, b'0 0 * * * echo keep\n')
        router.remove.assert_any_call(installer.ROOT)
        for name in ('RD05_TARGET4', 'RD05_TARGET6', 'RD05_EXCLUDE4', 'RD05_EXCLUDE6'):
            router.run.assert_any_call('ipset', 'destroy', name)
        router.remove.assert_any_call('/tmp/rd05-transparent-runtime.conf')
        router.remove.assert_any_call('/tmp/dnsmasq.d/rd05-zapret.conf')
        for script in (BASE / 'router').glob('*.sh'):
            for name in re.findall(r'/tmp/rd05[-A-Za-z0-9_.]+', script.read_text()):
                router.remove.assert_any_call(name)

    def test_unknown_installation_not_removed(self):
        router = Mock()
        router.exists.side_effect = [True, False]
        with self.assertRaises(ValueError):
            installer.installed_status(router)
        router.remove.assert_not_called()

    def test_check_does_not_apply(self):
        router = Mock()
        router.text.return_value = '/tmp/rd05-zapret-install.ABC123'
        with patch.object(installer, 'upload'), patch.object(installer, 'check_device'), patch.object(installer, 'apply') as apply:
            installer.install(router, True, 'full')
        apply.assert_not_called()
        router.remove.assert_called_once_with('/tmp/rd05-zapret-install.ABC123')

    def test_apply_error_disables_partial_installation_and_cleans_stage(self):
        router = Mock()
        router.text.return_value = '/tmp/rd05-zapret-install.ABC123'
        with patch.object(installer, 'upload'), patch.object(installer, 'check_device'), patch.object(installer, 'installed_status'), patch.object(installer, 'apply', side_effect=ValueError('failure')), self.assertRaises(ValueError):
            installer.install(router, False, 'full')
        router.copy.assert_not_called()
        router.run.assert_called_once_with('touch', f'{installer.ROOT}/disabled')
        router.service.assert_called_once_with('disable', root='/tmp/rd05-zapret-install.ABC123/router')
        router.remove.assert_called_once_with('/tmp/rd05-zapret-install.ABC123')

    def test_uninstalled_menu_hides_removal(self):
        with patch('builtins.print') as output:
            menu.print_menu('root@router', None)
        text = '\n'.join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertNotIn('Полностью удалить программу', text)
        self.assertNotIn('Проверить совместимость стратегии', text)
        with patch('builtins.print') as output:
            menu.print_menu('root@router', 'full (enabled)')
        text = '\n'.join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn('Полностью удалить программу', text)

    def test_cli_dispatches_selected_strategy(self):
        with patch.object(cli.shutil, 'which', return_value='ssh'), patch.object(cli, 'install') as install:
            result = cli.main(['--check', '--strategy', 'full', 'root@router'])
        self.assertEqual(result, 0)
        self.assertEqual(install.call_args.args[0].target, 'root@router')
        self.assertEqual(install.call_args.args[1:], (True, 'full'))

    def test_menu_exit_without_modification(self):
        with patch.object(menu, 'auto_check', return_value=None), patch('builtins.input', return_value='0'), patch('builtins.print'), patch.object(menu, 'install') as install, patch.object(menu, 'uninstall') as uninstall:
            menu.menu('root@router')
        install.assert_not_called()
        uninstall.assert_not_called()

    def test_strategy_selection_precedes_network_check(self):
        events = []
        def select():
            events.append('select')
            return 'full'
        def check(router):
            events.append('check')
        with patch.object(menu, 'auto_check', side_effect=check), patch.object(menu, 'choose_strategy', side_effect=select), patch.object(menu, 'install') as install, patch('builtins.input', side_effect=['1', '', '0']), patch('builtins.print'):
            menu.menu('root@router')
        self.assertEqual(events, ['check', 'select', 'check', 'check'])
        self.assertEqual(install.call_args.args[1:], (False, 'full'))

    def test_connection_timeout_does_not_show_menu(self):
        with patch.object(menu, 'auto_check', side_effect=subprocess.TimeoutExpired('ssh', 30)), patch('builtins.input') as prompt, patch('builtins.print') as output, patch.object(menu, 'print_menu') as render:
            result = menu.menu('root@router')
        self.assertEqual(result, 1)
        prompt.assert_not_called()
        render.assert_not_called()
        text = '\n'.join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn('Истекло время ожидания SSH', text)


if __name__ == '__main__':
    unittest.main()
