#!/usr/bin/env bash
set -euo pipefail

# The directory containing your Lua files
WATCH_DIR="./src/factorio/factorio_verse"

# The command that reloads inside the container
HOT_RELOAD_CMD="(docker compose ps -q factorio_0 | grep -q . || ./run-envs.sh start -n 1) && docker compose exec factorio_0 sh -lc 'sh /opt/factorio/scenarios/factorio_verse/hot-reload-scripts.sh'"

# Debounce window (e.g., 500ms). In practice 300–800ms feels good for editors that save temp files.
# Increased to 1000ms to reduce rapid-fire reloads
DEBOUNCE_MS=1000

# Check if the watch directory exists
if [[ ! -d "$WATCH_DIR" ]]; then
  echo "Error: Watch directory '$WATCH_DIR' does not exist!"
  exit 1
fi

echo "Watching for .lua file changes in: $WATCH_DIR"
echo "Will run luacheck and hot reload on changes..."

# Run watchexec: watch for .lua changes, run luacheck first, then hot reload
exec watchexec \
  --watch "$WATCH_DIR" \
  --exts lua \
  --debounce "${DEBOUNCE_MS}ms" \
  --restart \
  --clear \
  --ignore '.git/**' \
  --ignore '**/.DS_Store' \
  -- \
  bash -c "
    echo '[watch] change detected: running luacheck...'
    cd '$WATCH_DIR'
    luacheck -qqq . 2>/dev/null
    if [ \$? -le 1 ]; then
      echo '[watch] luacheck passed ✔ — hot reloading...'
      cd - > /dev/null
      $HOT_RELOAD_CMD
      echo '[watch] done.'
    else
      echo '[watch] luacheck failed ✖ — syntax errors found, not reloading.'
    fi
  "