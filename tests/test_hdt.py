import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('hdt', Path(__file__).parents[1] / 'hdt.py')
hdt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hdt)


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hdt-test-')
        self.root = Path(self.temp.name)
        self.prefix = self.root / 'installed prefix'
        self.source = self.root / 'source'
        self.runner = self.root / 'proton'
        for f in [self.source / hdt.GAME, self.source / hdt.BNET,
                  self.runner / 'proton', self.runner / 'protonfixes/winetricks']:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('fixture')
        data = self.source / hdt.DATA
        data.mkdir(parents=True)
        (data / 'decks.xml').write_text('<decks>keep me</decks>')
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'desktop data')})
        self.env.start()
        self.runtime = patch.object(hdt, 'runtime')
        self.runtime_mock = self.runtime.start()
        self.runtime_mock.side_effect = self.fake_runtime
        self.release = patch.object(hdt, 'release', side_effect=self.fake_release)
        self.release.start()
        self.which = patch.object(hdt.shutil, 'which', return_value='/usr/bin/true')
        self.which.start()

    def tearDown(self):
        self.which.stop()
        self.release.stop()
        self.runtime.stop()
        self.env.stop()
        self.temp.cleanup()

    def fake_runtime(self, prefix, proton, args, log=None):
        (prefix / 'system.reg').write_text(
            '[Software\\\\Microsoft\\\\NET Framework Setup\\\\NDP\\\\v4\\\\Full] 1\n'
            '"Release"=dword:00080eb1\n')

    def test_false_runtime_success_is_not_ready(self):
        self.runtime_mock.side_effect = None
        (self.source / 'system.reg').write_text('WINE REGISTRY Version 2\n')
        with self.assertRaisesRegex(RuntimeError, 'could not be verified'):
            self.install()
        self.assertEqual(json.loads((self.prefix / hdt.MARKER).read_text())['status'], 'installing')

    def fake_release(self, requested, work):
        tag = '1.55.7' if requested == 'latest' else requested
        app = work / 'app'
        app.mkdir()
        (app / hdt.EXE).write_text(tag)
        return tag, app

    def cli(self, *args):
        return hdt.main(['--prefix', str(self.prefix), *args])

    def install(self):
        self.cli('install', '--source', str(self.source), '--proton', str(self.runner))

    def test_install_update_rollback_uninstall(self):
        self.install()
        self.assertEqual(self.runtime_mock.call_count, 2)
        data = self.prefix / hdt.DATA / 'decks.xml'
        self.assertEqual(data.read_text(), '<decks>keep me</decks>')
        self.cli('launch')
        self.assertIn('/desktop=HearthstoneHDT,', str(self.runtime_mock.call_args))
        self.cli('update')
        self.assertEqual((self.prefix / hdt.APP / hdt.EXE).read_text(), '1.55.7')
        self.assertEqual(data.read_text(), '<decks>keep me</decks>')
        backup = next((self.prefix / '.hdt-backups').iterdir())
        data.write_text('after update')
        self.cli('rollback', backup.name)
        self.assertEqual(data.read_text(), '<decks>keep me</decks>')
        self.assertEqual(hdt.metadata(self.prefix)['version'], hdt.TESTED)
        menu = Path(hdt.metadata(self.prefix)['menu'])
        if subprocess.run(['sh', '-c', 'command -v desktop-file-validate'], capture_output=True).returncode == 0:
            subprocess.run(['desktop-file-validate', str(menu)], check=True)
        self.cli('uninstall')
        self.assertFalse(menu.exists())
        self.assertTrue(data.exists())
        self.assertTrue((self.prefix / hdt.GAME).exists())
        self.assertEqual((self.source / hdt.DATA / 'decks.xml').read_text(), '<decks>keep me</decks>')

    def test_existing_verified_dotnet_skips_winetricks(self):
        self.fake_runtime(self.source, self.runner, [])
        self.install()
        self.assertEqual(self.runtime_mock.call_count, 1)
        self.assertNotIn('winetricks', self.runtime_mock.call_args.args[2])

    def test_resume_incomplete_install_without_recopying_game(self):
        self.runtime_mock.side_effect = None
        (self.source / 'system.reg').write_text('WINE REGISTRY Version 2\n')
        with self.assertRaises(RuntimeError):
            self.install()
        sentinel = self.prefix / 'preserved.txt'
        sentinel.write_text('do not recopy')
        self.runtime_mock.side_effect = self.fake_runtime
        with patch.object(hdt, 'clone', side_effect=AssertionError('Must not recopy')):
            self.cli('install', '--resume', '--source', str(self.source), '--proton', str(self.runner))
        self.assertEqual(sentinel.read_text(), 'do not recopy')
        self.assertEqual(hdt.metadata(self.prefix)['status'], 'ready')
        with self.assertRaisesRegex(RuntimeError, 'only for incomplete'):
            self.cli('install', '--resume', '--source', str(self.source), '--proton', str(self.runner))

    def test_refuses_overwrite_and_nested_prefix(self):
        self.install()
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.install()
        self.prefix = self.source / 'nested'
        with self.assertRaisesRegex(RuntimeError, 'separate directories'):
            self.install()

    def test_failed_update_restores_data_and_version(self):
        self.install()
        real = hdt.replace_tree
        calls = []
        def broken(source, target):
            real(source, target)
            calls.append(1)
            if len(calls) == 1:
                raise OSError('disk failure simulation')
        with patch.object(hdt, 'replace_tree', side_effect=broken):
            with self.assertRaises(OSError):
                self.cli('update')
        self.assertEqual(hdt.metadata(self.prefix)['version'], hdt.TESTED)
        self.assertEqual((self.prefix / hdt.APP / hdt.EXE).read_text(), hdt.TESTED)
        self.assertFalse((self.prefix / '.transaction').exists())

    def test_interrupted_transaction_recovery(self):
        self.install()
        backup = hdt.snapshot(self.prefix, hdt.metadata(self.prefix))
        hdt.atomic_json(self.prefix / '.transaction', {'backup': backup.name})
        target = self.prefix / hdt.APP
        target.rename(target.with_name(target.name + '.hdt-old'))
        with self.assertRaisesRegex(RuntimeError, 'Interrupted'):
            self.cli('launch')
        self.cli('recover')
        self.assertEqual((target / hdt.EXE).read_text(), hdt.TESTED)

    def test_modified_menu_preserved(self):
        self.install()
        menu = Path(hdt.metadata(self.prefix)['menu'])
        menu.write_text('user customization')
        self.cli('uninstall')
        self.assertEqual(menu.read_text(), 'user customization')

    def test_busy_prefix(self):
        with patch.object(hdt, 'idle', side_effect=RuntimeError('busy')):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                self.install()
        self.assertFalse(self.prefix.exists())


