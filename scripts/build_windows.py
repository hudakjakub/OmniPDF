"""Build the Windows portable executable."""
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
from struct import pack
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from omnipdf.app_info import VERSION
from omnipdf.updates import PORTABLE_NAME


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


def write_windows_icon(source, destination):
    from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
    from PySide6.QtGui import QIcon

    sizes = (16, 20, 24, 28, 32, 36, 40, 48, 56, 60, 64, 72, 84, 96, 128, 256)
    icon = QIcon(str(source))
    directory = bytearray(pack('<3H', 0, 1, len(sizes)))
    images = bytearray()
    offset = len(directory) + 16 * len(sizes)
    for size in sizes:
        # Render from the vector at each size to retain antialiased strokes.
        pixmap = icon.pixmap(QSize(size * 3, size * 3), 1.0)
        pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not pixmap.save(buffer, 'PNG'):
            raise RuntimeError(f'Could not render the {size}px application icon')
        image = buffer.data()
        dimension = size % 256  # ICO encodes 256 with a zero byte.
        directory.extend(pack('<4B2H2I', dimension, dimension, 0, 0, 1, 32,
                              image.size(), offset + len(images)))
        images.extend(bytes(image))
    destination.write_bytes(directory + images)


def main():
    validate_version(VERSION, os.environ.get('RELEASE_TAG') or None)
    if sys.argv[1:] == ['--validate']:
        return
    if sys.platform != 'win32':
        raise SystemExit('Windows is required for the build')
    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtWidgets import QApplication

    os.chdir(ROOT)
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
    write_windows_icon(ROOT / 'omnipdf' / 'assets' / 'omni.svg', build / 'omni.ico')
    (build / 'version.txt').write_text(version_metadata(VERSION), encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                    '--name', Path(PORTABLE_NAME).stem, '--distpath', str(release), '--specpath', str(build),
                    '--paths', str(ROOT), '--icon', str(build / 'omni.ico'), '--version-file', str(build / 'version.txt'),
                    *sum((['--add-data', f'{ROOT / name};{dest}'] for name, dest in
                          [('omnipdf/assets', 'omnipdf/assets'), ('omnipdf/windows_ocr.ps1', 'omnipdf'), ('LICENSE', '.'), ('docs/THIRD_PARTY_NOTICES.md', 'docs'),
                           (str(native_printer), 'windows_print'),
                           (str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / 'qtbase_sk.qm'), 'omnipdf/translations'),
                           (str(licenses), 'licenses')]), []),
                    'omnipdf/main.py'], check=True, env=build_environment())


if __name__ == '__main__':
    main()
