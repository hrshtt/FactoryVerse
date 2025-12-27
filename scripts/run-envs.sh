#!/bin/bash

# FactoryVerse Server Management Script
# Manages Factorio servers with automatic mod deployment and client synchronization

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ============================================================================
# CONFIGURATION DETECTION
# ============================================================================

# Detect platform and emulator
if [ "$(uname -m)" = "arm64" ] || [ "$(uname -m)" = "aarch64" ]; then
    export EMULATOR="/bin/box64"
    export DOCKER_PLATFORM="linux/arm64"
else
    export EMULATOR=""
    export DOCKER_PLATFORM="linux/amd64"
fi

# Detect local Factorio mod directory
if [[ "$OSTYPE" == "darwin"* ]]; then
    LOCAL_MODS_PATH="$HOME/Library/Application Support/Factorio/mods"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    LOCAL_MODS_PATH="$HOME/.factorio/mods"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    LOCAL_MODS_PATH="$USERPROFILE/AppData/Roaming/Factorio/mods"
fi

# Verify paths exist
if [ ! -d "$LOCAL_MODS_PATH" ]; then
    echo "❌ Error: Local Factorio mods directory not found at $LOCAL_MODS_PATH"
    exit 1
fi

# ============================================================================
# STEP 1: HANDLE MODS
# ============================================================================

