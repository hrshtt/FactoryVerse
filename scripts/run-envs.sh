#!/bin/bash

# FactoryVerse Server Management Script
# Simplified mod-based server launcher with automatic client synchronization
# 
# Features:
# - Launches Factorio servers with FactoryVerse mod
# - Automatically zips and deploys the FactoryVerse mod
# - Syncs local Factorio mods to server
# - Validates scenario selection
# - Supports multiple server instances
# - Auto-synchronizes mods to clients on connection

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FACTORIO_VERSE_MOD_DIR="${SCRIPT_DIR}/src/factorio_verse"
FACTORIO_MODS_DIR="${SCRIPT_DIR}/src/factorio/mods"
FACTORIO_SCENARIOS_DIR="${SCRIPT_DIR}/src/factorio/scenarios"
FACTORIO_CONFIG_DIR="${SCRIPT_DIR}/src/factorio/config"
FV_OUTPUT_DIR="${SCRIPT_DIR}/.fv-output"

# Local Factorio mods directory (system-dependent)
LOCAL_MODS_PATH=""

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Detect platform and set up Docker configuration
setup_platform() {
    ARCH=$(uname -m)
    OS=$(uname -s)
    
    if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
        export EMULATOR="/bin/box64"
        export DOCKER_PLATFORM="linux/arm64"
    else
        export DOCKER_PLATFORM="linux/amd64"
        export EMULATOR=""
    fi
    
    echo "✓ Platform: $ARCH, Docker platform: $DOCKER_PLATFORM"
}

# Verify Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo "❌ Error: Docker not found. Please install Docker."
        exit 1
    fi
    COMPOSE_CMD="docker compose"
    echo "✓ Docker found"
}

# Detect and set local Factorio mods directory
detect_local_mods_path() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        LOCAL_MODS_PATH="$HOME/Library/Application Support/Factorio/mods"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        LOCAL_MODS_PATH="$HOME/.factorio/mods"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        # Windows
        LOCAL_MODS_PATH="$USERPROFILE/AppData/Roaming/Factorio/mods"
    fi
    
    if [ -z "$LOCAL_MODS_PATH" ] || [ ! -d "$LOCAL_MODS_PATH" ]; then
        echo "❌ Error: Local Factorio mods directory not found at $LOCAL_MODS_PATH"
        echo "Please ensure Factorio is installed and has been run at least once."
        exit 1
    fi
    
    echo "✓ Using local mods directory: $LOCAL_MODS_PATH"
}

# Validate that a scenario exists in the scenarios directory
validate_scenario() {
    local scenario=$1
    
    if [ ! -d "${FACTORIO_SCENARIOS_DIR}/${scenario}" ]; then
        echo "❌ Error: Scenario '${scenario}' not found in ${FACTORIO_SCENARIOS_DIR}"
        echo "Available scenarios:"
        ls -1 "${FACTORIO_SCENARIOS_DIR}" | grep -v "^\." | sed 's/^/  - /'
        exit 1
    fi
    
    echo "✓ Scenario validated: ${scenario}"
}

