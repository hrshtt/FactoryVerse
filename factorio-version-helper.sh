#!/bin/bash

# Factorio Version Manager for macOS
# This script helps manage multiple beta versions of Factorio without re-downloading

# Configuration
FACTORIO_GAME_DIR="$HOME/Library/Application Support/Steam/steamapps/common/Factorio"
FACTORIO_DATA_DIR="$HOME/Library/Application Support/factorio"
BACKUP_BASE_DIR="$HOME/FactorioVersions"
CURRENT_VERSION_FILE="$BACKUP_BASE_DIR/current_version.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if directories exist
check_directories() {
    if [ ! -d "$FACTORIO_GAME_DIR" ]; then
        print_error "Factorio game directory not found: $FACTORIO_GAME_DIR"
        exit 1
    fi
    
    if [ ! -d "$FACTORIO_DATA_DIR" ]; then
        print_error "Factorio data directory not found: $FACTORIO_DATA_DIR"
        exit 1
    fi
}

# Function to create backup directory structure
setup_backup_dir() {
    mkdir -p "$BACKUP_BASE_DIR"
    mkdir -p "$BACKUP_BASE_DIR/versions"
    mkdir -p "$BACKUP_BASE_DIR/saves_backup"
}

# Function to get current Factorio version
get_current_version() {
    if [ -f "$FACTORIO_GAME_DIR/factorio.app/Contents/Info.plist" ]; then
        # Try to extract version from Info.plist
        version=$(plutil -extract CFBundleShortVersionString raw "$FACTORIO_GAME_DIR/factorio.app/Contents/Info.plist" 2>/dev/null)
        if [ -n "$version" ]; then
            echo "$version"
        else
            # Fallback: try to get version from binary
            version_output=$("$FACTORIO_GAME_DIR/factorio.app/Contents/MacOS/factorio" --version 2>/dev/null | head -1)
            if [ -n "$version_output" ]; then
                echo "$version_output" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1
            else
                echo "unknown"
            fi
        fi
    else
        echo "unknown"
    fi
}

# Function to backup current version
backup_version() {
    local version_name="$1"
    local backup_dir="$BACKUP_BASE_DIR/versions/$version_name"
    
    print_info "Backing up current version as: $version_name"
    
    # Create backup directory
    mkdir -p "$backup_dir"
    
    # Check if Steam is running and warn user
    if pgrep -x "Steam" > /dev/null; then
        print_warning "Steam is currently running. Please close Steam before backing up to avoid file conflicts."
        read -p "Press Enter to continue after closing Steam, or Ctrl+C to cancel..."
    fi
    
    # Backup game files
    print_info "Backing up game files..."
    if ! cp -R "$FACTORIO_GAME_DIR" "$backup_dir/game" 2>/dev/null; then
        print_error "Failed to backup game files"
        exit 1
    fi
    
    # Backup data directory (saves, mods, etc.)
    print_info "Backing up data directory..."
    if ! cp -R "$FACTORIO_DATA_DIR" "$backup_dir/data" 2>/dev/null; then
        print_error "Failed to backup data directory"
        exit 1
    fi
    
    # Store version info
    local current_version=$(get_current_version)
    echo "$current_version" > "$backup_dir/version.txt"
    echo "$(date)" > "$backup_dir/backup_date.txt"
    
    # Update current version tracker
    echo "$version_name" > "$CURRENT_VERSION_FILE"
    
    print_success "Backup completed: $version_name (Version: $current_version)"
    print_info "Backup size: $(du -sh "$backup_dir" | cut -f1)"
}

# Function to restore a version
restore_version() {
    local version_name="$1"
    local backup_dir="$BACKUP_BASE_DIR/versions/$version_name"
    
    if [ ! -d "$backup_dir" ]; then
        print_error "Backup not found: $version_name"
        list_versions
        exit 1
    fi
    
    print_info "Restoring version: $version_name"
    
    # Check if Steam is running and warn user
    if pgrep -x "Steam" > /dev/null; then
        print_warning "Steam is currently running. Please close Steam before restoring to avoid file conflicts."
        read -p "Press Enter to continue after closing Steam, or Ctrl+C to cancel..."
    fi
    
    # Backup current state before restoring (safety measure)
    local current_version_name="pre-restore-$(date +%Y%m%d_%H%M%S)"
    print_info "Creating safety backup of current state..."
    backup_version "$current_version_name"
    
    # Remove current installation
    print_info "Removing current game installation..."
    rm -rf "$FACTORIO_GAME_DIR"
    rm -rf "$FACTORIO_DATA_DIR"
    
    # Restore game files
    print_info "Restoring game files..."
    if ! cp -R "$backup_dir/game" "$FACTORIO_GAME_DIR" 2>/dev/null; then
        print_error "Failed to restore game files"
        exit 1
    fi
    
    # Restore data directory
    print_info "Restoring data directory..."
    if ! cp -R "$backup_dir/data" "$FACTORIO_DATA_DIR" 2>/dev/null; then
        print_error "Failed to restore data directory"
        exit 1
    fi
    
    # Update current version tracker
    echo "$version_name" > "$CURRENT_VERSION_FILE"
    
    local restored_version=$(cat "$backup_dir/version.txt" 2>/dev/null || echo "unknown")
    print_success "Restore completed: $version_name (Version: $restored_version)"
    print_info "You can now start Steam and launch Factorio"
}

