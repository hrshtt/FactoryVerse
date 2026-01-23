"""Theme configuration for FactoryVerse UI."""

from nicegui import ui

# =============================================================================
# Modern Theme Colors
# =============================================================================
COLORS = {
    "primary": "#6366f1",  # Indigo
    "primary_dark": "#4f46e5",
    "secondary": "#0ea5e9",  # Sky blue
    "success": "#22c55e",  # Green
    "warning": "#f59e0b",  # Amber
    "danger": "#ef4444",  # Red
    "surface": "#1e1e2e",  # Dark surface
    "surface_alt": "#262637",  # Slightly lighter
    "text": "#e2e8f0",  # Light text
    "text_muted": "#94a3b8",  # Muted text
    "border": "#334155",  # Border color
}

# =============================================================================
# Industrial Theme Colors
# =============================================================================
INDUSTRIAL_COLORS = {
    "primary": "#D97706",  # Rust orange (main accent)
    "primary_dark": "#B45309",  # Darker rust
    "secondary": "#78716C",  # Industrial grey
    "success": "#65A30D",  # Olive/military green
    "warning": "#FBBF24",  # Industrial yellow/gold
    "danger": "#DC2626",  # Alert red
    "surface": "#1C1917",  # Dark brown/charcoal
    "surface_alt": "#292524",  # Stone grey
    "text": "#D6D3D1",  # Warm grey text
    "text_muted": "#A8A29E",  # Muted stone
    "border": "#57534E",  # Warm border
    "metal": "#44403C",  # Metal panel color
    "rust": "#9A3412",  # Deep rust for accents
}

# =============================================================================
# Theme Selection State
# =============================================================================
USE_INDUSTRIAL_THEME = True  # <-- Change this to toggle themes!


def apply_theme():
    """Apply the selected theme to the current page."""
    ui.dark_mode(True)
    theme_file = "industrial.css" if USE_INDUSTRIAL_THEME else "modern.css"
    # Note: The static directory must be registered in app.py
    ui.add_head_html(f'<link rel="stylesheet" href="/static/css/{theme_file}">')