# Zip the FactoryVerse mod and copy to local mod directory
prepare_factorio_verse_mod() {
    if [ ! -d "${FACTORIO_VERSE_MOD_DIR}" ]; then
        echo "❌ Error: FactoryVerse mod directory not found at ${FACTORIO_VERSE_MOD_DIR}"
        exit 1
    fi
    
    # Get version from info.json
    if [ ! -f "${FACTORIO_VERSE_MOD_DIR}/info.json" ]; then
        echo "❌ Error: info.json not found in FactoryVerse mod directory"
        exit 1
    fi
    
    VERSION=$(grep -o '"version"\s*:\s*"[^"]*"' "${FACTORIO_VERSE_MOD_DIR}/info.json" | cut -d'"' -f4)
    MOD_NAME="factorio_verse_${VERSION}"
    MOD_ZIP="${LOCAL_MODS_PATH}/${MOD_NAME}.zip"
    
    # Only zip if it doesn't exist or if the mod source has been modified
    if [ ! -f "${MOD_ZIP}" ] || [ "${FACTORIO_VERSE_MOD_DIR}" -nt "${MOD_ZIP}" ]; then
        echo "📦 Zipping FactoryVerse mod (v${VERSION})..."
        
        # Create a temporary directory for the mod structure
        TEMP_MOD_DIR=$(mktemp -d)
        trap "rm -rf ${TEMP_MOD_DIR}" EXIT
        
        # Copy mod contents to temp directory with correct structure
        mkdir -p "${TEMP_MOD_DIR}/${MOD_NAME}"
        cp -r "${FACTORIO_VERSE_MOD_DIR}"/* "${TEMP_MOD_DIR}/${MOD_NAME}/"
        
        # Create the zip file in the local mod directory
        (cd "${TEMP_MOD_DIR}" && zip -r "${MOD_ZIP}" "${MOD_NAME}" > /dev/null 2>&1)
        
        if [ -f "${MOD_ZIP}" ]; then
            echo "✓ Mod zipped successfully to: ${MOD_ZIP}"
        else
            echo "❌ Error: Failed to create mod zip file"
            exit 1
        fi
    else
        echo "✓ FactoryVerse mod already prepared: ${MOD_ZIP}"
    fi
}

# Update mod-list.json to enable all zipped mods in local directory
update_mod_list() {
    echo "📋 Updating mod-list.json..."
    
    # Read existing mod-list.json or create a default one
    if [ -f "${LOCAL_MODS_PATH}/mod-list.json" ]; then
        # Add our required mods and deduplicate by name
        jq '.mods += [{"name": "factorio_verse", "enabled": true}] | 
             .mods += [{"name": "elevated-rails", "enabled": false}] | 
             .mods += [{"name": "quality", "enabled": false}] | 
             .mods += [{"name": "space-age", "enabled": false}] | 
             .mods |= unique_by(.name) |
             .mods |= map(if .name == "factorio_verse" then .enabled = true 
                         elif .name == "elevated-rails" then .enabled = false 
                         elif .name == "quality" then .enabled = false 
                         elif .name == "space-age" then .enabled = false 
                         else . end)' \
            "${LOCAL_MODS_PATH}/mod-list.json" > "${LOCAL_MODS_PATH}/mod-list.json.tmp"
        mv "${LOCAL_MODS_PATH}/mod-list.json.tmp" "${LOCAL_MODS_PATH}/mod-list.json"
    else
        # Create new mod-list.json with just what we need
        cat > "${LOCAL_MODS_PATH}/mod-list.json" << 'EOF'
{
  "mods": [
    {"name": "base", "enabled": true},
    {"name": "factorio_verse", "enabled": true},
    {"name": "elevated-rails", "enabled": false},
    {"name": "quality", "enabled": false},
    {"name": "space-age", "enabled": false}
  ]
}
EOF
    fi
    
    echo "✓ mod-list.json updated (factorio_verse enabled, DLC mods disabled)"
}

# Create output directories for each server instance
create_output_dirs() {
    local num_instances=$1
    
    mkdir -p "${FV_OUTPUT_DIR}/saves"
    
    for i in $(seq 0 $((num_instances - 1))); do
        mkdir -p "${FV_OUTPUT_DIR}/output_${i}"
    done
    
    echo "✓ Output directories created"
}

# Generate docker-compose.yml with specified number of instances
generate_compose_file() {
    local num_instances=$1
    local scenario=$2
    
    cat > "${SCRIPT_DIR}/docker-compose.yml" << EOF
services:
EOF

    for i in $(seq 0 $((num_instances - 1))); do
        UDP_PORT=$((34197 + i))
        TCP_PORT=$((27000 + i))
        
        cat >> "${SCRIPT_DIR}/docker-compose.yml" << EOF
  factorio_${i}:
    image: factoriotools/factorio:2.0.60
    platform: ${DOCKER_PLATFORM}
    entrypoint: []
    command: ${EMULATOR} /opt/factorio/bin/x64/factorio --start-server-load-scenario ${scenario} --port 34197 --rcon-port 27015 --rcon-password "factorio" --server-settings /factorio/config/server-settings.json --map-gen-settings /factorio/config/map-gen-settings.json --map-settings /factorio/config/map-settings.json --server-banlist /factorio/config/server-banlist.json --server-whitelist /factorio/config/server-whitelist.json --use-server-whitelist --server-adminlist /factorio/config/server-adminlist.json --mod-directory /opt/factorio/mods --map-gen-seed 44340
    environment:
      - DLC_SPACE_AGE=false
      - RCON_PORT=27015
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1024m
    ports:
    - ${UDP_PORT}:34197/udp
    - ${TCP_PORT}:27015/tcp
    pull_policy: missing
    volumes:
    - source: ./src/factorio/scenarios
      target: /opt/factorio/scenarios
      type: bind
    - source: "${LOCAL_MODS_PATH}"
      target: /opt/factorio/mods
      type: bind
    - source: ./src/factorio/config
      target: /factorio/config
      type: bind
    - source: ${FV_OUTPUT_DIR}/output_${i}
      target: /opt/factorio/script-output
      type: bind
EOF
    done
    
    echo "✓ docker-compose.yml generated for $num_instances instance(s)"
}

# Start the Factorio cluster
start_cluster() {
    local num_instances=$1
    local scenario=$2
    
    echo ""
    echo "🚀 Starting Factorio cluster..."
    echo "  Instances: $num_instances"
    echo "  Scenario: $scenario"
    echo ""
    
    # Validate inputs
    if ! [[ "$num_instances" =~ ^[0-9]+$ ]] || [ "$num_instances" -lt 1 ] || [ "$num_instances" -gt 33 ]; then
        echo "❌ Error: Number of instances must be between 1 and 33"
        exit 1
    fi
    
    validate_scenario "$scenario"
    
    # Prepare everything
    detect_local_mods_path
    prepare_factorio_verse_mod
    update_mod_list
    create_output_dirs "$num_instances"
    generate_compose_file "$num_instances" "$scenario"
    
    # Start the cluster
    $COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" up -d
    
    echo ""
    echo "✅ Factorio cluster started successfully!"
    echo ""
    echo "Access servers at:"
    for i in $(seq 0 $((num_instances - 1))); do
        UDP_PORT=$((34197 + i))
        TCP_PORT=$((27000 + i))
        echo "  Server $i: localhost:${UDP_PORT} (UDP)"
    done
    echo ""
}

# Stop all running Factorio instances
stop_cluster() {
    check_docker
    
    if [ ! -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
        echo "❌ Error: docker-compose.yml not found. No cluster to stop."
        exit 1
    fi
    
    echo "🛑 Stopping Factorio cluster..."
    
    # Attempt to kick all players
    RUNNING_CONTAINERS=$($COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" ps --services --filter "status=running" 2>/dev/null | grep "factorio_" || true)
    
    if [ -n "$RUNNING_CONTAINERS" ]; then
        echo "  Kicking all players..."
        echo "$RUNNING_CONTAINERS" | while read -r container_name; do
            $COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" exec -T "$container_name" rcon '/c for _,p in pairs(game.connected_players) do rcon.print(p.name) end' 2>/dev/null | while read -r player_name; do
                [ -n "$player_name" ] && $COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" exec -T "$container_name" rcon "/kick $player_name Server maintenance" 2>/dev/null || true
            done
        done
        sleep 1
    fi
    
    $COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" down
    docker network prune -f 2>/dev/null || true
    
    echo "✅ Cluster stopped successfully"
}

# Restart existing cluster
restart_cluster() {
    check_docker
    
    if [ ! -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
        echo "❌ Error: docker-compose.yml not found. No cluster to restart."
        exit 1
    fi
    
    echo "🔄 Restarting Factorio cluster..."
    $COMPOSE_CMD -f "${SCRIPT_DIR}/docker-compose.yml" restart
    echo "✅ Cluster restarted successfully"
}

# Display usage information
show_help() {
    cat << EOF
FactoryVerse Server Manager

USAGE:
  $0 [COMMAND] [OPTIONS]

COMMANDS:
  start              Start Factorio servers with FactoryVerse mod (default)
  stop               Stop all running servers
  restart            Restart existing servers
  help               Show this help message

OPTIONS:
  -n, --num NUM      Number of server instances to run (1-33, default: 1)
  -s, --scenario S   Scenario to load (default: test_scenario)
  --sync-mods        Sync local Factorio mods to server mods directory

EXAMPLES:
  $0                            Start 1 server with test_scenario
  $0 -n 3 -s sandbox            Start 3 servers with sandbox scenario
  $0 -n 5 --sync-mods           Start 5 servers and sync local mods
  $0 --scenario freeplay        Start 1 server with freeplay scenario
  $0 stop                       Stop all running servers
  $0 restart                    Restart existing servers

FEATURES:
  • Automatically zips and deploys FactoryVerse mod
  • Clients auto-download and synchronize mods on connection
  • Validates scenario against available scenarios
  • Optional: Sync your local Factorio mods to server
  • Multiple server instances with different ports
  • Output and save files stored in .fv-output/

EOF
}

# ============================================================================
# MAIN SCRIPT
# ============================================================================

# Parse arguments
COMMAND="start"
NUM_INSTANCES=1
SCENARIO="test_scenario"
SYNC_LOCAL_MODS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        start|stop|restart|help)
            COMMAND="$1"
            shift
            ;;
        -n|--num)
            NUM_INSTANCES="${2:-1}"
            shift 2
            ;;
        -s|--scenario)
            SCENARIO="${2:-test_scenario}"
            shift 2
            ;;
        --sync-mods)
            SYNC_LOCAL_MODS=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "❌ Error: Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Execute command
setup_platform
check_docker

case "$COMMAND" in
    start)
        start_cluster "$NUM_INSTANCES" "$SCENARIO"
        ;;
    stop)
        stop_cluster
        ;;
    restart)
        restart_cluster
        ;;
    help)
        show_help
        ;;
    *)
        echo "❌ Error: Unknown command '$COMMAND'"
        show_help
        exit 1
        ;;
esac
