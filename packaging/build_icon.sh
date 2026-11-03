#!/bin/bash
# Convert the existing logo into all of the standard macOS icon sizes.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
sips -s format png -z 80 80 'logo/MHW-logo-no-text.webp' \
    --out 'logo/MHW-mark.png' >/dev/null
iconset='build/MHW Scheduler.iconset'
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -s format png -z "$size" "$size" 'logo/MHW-logo-no-text.webp' \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    retina=$((size * 2))
    sips -s format png -z "$retina" "$retina" 'logo/MHW-logo-no-text.webp' \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o 'logo/MHW Scheduler.icns'
