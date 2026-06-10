# FactoryVerse UI Architecture

## Overview

The FactoryVerse UI is built using [NiceGUI](https://nicegui.io/) and provides a unified **Control Center** for managing all aspects of the FactoryVerse system.

## Quick Start

```bash
uv run fv ui
```

This launches the Control Center at http://localhost:8080

## Architecture

### Unified Control Center (`ui/app.py`)

The preferred entry point. A single-port, cohesive application with:

| Page | URL | Description |
|------|-----|-------------|
| **Overview** | `/` | System stats, quick actions, recent sessions |
| **Services** | `/services` | Docker, Client, Instance management |
| **Agents** | `/agents` | Launch sessions, view all sessions |
| **Trajectory** | `/trajectory/{session_id}` | Real-time trajectory viewer |
| **Settings** | `/settings` | Configuration (future) |

### Key Features

1. **Sidebar Navigation** - Consistent navigation across all pages
2. **Pre-flight Checks** - Verifies services before agent launch
3. **Glassmorphism Design** - Premium look with glass effects, gradients
4. **Real-time Updates** - Auto-refresh for status and trajectory
5. **Integrated Viewer** - Trajectory viewer is part of the app, not separate

## Design System

### Color Palette

```css
--primary: #6366f1;      /* Indigo */
--secondary: #0ea5e9;    /* Sky blue */
--success: #22c55e;      /* Green */
--warning: #f59e0b;      /* Amber */
--danger: #ef4444;       /* Red */
--surface: #1e1e2e;      /* Dark surface */
```

### Components

- `glass-card` - Glassmorphism card with blur and transparency
- `stat-card` - Statistics display with gradient text
- `session-card` - Session card with status indicator
- `sidebar-item` - Navigation item with hover effects

## Flow: Agent Session Launch

```
┌─────────────────┐
│  /agents page   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Pre-flight      │  ← Checks Docker, Client, Instances
│ Check Card      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Launch Form     │  ← Model, Mode, Instance
│                 │
└────────┬────────┘
         │ Click "LAUNCH SESSION"
         ▼
┌─────────────────┐
│ AgentService.   │  ← Uses unified service layer
│ create_session()│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Session Card    │  ← Shows in session list
│ appears         │
└────────┬────────┘
         │ Click "VIEW"
         ▼
┌─────────────────┐
│ /trajectory/    │  ← Real-time trajectory
│ {session_id}    │
└─────────────────┘
```

## Integration with Holistic Architecture

This UI implementation aligns with the `HOLISTIC_ARCHITECTURE_ANALYSIS.md` vision:

| Principle | Implementation |
|-----------|----------------|
| **Service-Based** | Uses `AgentService` and `ServiceManager` |
| **Shared Services** | Same services work for CLI, GUI, MCP |
| **Modular** | Each page/component has single responsibility |
| **Observable** | File-based trajectory for decoupled observation |
| **Pre-flight** | Service checks before agent operations |

## Legacy Modules (Deprecated)

The following are kept for backward compatibility but should not be used:

- `ui/dashboard.py` → Use Control Center `/services` page
- `ui/agent_orchestrator.py` → Use Control Center `/agents` page  
- `ui/agent_viewer.py` → Use Control Center `/trajectory/{id}` page

## CLI Commands

```bash
# Preferred: Launch unified Control Center
uv run fv ui

# Legacy (deprecated): Separate UIs
uv run fv ui-agents  # Use 'ui' instead
```

## Future Enhancements

1. **Settings Page** - Configuration editor
2. **Log Viewer** - Real-time log streaming
3. **Resource Monitor** - CPU/Memory graphs
4. **Multi-Session View** - Compare trajectories side-by-side
5. **Keyboard Shortcuts** - Power user navigation
