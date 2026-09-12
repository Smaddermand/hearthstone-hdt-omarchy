#!/usr/bin/env python3
"""Experimental per-user HDT integration. Python standard library only."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

APP = Path('drive_c/HDT/Hearthstone Deck Tracker')
EXE = 'Hearthstone Deck Tracker.exe'
DATA = Path('drive_c/users/steamuser/AppData/Roaming/HearthstoneDeckTracker')
GAME = Path('drive_c/Program Files (x86)/Hearthstone/Hearthstone.exe')
BNET = Path('drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe')
MARKER = '.hdt-omarchy.json'
API = 'https://api.github.com/repos/HearthSim/Hearthstone-Deck-Tracker/releases/'
TESTED = '1.55.6'
TESTED_PROTON = 'GE-Proton11-6-x86_64'


def fail(message):
    raise RuntimeError(message)


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def version(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        fail('Version must be MAJOR.MINOR.PATCH.')
    return tuple(map(int, value.split('.')))


def idle(prefix, proc_root=Path('/proc')):
    """Catch clients started outside our launcher too. Never print environments."""
    expected = prefix.resolve()
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            fields = (proc / 'environ').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError:
            # Protected native programs can deny environ even to their owner.
            # Only an uninspectable Wine/game process makes this check uncertain.
            try:
                name = (proc / 'comm').read_text().strip().lower()
            except FileNotFoundError:
                continue
            except PermissionError:
                fail(f'Cannot identify PID {proc.name}; cannot verify that the environment is idle.')
            if (any(word in name for word in ('wine', 'proton', 'umu', 'hearthstone', 'battle.net'))
                    or name.endswith('.exe')):
                fail(f'Cannot inspect Wine/game process {name} (PID {proc.name}). '
                     'Close that application before retrying.')
            continue
        for field in fields:
            if field.startswith(b'WINEPREFIX='):
                if Path(os.fsdecode(field.split(b'=', 1)[1])).resolve() == expected:
                    fail(f'Environment is in use (PID {proc.name}). Close HDT, Hearthstone and Battle.net first.')


@contextlib.contextmanager
def locked(prefix):
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with (prefix.parent / ('.' + prefix.name + '.hdt.lock')).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('Another installer, launcher or update is running.')
        yield


def metadata(prefix):
    path = prefix / MARKER
    if not path.is_file():
        fail('This is not an environment managed by this installer.')
    result = json.loads(path.read_text())
    if result.get('schema') != 1 or result.get('status') != 'ready':
        fail('Installation is incomplete. Inspect install.log in the destination.')
    if (prefix / '.transaction').exists():
        fail('Interrupted update: run recover before launching or updating.')
    return result


def fetch(url, dest):
    request = urllib.request.Request(url, headers={'User-Agent': 'hearthstone-hdt-omarchy/0.1'})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open('wb') as out:
        shutil.copyfileobj(response, out)


def release(requested, work):
    endpoint = 'latest' if requested == 'latest' else 'tags/v' + requested
    if requested != 'latest':
        version(requested)
    fetch(API + endpoint, work / 'release.json')
    info = json.loads((work / 'release.json').read_text())
    tag = info['tag_name'].removeprefix('v')
    version(tag)
    if info.get('prerelease') or info.get('draft') or (requested != 'latest' and requested != tag):
        fail('Expected the requested stable release.')
    name = f'Hearthstone.Deck.Tracker-v{tag}.zip'
    asset = next((a for a in info['assets'] if a['name'] == name), None)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
        fail('Official release has no SHA-256 digest. Refusing an unverified download.')
    url = f'https://github.com/HearthSim/Hearthstone-Deck-Tracker/releases/download/v{tag}/{name}'
    if asset['browser_download_url'] != url:
        fail('Unexpected release download URL.')
    fetch(url, work / 'release.zip')
    if 'sha256:' + digest(work / 'release.zip') != asset['digest']:
        fail('Release checksum mismatch.')
    extract(work / 'release.zip', work / 'unpacked')
    return tag, work / 'unpacked/Hearthstone Deck Tracker'


def extract(archive, dest):
    with zipfile.ZipFile(archive) as z:
        seen = set()
        total = 0
        for entry in z.infolist():
            p = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (p.is_absolute() or '..' in p.parts or '\\' in entry.filename
                    or ':' in entry.filename or not p.parts
                    or p.parts[0] != 'Hearthstone Deck Tracker'
                    or stat.S_ISLNK(mode) or entry.filename.casefold() in seen):
                fail('Unsafe or unexpected ZIP entry.')
            seen.add(entry.filename.casefold())
            total += entry.file_size
            if total > 2 * 1024**3:
                fail('Unpacked release exceeds 2 GiB.')
        z.extractall(dest)
    if not (dest / 'Hearthstone Deck Tracker' / EXE).is_file():
        fail('Archive contains no HDT executable.')


def runtime(prefix, proton, args, log=None):
    env = dict(os.environ, WINEPREFIX=str(prefix), PROTONPATH=str(proton),
               GAMEID='umu-battlenet', PROTON_VERB='run', PROTON_USE_XALIA='0',
               PROTON_LOG='0')
    subprocess.run(['umu-run', *map(str, args)], env=env, check=True,
                   stdout=log, stderr=subprocess.STDOUT if log else None)


def clone(source, dest):
    # Copy links without following them. cp creates independent files, never hardlinks.
    subprocess.run(['cp', '-a', '--reflink=auto', '--', str(source) + '/.', str(dest)], check=True)
    for p in dest.rglob('*'):
        if p.is_symlink() and p.resolve().is_relative_to(source):
            target = dest / p.resolve().relative_to(source)
            p.unlink()
            p.symlink_to(target)


def prepare_dotnet_files(prefix):
    """Native .NET replaces framework and system DLLs; never write through Proton links."""
    root = prefix / 'drive_c/windows'
    if root.is_symlink():
        fail('Linked Windows directory is unsupported.')
    for current, dirs, files in os.walk(root, followlinks=False):
        folder = Path(current)
        if any((folder / name).is_symlink() for name in dirs):
            fail('Linked Windows subdirectory is unsupported.')
        for name in files:
            path = folder / name
            if path.is_symlink():
                local = path.with_name(path.name + '.local-' + uuid.uuid4().hex)
                try:
                    shutil.copy2(path, local)
                    local.chmod(local.stat().st_mode | stat.S_IWUSR)
                    local.replace(path)
                finally:
                    local.unlink(missing_ok=True)
            elif path.is_file():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)


def verify_dotnet(prefix):
    registry = (prefix / 'system.reg').read_text(errors='replace')
    key = r'Software\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full'
    section = re.search(r'^\[' + re.escape(key) + r'\][^\n]*\n(.*?)(?=^\[|\Z)',
                        registry, re.M | re.S)
    release = re.search(r'^"Release"=dword:([0-9a-f]+)$', section[1], re.M) if section else None
    if not release or int(release[1], 16) < 528040:
        fail('Microsoft .NET 4.8 installation could not be verified. Inspect install.log; destination remains incomplete.')


def configure(prefix):
    folder = prefix / DATA
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'config.xml'
    tree = ET.parse(path) if path.exists() else ET.ElementTree(ET.Element('Config'))
    for key, value in {'SaveInAppData': 'true', 'HearthstoneDirectory': r'C:\Program Files (x86)\Hearthstone',
                       'StartHearthstoneWithHDT': 'false', 'CloseWithHearthstone': 'false',
                       'StartWithWindows': 'false'}.items():
        node = tree.getroot().find(key)
        if node is None:
            node = ET.SubElement(tree.getroot(), key)
        node.text = value
    tree.write(path, encoding='utf-8', xml_declaration=True)


def desktop_quote(value):
    # freedesktop Exec quoting, including the preceding string-unescape layer.
    value = str(value)
    if any(c in value for c in '\n\r\0'):
        fail('Unsupported newline in desktop path.')
    value = value.replace('%', '%%')
    for old, new in [('\\', '\\\\\\\\'), ('"', '\\\\"'), ('`', '\\\\`'), ('$', '\\\\$')]:
        value = value.replace(old, new)
    return '"' + value + '"'


def menu(prefix, info):
    path = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications/hdt-omarchy.desktop'
    if path.exists() and info.get('menu') != str(path):
        fail(f'Menu entry already exists: {path}')
    tool = prefix / '.hdt-tool.py'
    shutil.copy2(Path(__file__).resolve(), tool)
    body = ('[Desktop Entry]\nType=Application\nName=Hearthstone Deck Tracker (Omarchy)\n'
            'Comment=Launch HDT, then use Start Hearthstone\nIcon=applications-games\n'
            f'Exec=/usr/bin/python3 {desktop_quote(tool)} --prefix {desktop_quote(prefix)} launch\n'
            'Terminal=false\nCategories=Game;\nKeywords=HDT;HSReplay;Hearthstone;\nStartupNotify=false\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    info['menu'] = str(path)
    info['menu_sha256'] = digest(path)
    atomic_json(prefix / MARKER, info)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(path.parent)], check=False)


def install(args, prefix):
    source = args.source.expanduser().resolve()
    proton = args.proton.expanduser().resolve()
    previous = None
    if args.resume:
        marker = prefix / MARKER
        if not marker.is_file():
            fail('Resume requires an incomplete installation created by this tool.')
        previous = json.loads(marker.read_text())
        if previous.get('schema') != 1 or previous.get('status') != 'installing':
            fail('Resume is allowed only for incomplete installations.')
        if previous.get('proton') != str(proton) or previous.get('version') != args.version:
            fail('Resume with the same --proton and --version used originally.')
    elif prefix.exists():
        fail('Destination already exists; choose a new --prefix or use install --resume for an incomplete installation.')
    if prefix.is_relative_to(source) or source.is_relative_to(prefix):
        fail('Source and destination must be separate directories.')
    for f in [source / GAME, source / BNET, proton / 'proton', proton / 'protonfixes/winetricks']:
        if not f.is_file():
            fail(f'Missing requirement: {f}')
    if not shutil.which('umu-run'):
        fail('Install umu-launcher through Omarchy first.')
    for relative in [DATA, APP]:
        root = source / relative
        for item in [root, *root.parents]:
            if item == source:
                break
            if item.is_symlink():
                fail('Linked tracker/profile directories are unsupported; choose a self-contained source.')
        if root.exists() and any(item.is_symlink() for item in root.rglob('*')):
            fail('Linked tracker/profile files are unsupported in this first installer.')
    idle(source)
    with tempfile.TemporaryDirectory(prefix='hdt-download-') as tmp:
        tag, app = release(args.version, Path(tmp))
        if previous is None:
            prefix.mkdir(mode=0o700)
            info = {'schema': 1, 'status': 'installing', 'version': tag, 'proton': str(proton)}
            atomic_json(prefix / MARKER, info)
            print('Copying Battle.net environment. Keep the source closed until copying finishes.', flush=True)
            clone(source, prefix)
            os.chmod(prefix, 0o700)
            atomic_json(prefix / MARKER, info)
        else:
            info = previous
        prepare_dotnet_files(prefix)
        print('Installing Microsoft .NET 4.8 in the copy; this can take several minutes.', flush=True)
        with (prefix / 'install.log').open('a') as log:
            try:
                verify_dotnet(prefix)
            except (RuntimeError, FileNotFoundError):
                runtime(prefix, proton, ['winetricks', '-q', 'dotnet48'], log)
            else:
                print('Microsoft .NET 4.8 is already verified; keeping it.', flush=True)
            runtime(prefix, proton, [prefix / 'drive_c/windows/system32/winecfg.exe', '-v', 'win10'], log)
        verify_dotnet(prefix)
        if (prefix / APP).exists():
            (prefix / APP).rename(prefix / '.hdt-source-app')
        (prefix / APP).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(app, prefix / APP)
        configure(prefix)
        info['status'] = 'ready'
        atomic_json(prefix / MARKER, info)
        if not args.no_menu:
            menu(prefix, info)
        print(f'Installed HDT {tag} at {prefix}. Use launch, then Start Hearthstone inside HDT.')


def snapshot(prefix, info):
    backup = prefix / '.hdt-backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    shutil.copytree(prefix / APP, backup / 'app', symlinks=True)
    if (prefix / DATA).exists():
        shutil.copytree(prefix / DATA, backup / 'data', symlinks=True)
    atomic_json(backup / 'metadata.json', info)
    return backup


def replace_tree(source, target):
    stage = target.with_name(target.name + '.hdt-stage')
    old = target.with_name(target.name + '.hdt-old')
    if stage.exists() or old.exists():
        fail(f'Unfinished replacement at {target}; run recover.')
    if source.exists():
        shutil.copytree(source, stage, symlinks=True)
    if target.exists():
        target.rename(old)
    try:
        if stage.exists():
            stage.rename(target)
    except BaseException:
        if old.exists():
            old.rename(target)
        raise
    if old.exists():
        shutil.rmtree(old)


def restore(prefix, backup):
    info = json.loads((backup / 'metadata.json').read_text())
    for item, target in [('app', prefix / APP), ('data', prefix / DATA)]:
        # Recovery may follow termination between directory renames.
        for suffix in ['.hdt-stage', '.hdt-old']:
            leftover = target.with_name(target.name + suffix)
            if leftover.exists():
                shutil.rmtree(leftover)
        replace_tree(backup / item, target)
    atomic_json(prefix / MARKER, info)


def transaction(prefix, info, action):
    backup = snapshot(prefix, info)
    atomic_json(prefix / '.transaction', {'backup': backup.name})
    try:
        action()
    except BaseException:
        restore(prefix, backup)
        (prefix / '.transaction').unlink()
        raise
    (prefix / '.transaction').unlink()
    print(f'Backup retained: {backup.name}')


def update(args, prefix):
    info = metadata(prefix)
    with tempfile.TemporaryDirectory(prefix='hdt-update-') as tmp:
        tag, app = release(args.version, Path(tmp))
        if version(tag) <= version(info['version']):
            print('No newer version selected. Use rollback to restore a backup.')
            return
        def apply():
            replace_tree(app, prefix / APP)
            info['version'] = tag
            atomic_json(prefix / MARKER, info)
        transaction(prefix, info.copy(), apply)
        print(f'Updated to {tag}. Proton and .NET unchanged.')


def backup_path(prefix, name):
    if not re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}', name):
        fail('Use a backup ID printed by backups.')
    path = prefix / '.hdt-backups' / name
    if path.is_symlink() or not (path / 'metadata.json').is_file():
        fail('Backup not found.')
    return path


def size():
    selected = os.environ.get('HDT_DESKTOP_SIZE')
    if not selected:
        try:
            monitors = json.loads(subprocess.check_output(['hyprctl', 'monitors', '-j'], timeout=3))
            m = next((m for m in monitors if m.get('focused')), monitors[0])
            w, h = m['width'], m['height']
            if m.get('transform', 0) % 2:
                w, h = h, w
            selected = f"{round(w / m.get('scale', 1))}x{round(h / m.get('scale', 1))}"
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            selected = '1920x1080'
    if not re.fullmatch(r'[1-9]\d{0,4}x[1-9]\d{0,4}', selected):
        fail('HDT_DESKTOP_SIZE must be WIDTHxHEIGHT.')
    return selected


def launch(args, prefix):
    info = metadata(prefix)
    proton = Path(info['proton'])
    for file in [prefix / APP / EXE, proton / 'proton']:
        if not file.is_file():
            fail(f'Missing {file}')
    cmd = ('@echo off\n"C:\\windows\\system32\\winecfg.exe" -v win10\n'
           'if errorlevel 1 exit /b 1\ncd /d "C:\\HDT\\Hearthstone Deck Tracker"\n'
           '"Hearthstone Deck Tracker.exe"\nexit /b %ERRORLEVEL%\n')
    (prefix / 'drive_c/hdt-launch.cmd').write_bytes(cmd.replace('\n', '\r\n').encode())
    log = prefix / 'launcher.log'
    if log.exists():
        log.replace(prefix / 'launcher.previous.log')
    invocation = ['C:\\windows\\system32\\cmd.exe', '/c', 'C:\\hdt-launch.cmd']
    if not args.no_virtual_desktop:
        invocation = [str(prefix / 'drive_c/windows/explorer.exe'), '/desktop=HearthstoneHDT,' + size(), *invocation]
    with log.open('w') as out:
        runtime(prefix, proton, invocation, out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / 'Games/hearthstone-hdt-omarchy')
    sub = parser.add_subparsers(dest='command', required=True)
    ins = sub.add_parser('install')
    ins.add_argument('--source', type=Path, default=Path.home() / 'Games/battlenet')
    ins.add_argument('--proton', type=Path, default=Path.home() / '.local/share/Steam/compatibilitytools.d' / TESTED_PROTON)
    ins.add_argument('--version', default=TESTED)
    ins.add_argument('--no-menu', action='store_true')
    ins.add_argument('--resume', action='store_true', help='Retry dependency setup in an incomplete installation')
    la = sub.add_parser('launch')
    la.add_argument('--no-virtual-desktop', action='store_true')
    up = sub.add_parser('update')
    up.add_argument('--version', default='latest')
    rb = sub.add_parser('rollback')
    rb.add_argument('backup')
    for name in ['status', 'backups', 'recover', 'menu', 'uninstall']:
        sub.add_parser(name)
    args = parser.parse_args(argv)
    prefix = args.prefix.expanduser().resolve()
    if prefix == Path.home() or prefix == Path('/'):
        fail('Choose a dedicated environment directory.')
    if args.command == 'status':
        print(json.dumps(metadata(prefix), indent=2))
        return
    with locked(prefix):
        idle(prefix)
        if args.command == 'install':
            install(args, prefix)
        elif args.command == 'recover':
            journal = json.loads((prefix / '.transaction').read_text())
            restore(prefix, backup_path(prefix, journal['backup']))
            (prefix / '.transaction').unlink()
            print('Interrupted transaction restored from its backup.')
        else:
            info = metadata(prefix)
            if args.command == 'launch':
                launch(args, prefix)
            elif args.command == 'update':
                update(args, prefix)
            elif args.command == 'rollback':
                backup = backup_path(prefix, args.backup)
                transaction(prefix, info, lambda: restore(prefix, backup))
                print('Application and data restored. A backup of the pre-rollback state was retained.')
            elif args.command == 'backups':
                for item in sorted((prefix / '.hdt-backups').glob('*/metadata.json')):
                    print(item.parent.name, json.loads(item.read_text())['version'])
            elif args.command == 'menu':
                menu(prefix, info)
            elif args.command == 'uninstall':
                path = Path(info['menu']) if info.get('menu') else None
                if path and path.is_file() and digest(path) == info.get('menu_sha256'):
                    path.unlink()
                elif path and path.exists():
                    print('Menu entry was modified; leaving it in place.')
                (prefix / '.hdt-tool.py').unlink(missing_ok=True)
                info.pop('menu', None)
                info.pop('menu_sha256', None)
                atomic_json(prefix / MARKER, info)
                print(f'Integration removed. Game, tracker, settings and backups retained at {prefix}.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
