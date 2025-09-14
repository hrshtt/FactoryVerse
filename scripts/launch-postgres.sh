#!/usr/bin/env bash
set -euo pipefail

# Simple launcher for a local PostgreSQL container suitable for load_raw_snapshots.py
# Usage:
#   ./scripts/launch-postgres.sh
# Then run the loader using the printed DSN, e.g.:
#   python -m FactoryVerse.services.duckdb.load_raw_snapshots /path/to/snaps --dsn "$(./scripts/launch-postgres.sh --print-dsn)"

CONTAINER_NAME=${CONTAINER_NAME:-factoryverse-pg}
IMAGE=${IMAGE:-kartoza/postgis:latest}
PORT=${PORT:-5432}
DB=${DB:-factoryverse}
PG_USER=${PG_USER:-factoryverse}
PG_PASSWORD=${PG_PASSWORD:-factoryverse}
VOLUME_NAME=${VOLUME_NAME:-factoryverse_pg_data}

print_dsn() {
  printf "postgresql://%s:%s@localhost:%s/%s\n" "$PG_USER" "$PG_PASSWORD" "$PORT" "$DB"
}

if [[ ${1:-} == "--print-dsn" ]]; then
  print_dsn
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required but not found in PATH" >&2
  exit 1
fi

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"
}

start_container() {
  echo "Starting PostgreSQL container: $CONTAINER_NAME"
  docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -e POSTGRES_USER="$PG_USER" \
    -e POSTGRES_DB="$DB" \
    -v "$VOLUME_NAME":/var/lib/postgresql/data \
    -p "$PORT":5432 \
    "$IMAGE" >/dev/null
}

reset_container_and_volume() {
  if container_exists; then
    if container_running; then
      echo "Stopping '$CONTAINER_NAME'..."
      docker stop "$CONTAINER_NAME" >/dev/null || true
    fi
    echo "Removing container '$CONTAINER_NAME'..."
    docker rm "$CONTAINER_NAME" >/dev/null || true
  fi
  echo "Removing volume '$VOLUME_NAME' (data will be lost)..."
  docker volume rm "$VOLUME_NAME" >/dev/null || true
  echo "Recreating volume '$VOLUME_NAME'..."
  docker volume create "$VOLUME_NAME" >/dev/null
  start_container
}

# Stop container option
if [[ ${1:-} == "--stop" ]]; then
  if container_exists; then
    if container_running; then
      echo "Stopping '$CONTAINER_NAME'..."
      docker stop "$CONTAINER_NAME" >/dev/null
      echo "Container stopped."
    else
      echo "Container '$CONTAINER_NAME' is already stopped."
    fi
  else
    echo "Container '$CONTAINER_NAME' not found."
  fi
  exit 0
fi

# Restart container option
if [[ ${1:-} == "--restart" ]]; then
  if container_exists; then
    echo "Restarting '$CONTAINER_NAME'..."
    docker restart "$CONTAINER_NAME" >/dev/null
  else
    echo "Container '$CONTAINER_NAME' not found. Starting a new one..."
    start_container
  fi
fi

# Reset container and volume (destroys all data!)
if [[ ${1:-} == "--reset" || ${1:-} == "--recreate" ]]; then
  echo "Resetting PostgreSQL container and data volume. This will delete all data."
  reset_container_and_volume
fi

if container_exists; then
  if container_running; then
    echo "Container '$CONTAINER_NAME' already running."
  else
    echo "Container '$CONTAINER_NAME' exists but is stopped. Starting it..."
    docker start "$CONTAINER_NAME" >/dev/null
  fi
else
  start_container
fi

echo "Waiting for PostgreSQL to become ready..."
for i in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -h 127.0.0.1 -U "$PG_USER" -d "$DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec "$CONTAINER_NAME" pg_isready -h 127.0.0.1 -U "$PG_USER" -d "$DB" >/dev/null 2>&1; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

DSN="$(print_dsn)"
echo "PostgreSQL is ready."
echo "DSN: $DSN"
echo
echo "Next:"
echo "  # Either rely on the loader's default DSN (matches this container)"
echo "  python -m FactoryVerse.services.duckdb.load_raw_snapshots /path/to/snaps"
echo "  # Or pass the DSN explicitly"
echo "  python -m FactoryVerse.services.duckdb.load_raw_snapshots /path/to/snaps --dsn \"$DSN\""