class Validation(unittest.TestCase):
    def test_process_scan_ignores_protected_native_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / '99999999'
            proc.mkdir()
            (proc / 'comm').write_text('ssh-agent\n')
            with patch.object(Path, 'read_bytes', side_effect=PermissionError):
                hdt.idle(root / 'prefix', root)
            (proc / 'comm').write_text('wineserver\n')
            with patch.object(Path, 'read_bytes', side_effect=PermissionError):
                with self.assertRaisesRegex(RuntimeError, 'Wine/game process wineserver'):
                    hdt.idle(root / 'prefix', root)

    def test_process_scan_blocks_only_matching_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / '99999999'
            proc.mkdir()
            prefix = root / 'prefix'
            (proc / 'environ').write_bytes(b'WINEPREFIX=' + os.fsencode(prefix) + b'\0')
            with self.assertRaisesRegex(RuntimeError, 'Environment is in use'):
                hdt.idle(prefix, root)
            hdt.idle(root / 'another-prefix', root)

    def test_dotnet_preparation_does_not_change_shared_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / 'shared.dll'
            shared.write_bytes(b'proton original')
            shared.chmod(0o444)
            prefix = root / 'prefix'
            for directory, name in [('Microsoft.NET/Framework64/v4.0.30319', 'diasymreader.dll'),
                                    ('system32', 'dxva2.dll')]:
                target = prefix / 'drive_c/windows' / directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(shared)
            hdt.prepare_dotnet_files(prefix)
            for target in (prefix / 'drive_c/windows').rglob('*.dll'):
                self.assertFalse(target.is_symlink())
                self.assertTrue(target.stat().st_mode & 0o200)
                target.write_bytes(b'native replacement')
            self.assertEqual(shared.read_bytes(), b'proton original')
            self.assertFalse(shared.stat().st_mode & 0o200)

    def test_archive_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['../escape', '/escape', 'Hearthstone Deck Tracker/../../escape', 'C:/escape']:
                with zipfile.ZipFile(root / 'bad.zip', 'w') as z:
                    z.writestr(name, 'bad')
                with self.assertRaises(RuntimeError):
                    hdt.extract(root / 'bad.zip', root / 'out')
            with zipfile.ZipFile(root / 'bad.zip', 'w') as z:
                entry = zipfile.ZipInfo('Hearthstone Deck Tracker/link')
                entry.external_attr = 0o120777 << 16
                z.writestr(entry, '/tmp')
            with self.assertRaises(RuntimeError):
                hdt.extract(root / 'bad.zip', root / 'out')

    def test_checksum_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            def download(url, dest):
                if dest.suffix == '.json':
                    dest.write_text(json.dumps({'tag_name': 'v1.55.6', 'assets': [{
                        'name': 'Hearthstone.Deck.Tracker-v1.55.6.zip', 'digest': 'sha256:' + '0'*64,
                        'browser_download_url': 'https://github.com/HearthSim/Hearthstone-Deck-Tracker/releases/download/v1.55.6/Hearthstone.Deck.Tracker-v1.55.6.zip'}]}))
                else:
                    dest.write_bytes(b'corrupt')
            with patch.object(hdt, 'fetch', side_effect=download):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    hdt.release('1.55.6', Path(tmp))

    def test_monitor_scale_rotation(self):
        with patch.dict(os.environ, {'HDT_DESKTOP_SIZE': ''}):
            with patch.object(hdt.subprocess, 'check_output', return_value=b'[{"width":3840,"height":2160,"scale":2,"transform":1}]'):
                self.assertEqual(hdt.size(), '1080x1920')

    def test_lock_excludes_second_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'prefix'
            with hdt.locked(prefix):
                with self.assertRaises(RuntimeError):
                    with hdt.locked(prefix):
                        pass


if __name__ == '__main__':
    unittest.main()
