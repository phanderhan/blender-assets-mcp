#!/bin/sh
# Codex stdio launcher. Never silently fall back to an unmounted host directory.
set -eu
: "${ASSET_CACHE_DIR:?ASSET_CACHE_DIR must name the dedicated mounted cache}"
case "$ASSET_CACHE_DIR" in
    /Volumes/*/cache) ;;
    *) echo "Asset cache must be /Volumes/<volume>/cache" >&2; exit 1 ;;
esac
volume=${ASSET_CACHE_DIR%/cache}
if ! /sbin/mount | /usr/bin/grep -F " on $volume (" >/dev/null || [ ! -d "$ASSET_CACHE_DIR" ]; then
    echo "Dedicated asset volume is not mounted: $volume" >&2
    exit 1
fi
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
exec /usr/local/bin/docker compose -p blender-assets-trial --project-directory "$project_dir" \
    -f "$project_dir/compose.yaml" run --rm -T server