prepare_mods() {
    echo "📦 Preparing FactoryVerse mods (fv_embodied_agent + fv_snapshot)..."
    
    # Remove old mod copies
    echo "   Removing existing FactoryVerse mod copies..."
    rm -rf "${LOCAL_MODS_PATH}"/fv_embodied_agent*
    rm -rf "${LOCAL_MODS_PATH}"/fv_snapshot*
    rm -rf "${LOCAL_MODS_PATH}"/factorio_verse*
    
    # Prepare fv_embodied_agent mod
    EA_VERSION=$(grep -o '"version"\s*:\s*"[^"]*"' "${SCRIPT_DIR}/src/fv_embodied_agent/info.json" | cut -d'"' -f4)
    EA_MOD_NAME="fv_embodied_agent_${EA_VERSION}"
    mkdir -p "${LOCAL_MODS_PATH}/${EA_MOD_NAME}"
    cp -r "${SCRIPT_DIR}/src/fv_embodied_agent"/* "${LOCAL_MODS_PATH}/${EA_MOD_NAME}/"
    echo "✓ fv_embodied_agent mod copied as ${EA_MOD_NAME}"
    
    # Prepare fv_snapshot mod
    SS_VERSION=$(grep -o '"version"\s*:\s*"[^"]*"' "${SCRIPT_DIR}/src/fv_snapshot/info.json" | cut -d'"' -f4)
    SS_MOD_NAME="fv_snapshot_${SS_VERSION}"
    mkdir -p "${LOCAL_MODS_PATH}/${SS_MOD_NAME}"
    cp -r "${SCRIPT_DIR}/src/fv_snapshot"/* "${LOCAL_MODS_PATH}/${SS_MOD_NAME}/"
    echo "✓ fv_snapshot mod copied as ${SS_MOD_NAME}"
    
    # Update mod-list.json
    if [ -f "${LOCAL_MODS_PATH}/mod-list.json" ]; then
        jq '.mods += [{\"name\": \"fv_embodied_agent\", \"enabled\": true}] | 
             .mods += [{\"name\": \"fv_snapshot\", \"enabled\": true}] | 
             .mods += [{\"name\": \"elevated-rails\", \"enabled\": false}] | 
             .mods += [{\"name\": \"quality\", \"enabled\": false}] | 
             .mods += [{\"name\": \"space-age\", \"enabled\": false}] | 
             .mods |= unique_by(.name) |
             .mods |= map(if .name == \"fv_embodied_agent\" then .enabled = true 
                         elif .name == \"fv_snapshot\" then .enabled = true
                         elif .name == \"elevated-rails\" then .enabled = false 
                         elif .name == \"quality\" then .enabled = false 
                         elif .name == \"space-age\" then .enabled = false else . end)' \
            "${LOCAL_MODS_PATH}/mod-list.json" > "${LOCAL_MODS_PATH}/mod-list.json.tmp"
        mv "${LOCAL_MODS_PATH}/mod-list.json.tmp" "${LOCAL_MODS_PATH}/mod-list.json"
    else
        cat > "${LOCAL_MODS_PATH}/mod-list.json" << 'EOF'
{
  "mods": [
    {"name": "base", "enabled": true},
    {"name": "fv_embodied_agent", "enabled": true},
    {"name": "fv_snapshot", "enabled": true},
    {"name": "elevated-rails", "enabled": false},
    {"name": "quality", "enabled": false},
    {"name": "space-age", "enabled": false}
  ]
}
EOF
    fi
    
    echo "✓ Mods prepared"
}

# ============================================================================
# STEP 2: HANDLE SCENARIO/SAVE
# ============================================================================

validate_scenario() {
    local scenario=$1
    if [ ! -d "${SCRIPT_DIR}/src/factorio/scenarios/${scenario}" ]; then
        echo "❌ Error: Scenario '${scenario}' not found"
        exit 1
    fi
    echo "✓ Scenario validated: $scenario"
}

# ============================================================================
# STEP 3: GENERATE DOCKER COMPOSE
# ============================================================================

generate_compose() {
    local num_instances=$1
    local scenario=$2
    
    cat > "${SCRIPT_DIR}/docker-compose.yml" <<EOF
services:
EOF
    
    for i in $(seq 0 $((num_instances - 1))); do
        local udp_port=$((34197 + i))
        local tcp_port=$((27000 + i))
        local output_dir="${SCRIPT_DIR}/.fv-output/output_${i}"
        
        mkdir -p "$output_dir"
        
        cat >> "${SCRIPT_DIR}/docker-compose.yml" <<EOF
  factorio_${i}:
    image: factoriotools/factorio:2.0.72
    platform: ${DOCKER_PLATFORM}
    entrypoint: []
    command: ${EMULATOR} /opt/factorio/bin/x64/factorio --start-server-load-scenario ${scenario} --port 34197 --rcon-port 27015 --rcon-password "factorio" --server-settings /factorio/config/server-settings.json --map-gen-settings /factorio/config/map-gen-settings.json --map-settings /factorio/config/map-settings.json --server-whitelist /factorio/config/server-whitelist.json --use-server-whitelist --server-adminlist /factorio/config/server-adminlist.json --mod-directory /opt/factorio/mods --map-gen-seed 44340
    environment:
      - DLC_SPACE_AGE=false
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1024m
    ports:
      - ${udp_port}:34197/udp
      - ${tcp_port}:27015/tcp
    volumes:
      - source: ${SCRIPT_DIR}/src/factorio/scenarios
        target: /opt/factorio/scenarios
        type: bind
      - source: "${LOCAL_MODS_PATH}"
        target: /opt/factorio/mods
        type: bind
      - source: ${SCRIPT_DIR}/src/factorio/config
        target: /factorio/config
        type: bind
      - source: ${output_dir}
        target: /opt/factorio/script-output
        type: bind
EOF
    done
    
    echo "✓ docker-compose.yml generated"
}

# ============================================================================
# COMMANDS
# ============================================================================

start_cluster() {
    local num_instances=$1
    local scenario=${2:-test-ground}
    
    echo "🚀 Starting Factorio cluster (${num_instances} instance(s), scenario: ${scenario})"
    
    validate_scenario "$scenario"
    prepare_mods
    generate_compose "$num_instances" "$scenario"
    
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d
    
    echo "✅ Cluster started!"
    for i in $(seq 0 $((num_instances - 1))); do
        echo "  Server $i: localhost:$((34197 + i))"
    done
}

stop_cluster() {
    if [ ! -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
        echo "❌ No cluster running"
        exit 1
    fi
    
    echo "🛑 Stopping cluster..."
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
    echo "✅ Cluster stopped"
}

# ============================================================================
# MAIN
# ============================================================================

if ! command -v docker &>/dev/null; then
    echo "❌ Docker not found"
    exit 1
fi

COMMAND="${1:-start}"
NUM_INSTANCES="${2:-1}"
SCENARIO="${3:-test-ground}"

case "$COMMAND" in
    start|'')
        start_cluster "$NUM_INSTANCES" "$SCENARIO"
        ;;
    stop)
        stop_cluster
        ;;
    restart)
        docker compose -f "${SCRIPT_DIR}/docker-compose.yml" restart
        ;;
    *)
        echo "Usage: $0 [start|stop|restart] [num_instances] [scenario]"
        ;;
esac
