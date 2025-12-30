"""Session management for agent runs."""
import json
import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List


@dataclass
class SessionConfig:
    """Configuration for an agent session."""
    run_id: str
    model: str
    mode: str  # 'assisted' or 'autonomous'
    started_at: str
    ended_at: Optional[str] = None
    total_turns: int = 0
    config: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.config is None:
            self.config = {}


class SessionManager:
    """Manage agent session directories and metadata."""
    
    def __init__(self, output_dir: Path = None):
        """
        Initialize session manager.
        
        Args:
            output_dir: Base output directory (default: .fv-output)
        """
        if output_dir is None:
            output_dir = Path(".fv-output")
        
        self.output_dir = Path(output_dir)
        self.runs_dir = self.output_dir / "runs"
        self.config_dir = self.output_dir / "config"
        
        # Create directories
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def create_session(
        self,
        model_name: str,
        mode: str = "assisted",
        config: Optional[Dict[str, Any]] = None
    ) -> SessionConfig:
        """
        Create a new session with timestamp-based ID.
        
        Args:
            model_name: Name of the model (e.g., 'intellect-3')
            mode: 'assisted' or 'autonomous'
            config: Optional configuration dict
            
        Returns:
            SessionConfig with run metadata
        """
        # Generate timestamp-based run ID
        run_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        # Create session directory
        session_dir = self.runs_dir / model_name / run_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session config
        session = SessionConfig(
            run_id=run_id,
            model=model_name,
            mode=mode,
            started_at=datetime.datetime.now().isoformat(),
            config=config or {}
        )
        
        # Save metadata
        self._save_metadata(session_dir, session)
        
        return session
    
    def get_session_paths(self, session: SessionConfig) -> Dict[str, Path]:
        """
        Get all file paths for a session.
        
        Args:
            session: Session configuration
            
        Returns:
            Dict mapping file types to paths
        """
        session_dir = self.runs_dir / session.model / session.run_id
        
        return {
            'session_dir': session_dir,
            'metadata': session_dir / 'metadata.json',
            'notebook': session_dir / 'notebook.ipynb',
            'chat_log': session_dir / 'chat.md',
            'trajectory': session_dir / 'trajectory.json',
            'initial_state': session_dir / 'initial_state.md',
            'map_screenshot': session_dir / 'map_overview.png'
        }
    
    def update_session(self, session: SessionConfig):
        """
        Update session metadata.
        
        Args:
            session: Updated session configuration
        """
        session_dir = self.runs_dir / session.model / session.run_id
        self._save_metadata(session_dir, session)
    
    def list_sessions(
        self,
        model_name: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[SessionConfig]:
        """
        List all sessions, optionally filtered by model.
        
        Args:
            model_name: Optional model name to filter by
            limit: Optional limit on number of sessions to return
            
        Returns:
            List of SessionConfig objects, sorted by start time (newest first)
        """
        sessions = []
        
        # Determine which models to check
        if model_name:
            models = [model_name]
        else:
            if not self.runs_dir.exists():
                return []
            models = [d.name for d in self.runs_dir.iterdir() if d.is_dir()]
        
        # Collect sessions from each model
        for model in models:
            model_dir = self.runs_dir / model
            if not model_dir.exists():
                continue
            
            for run_dir in model_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                
                metadata_path = run_dir / 'metadata.json'
                if metadata_path.exists():
                    try:
                        with open(metadata_path) as f:
                            data = json.load(f)
                            sessions.append(SessionConfig(**data))
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"Warning: Could not load metadata from {metadata_path}: {e}")
        
        # Sort by start time (newest first)
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        
        # Apply limit if specified
        if limit:
            sessions = sessions[:limit]
        
        return sessions
    
    def _save_metadata(self, session_dir: Path, session: SessionConfig):
        """Save session metadata to JSON file."""
        metadata_path = session_dir / 'metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(asdict(session), f, indent=2)
