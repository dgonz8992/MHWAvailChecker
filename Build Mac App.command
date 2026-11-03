#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [ ! -x .venv-build/bin/python ]; then
    .venv-modern/bin/python -m venv .venv-build
fi
.venv-build/bin/python -m pip install 'pyinstaller==6.22.3'
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
bash packaging/build_icon.sh
.venv-build/bin/python -m PyInstaller --noconfirm --clean 'MHW Scheduler.spec'
ditto -c -k --sequesterRsrc --keepParent \
    'dist/MHW Scheduler.app' 'dist/MHW Scheduler.zip'
echo 'Ready: dist/MHW Scheduler.app'
echo 'Share: dist/MHW Scheduler.zip'
