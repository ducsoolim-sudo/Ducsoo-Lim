"""Install checksum-pinned official KataGo assets for the test image only."""
import hashlib
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile
import io

ENGINE_URL = 'https://github.com/lightvector/KataGo/releases/download/v1.16.3/katago-v1.16.3-eigen-linux-x64.zip'
ENGINE_SHA = '8b617286e3fc778e69feeae470c994efaca08865a3edb497a5d41a60be36c6a8'
MODEL_URL = 'https://github.com/lightvector/KataGo/releases/download/v1.3/g170e-b10c128-s1141046784-d204142634.txt.gz'
MODEL_SHA = '3d8a24697ba25fe4da39af4c2b6bd405907b0ad8295322f5a550fa2d8fe4a2f4'


def download(url, digest):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Official AI asset checksum mismatch')
    return data


def install(destination):
    destination.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(download(ENGINE_URL, ENGINE_SHA)))
    binary = destination / 'katago.AppImage'
    binary.write_bytes(archive.read('katago'))
    binary.chmod(0o755)
    (destination / 'README-KataGo.txt').write_bytes(archive.read('README.txt'))
    subprocess.run([str(binary.resolve()), '--appimage-extract'], cwd=destination,
                   check=True, stdout=subprocess.DEVNULL, timeout=120)
    binary.unlink()
    (destination / 'model.txt.gz').write_bytes(download(MODEL_URL, MODEL_SHA))
    license_url = 'https://raw.githubusercontent.com/lightvector/KataGo/v1.16.3/LICENSE'
    with urllib.request.urlopen(license_url, timeout=30) as response:
        (destination / 'LICENSE-KataGo.txt').write_bytes(response.read())
    (destination / 'MODEL-SOURCE.txt').write_text(MODEL_URL + '\nSHA256 ' + MODEL_SHA +
        '\ng170 model: CC0. https://katagotraining.org/network_license/\n')
    subprocess.run([str(destination / 'squashfs-root/AppRun'), 'version'], check=True, timeout=15)


if __name__ == '__main__':
    install(Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/go13-ai').resolve())
