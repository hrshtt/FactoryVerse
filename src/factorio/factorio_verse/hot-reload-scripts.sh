#!/bin/sh

set -eu

# This script copies all .lua files from the scenario directory (where this
# script resides) into /factorio/temp/currently-playing/ inside the container,
# preserving the directory structure.

DEST_DIR="/factorio/temp/currently-playing"

# Move to the directory where the script lives (scenario root)
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || echo ".")
cd "$SCRIPT_DIR"

echo "Syncing *.lua files from $(pwd) to $DEST_DIR ..."

# Ensure destination exists
mkdir -p "$DEST_DIR"

# Find and copy .lua files while preserving folder structure
# Works with busybox/posix utils available in most minimal containers
files_copied=0
find . -type f -name '*.lua' | while IFS= read -r relpath; do
  # Strip leading ./ to build proper destination paths
  case "$relpath" in
    ./*) relpath=${relpath#./} ;;
  esac

  dest_path="$DEST_DIR/$relpath"
  dest_dir=$(dirname "$dest_path")

  mkdir -p "$dest_dir"
  cp "$relpath" "$dest_path"
  echo "Copied: $relpath -> $dest_path"
  files_copied=$((files_copied + 1))
done

echo "Done. ${files_copied} *.lua files synced to $DEST_DIR."

rcon '/reload_scripts'