# Function to list available versions
list_versions() {
    print_info "Available backed up versions:"
    
    if [ ! -d "$BACKUP_BASE_DIR/versions" ] || [ -z "$(ls -A "$BACKUP_BASE_DIR/versions" 2>/dev/null)" ]; then
        print_warning "No versions backed up yet"
        return
    fi
    
    local current_version=""
    if [ -f "$CURRENT_VERSION_FILE" ]; then
        current_version=$(cat "$CURRENT_VERSION_FILE")
    fi
    
    echo
    printf "%-20s %-15s %-20s %-10s\n" "NAME" "VERSION" "BACKUP DATE" "SIZE"
    printf "%-20s %-15s %-20s %-10s\n" "----" "-------" "-----------" "----"
    
    for version_dir in "$BACKUP_BASE_DIR/versions"/*; do
        if [ -d "$version_dir" ]; then
            local name=$(basename "$version_dir")
            local version=$(cat "$version_dir/version.txt" 2>/dev/null || echo "unknown")
            local backup_date=$(cat "$version_dir/backup_date.txt" 2>/dev/null || echo "unknown")
            local size=$(du -sh "$version_dir" 2>/dev/null | cut -f1 || echo "unknown")
            
            local marker=""
            if [ "$name" = "$current_version" ]; then
                marker=" *"
            fi
            
            printf "%-20s %-15s %-20s %-10s%s\n" "$name" "$version" "$backup_date" "$size" "$marker"
        fi
    done
    
    echo
    print_info "* indicates currently active version"
}

# Function to delete a version
delete_version() {
    local version_name="$1"
    local backup_dir="$BACKUP_BASE_DIR/versions/$version_name"
    
    if [ ! -d "$backup_dir" ]; then
        print_error "Backup not found: $version_name"
        return 1
    fi
    
    print_warning "This will permanently delete the backup: $version_name"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$backup_dir"
        print_success "Deleted backup: $version_name"
    else
        print_info "Deletion cancelled"
    fi
}

# Function to show current status
show_status() {
    print_info "Factorio Version Manager Status"
    echo
    
    # Check if directories exist
    if [ -d "$FACTORIO_GAME_DIR" ]; then
        print_success "Game directory found: $FACTORIO_GAME_DIR"
        local current_version=$(get_current_version)
        print_info "Current installed version: $current_version"
    else
        print_error "Game directory not found: $FACTORIO_GAME_DIR"
    fi
    
    if [ -d "$FACTORIO_DATA_DIR" ]; then
        print_success "Data directory found: $FACTORIO_DATA_DIR"
    else
        print_error "Data directory not found: $FACTORIO_DATA_DIR"
    fi
    
    # Show current active backup
    if [ -f "$CURRENT_VERSION_FILE" ]; then
        local current_backup=$(cat "$CURRENT_VERSION_FILE")
        print_info "Current active backup: $current_backup"
    else
        print_warning "No active backup tracked"
    fi
    
    # Show backup directory info
    if [ -d "$BACKUP_BASE_DIR" ]; then
        print_info "Backup directory: $BACKUP_BASE_DIR"
        local backup_count=$(ls -1 "$BACKUP_BASE_DIR/versions" 2>/dev/null | wc -l)
        print_info "Number of backups: $backup_count"
        local total_size=$(du -sh "$BACKUP_BASE_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        print_info "Total backup size: $total_size"
    else
        print_warning "Backup directory not yet created"
    fi
}

# Function to show help
show_help() {
    echo "Factorio Version Manager for macOS"
    echo
    echo "Usage: $0 [command] [options]"
    echo
    echo "Commands:"
    echo "  backup <name>     - Backup current version with given name"
    echo "  restore <name>    - Restore a backed up version"
    echo "  list              - List all backed up versions"
    echo "  delete <name>     - Delete a backed up version"
    echo "  status            - Show current status"
    echo "  help              - Show this help message"
    echo
    echo "Examples:"
    echo "  $0 backup 1.1.110-stable"
    echo "  $0 backup 2.0.15-experimental"
    echo "  $0 restore 1.1.110-stable"
    echo "  $0 list"
    echo "  $0 delete old-version"
    echo
    echo "Notes:"
    echo "  - Close Steam before backing up or restoring"
    echo "  - Backups include both game files and data (saves, mods, etc.)"
    echo "  - A safety backup is created before each restore"
    echo "  - Use descriptive names for your backups"
}

# Main script logic
main() {
    case "$1" in
        backup)
            if [ -z "$2" ]; then
                print_error "Please provide a name for the backup"
                echo "Usage: $0 backup <name>"
                exit 1
            fi
            check_directories
            setup_backup_dir
            backup_version "$2"
            ;;
        restore)
            if [ -z "$2" ]; then
                print_error "Please provide the name of the backup to restore"
                echo "Usage: $0 restore <name>"
                exit 1
            fi
            check_directories
            setup_backup_dir
            restore_version "$2"
            ;;
        list)
            setup_backup_dir
            list_versions
            ;;
        delete)
            if [ -z "$2" ]; then
                print_error "Please provide the name of the backup to delete"
                echo "Usage: $0 delete <name>"
                exit 1
            fi
            setup_backup_dir
            delete_version "$2"
            ;;
        status)
            show_status
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"