#!/bin/bash

# Prepare a Factorio save by overlaying src/factorio/factorio_verse and zipping it.
# - Accepts a path to a save .zip or a save directory
# - If zip: unzip so the result is a directory at .fv-output/saves/<save_name>
# - If directory: copy it directly to .fv-output/saves/<save_name>
# - Overlay @factorio_verse contents, overwriting control.lua
# - Append extra control.lua lines
# - Zip the save so the top-level in the archive is <save_name>/ and keep it in .fv-output/saves/

set -e

usage() {
    echo "Usage: $0 <save_zip_or_dir_path>"
    echo "Example: $0 ./my_save.zip"
    exit 1
}

if [ $# -lt 1 ]; then
    echo "Error: Missing input path"
    usage
fi

INPUT_PATH="$1"

# Resolve project structure
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_SAVES_DIR="$PROJECT_ROOT/.fv-output/saves"
FACTORIO_VERSE_DIR="$PROJECT_ROOT/src/factorio/factorio_verse"

mkdir -p "$OUTPUT_SAVES_DIR"

if [ ! -d "$FACTORIO_VERSE_DIR" ]; then
    echo "Error: factorio_verse not found at $FACTORIO_VERSE_DIR"
    exit 1
fi

# Determine input type and base name
if [ -f "$INPUT_PATH" ]; then
    case "$INPUT_PATH" in
        *.zip|*.ZIP)
            INPUT_TYPE="zip"
            ;;
        *)
            echo "Error: File input must be a .zip"
            exit 1
            ;;
    esac
    BASE_NAME="$(basename "$INPUT_PATH")"
    SAVE_NAME="${BASE_NAME%.*}"
elif [ -d "$INPUT_PATH" ]; then
    INPUT_TYPE="dir"
    # Remove trailing slash for basename
    INPUT_PATH="${INPUT_PATH%/}"
    SAVE_NAME="$(basename "$INPUT_PATH")"
else
    echo "Error: Input path not found: $INPUT_PATH"
    exit 1
fi

TARGET_SAVE_DIR="$OUTPUT_SAVES_DIR/$SAVE_NAME"

# Clean any previous output save directory
rm -rf "$TARGET_SAVE_DIR"

echo "▶ Preparing save: $SAVE_NAME"

if [ "$INPUT_TYPE" = "zip" ]; then
    echo "- Unzipping $INPUT_PATH to $OUTPUT_SAVES_DIR"
    TMP_EXTRACT_DIR="$OUTPUT_SAVES_DIR/.tmp_extract_$$"
    mkdir -p "$TMP_EXTRACT_DIR"
    unzip -q "$INPUT_PATH" -d "$TMP_EXTRACT_DIR"

    # If zip contained a single top-level dir, use it; otherwise wrap contents
    item_count=$(find "$TMP_EXTRACT_DIR" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
    if [ "$item_count" = "1" ] && [ -d "$(find "$TMP_EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d)" ]; then
        mv "$(find "$TMP_EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d)" "$TARGET_SAVE_DIR"
    else
        mkdir -p "$TARGET_SAVE_DIR"
        shopt -s dotglob
        mv "$TMP_EXTRACT_DIR"/* "$TARGET_SAVE_DIR/"
        shopt -u dotglob
    fi
    rm -rf "$TMP_EXTRACT_DIR"
else
    echo "- Copying directory $INPUT_PATH to $OUTPUT_SAVES_DIR/$SAVE_NAME"
    cp -R "$INPUT_PATH" "$OUTPUT_SAVES_DIR/"
fi

if [ ! -d "$TARGET_SAVE_DIR" ]; then
    echo "Error: Expected save directory not found at $TARGET_SAVE_DIR"
    exit 1
fi

echo "- Overlaying @factorio_verse contents onto save (overwriting control.lua)"
cp -Rf "$FACTORIO_VERSE_DIR"/. "$TARGET_SAVE_DIR"/

if [ ! -f "$TARGET_SAVE_DIR/control.lua" ]; then
    echo "Error: control.lua not found after overlay at $TARGET_SAVE_DIR/control.lua"
    exit 1
fi

echo "- Appending extra lines to control.lua"
# cat >> "$TARGET_SAVE_DIR/control.lua" <<'EOF'


# local handler = require("event_handler")
# handler.add_lib(require("freeplay"))
# handler.add_lib(require("silo-script"))
# EOF

echo "- Creating zip archive with top-level: $SAVE_NAME/"
(cd "$OUTPUT_SAVES_DIR" && rm -f "$SAVE_NAME.zip" && zip -q -r "$SAVE_NAME.zip" "$SAVE_NAME")

echo "✓ Done. Save directory: $TARGET_SAVE_DIR"
echo "  Zip archive: $OUTPUT_SAVES_DIR/$SAVE_NAME.zip"