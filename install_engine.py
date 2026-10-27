"""Install pinned CPU engine + SMALL SMOKE-TEST model; not a release-quality net.
Usage: python install_engine.py /absolute/runtime/path
Use KATAGO_MODEL to select a stronger validated net before deployment.
"""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ASSETS = (
 ('engine.zip','https://github.com/lightvector/KataGo/releases/download/v1.16.3/katago-v1.16.3-eigen-linux-x64.zip','8b617286e3fc778e69feeae470c994efaca08865a3edb497a5d41a60be36c6a8'),
 ('smoke-model.bin.gz','https://raw.githubusercontent.com/lightvector/KataGo/v1.16.3/cpp/tests/models/g170-b6c96-s175395328-d26788732.bin.gz','f5d32604e3675c480c7c8f6aa579a1ea857135628a0afccc8fa56330fbacd38d'),
)


STRONG_MODEL = (
 "strong-model.bin.gz",
 "https://github.com/lightvector/KataGo/releases/download/v1.12.0/b18c384nbt-uec.bin.gz",
 "dd6a372c5496267347bd7c977b617f730f4d9198a2a075cc3d1a1047b4da5c4c",
)


def install(destination, strong=False):
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
    assets = (ASSETS[0], STRONG_MODEL if strong else ASSETS[1])
    for name,url,checksum in assets:
        target=root/name
        data=target.read_bytes() if target.exists() else urllib.request.urlopen(url,timeout=60).read()
        if hashlib.sha256(data).hexdigest()!=checksum:
            raise RuntimeError('Checksum mismatch for '+name)
        target.write_bytes(data)
    with zipfile.ZipFile(root/'engine.zip') as archive:
        for info in archive.infolist():
            if not (root/'bundle'/info.filename).resolve().is_relative_to(root/'bundle'):
                raise RuntimeError('Unsafe archive path')
        archive.extractall(root/'bundle')
    app=root/'bundle'/'katago';app.chmod(0o755)
    subprocess.run([str(app),'--appimage-extract'],cwd=root,stdout=subprocess.DEVNULL,check=True)
    binary=root/'squashfs-root'/'AppRun'
    print('KATAGO_BINARY='+str(binary))
    print('KATAGO_MODEL='+str(root/('strong-model.bin.gz' if strong else 'smoke-model.bin.gz')))
    print('Validate accuracy, latency, and memory before release.' if strong else 'Smoke-test model only. Validate a stronger net before release.')


if __name__=='__main__':
    if len(sys.argv) not in (2,3) or (len(sys.argv)==3 and sys.argv[2]!='--strong'):raise SystemExit('Usage: python install_engine.py /absolute/runtime/path [--strong]')
    install(sys.argv[1], strong='--strong' in sys.argv)
