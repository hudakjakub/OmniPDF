"""Build the Windows portable executable, installer and checksums."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app_info import VERSION
from updates import INSTALLER_NAME


def validate_version(version, tag=None):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("VERSION must be a stable semantic version")
    if any(int(part) > 65535 for part in version.split('.')):
        raise ValueError("Windows version components must not exceed 65535")
    if tag is not None and tag != f"v{version}":
        raise ValueError("Tag must match VERSION exactly")
    return tuple(map(int, version.split('.'))) + (0,)


def version_metadata(version):
    parts = validate_version(version)
    return f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription', 'Omni PDF'), StringStruct('FileVersion', '{version}'), StringStruct('ProductName', 'Omni PDF'), StringStruct('ProductVersion', '{version}')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
'''


def build_environment():
    # Host tools can expose incompatible ICU DLLs; only use Python and Windows paths.
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    environment = dict(os.environ)
    environment['PATH'] = os.pathsep.join(map(str, (Path(sys.executable).parent,
        Path(sys.base_prefix), windows / 'System32', windows)))
    return environment


def main():
    validate_version(VERSION, os.environ.get('RELEASE_TAG') or None)
    if sys.argv[1:] == ['--validate']:
        return
    if sys.platform != 'win32':
        raise SystemExit('Windows is required for the build')
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtWidgets import QApplication

    os.chdir(ROOT)
    iscc = Path(os.environ.get('ISCC', r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'))
    if not iscc.is_file() and 'ISCC' not in os.environ:
        iscc = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Inno Setup 7' / 'ISCC.exe'
    if not iscc.is_file():
        raise FileNotFoundError(f'Inno Setup compiler not found: {iscc}')
    build = ROOT / 'build' / 'release-inputs'
    build.mkdir(parents=True, exist_ok=True)
    licenses = build / 'licenses'
    if licenses.resolve() != ROOT / 'build' / 'release-inputs' / 'licenses':
        raise ValueError('Build license directory must stay inside the workspace')
    if licenses.exists():
        shutil.rmtree(licenses)
    licenses.mkdir()
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
    inno_license = iscc.parent / 'license.txt'
    if inno_license.is_file():
        shutil.copy2(inno_license, licenses / 'Inno-Setup-LICENSE.txt')
    for distribution in ('PyMuPDF', 'PySide6-Essentials', 'shiboken6', 'pyinstaller'):
        package = importlib.metadata.distribution(distribution)
        for entry in package.files or ():
            path = str(entry).replace('\\', '/')
            if ('.dist-info/' in path and any(word in path.lower() for word in ('license', 'copying'))) or '/licenses/' in path.lower():
                destination = licenses / distribution / Path(*entry.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package.locate_file(entry), destination)
    dotnet = shutil.which('dotnet')
    if not dotnet:
        raise FileNotFoundError('The .NET 10 SDK is required to build Windows printing')
    native_printer = build / 'windows_print'
    native_env = build_environment()
    native_env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    subprocess.run([dotnet, 'publish', str(ROOT / 'windows_print' / 'WindowsPrint.csproj'),
                    '-c', 'Release', '-p:Platform=x64', '--self-contained', 'true',
                    '-o', str(native_printer), '--nologo'], check=True, env=native_env)
    assets = json.loads((ROOT / 'windows_print' / 'obj' / 'project.assets.json').read_text(encoding='utf-8'))
    for library in assets['libraries'].values():
        if library.get('type') != 'package':
            continue
        for folder in assets['packageFolders']:
            package = Path(folder) / library['path']
            if package.is_dir():
                for item in package.iterdir():
                    if item.is_file() and item.name.lower().startswith(('license', 'notice')):
                        target = licenses / 'Windows-print' / library['path'] / item.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
                break
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    icon = QIcon(str(ROOT / 'assets' / 'omni.svg'))
    if not icon.pixmap(256, 256).save(str(build / 'omni.ico'), 'ICO'):
        raise RuntimeError('Could not render the application icon')
    (build / 'version.txt').write_text(version_metadata(VERSION), encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                    '--name', 'OmniPDF', '--specpath', str(build), '--icon', str(build / 'omni.ico'), '--version-file', str(build / 'version.txt'),
                    *sum((['--add-data', f'{ROOT / name};{dest}'] for name, dest in
                          [('assets', 'assets'), ('windows_ocr.ps1', '.'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'),
                           (str(native_printer), 'windows_print'),
                           (str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / 'qtbase_sk.qm'), 'translations'),
                           (str(licenses), 'licenses')]), []),
                    'main.py'], check=True, env=build_environment())
    portable = release / 'OmniPDF-windows-x64.exe'
    shutil.copy2(ROOT / 'dist' / 'OmniPDF.exe', portable)
    subprocess.run([str(iscc), f'/DAppVersion={VERSION}', str(ROOT / 'packaging' / 'installer.iss')], check=True)
    installer = release / INSTALLER_NAME
    # Older installed updaters require the versioned installer name.
    legacy_installer = release / f'OmniPDF-Setup-{VERSION}-windows-x64.exe'
    shutil.copy2(installer, legacy_installer)
    (release / 'SHA256SUMS.txt').write_text(''.join(
        f'{hashlib.file_digest(path.open("rb"), "sha256").hexdigest()}  {path.name}\n'
        for path in (portable, installer, legacy_installer)), encoding='ascii')


if __name__ == '__main__':
    main()
