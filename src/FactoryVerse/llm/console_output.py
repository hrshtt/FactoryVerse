"""Console output handler for clean LLM conversation display."""
import sys
from typing import Optional


class ConsoleOutput:
    """Handles clean console output for LLM agent interactions."""
    
    # ANSI color codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Colors
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    
    def __init__(self, enabled: bool = True):
        """
        Initialize console output handler.
        
        Args:
            enabled: Whether to enable console output
        """
        self.enabled = enabled
    
    def _print(self, message: str, end: str = "\n"):
        """Print message if enabled."""
        if self.enabled:
            print(message, end=end, flush=True)
    
    def user_message(self, message: str):
        """Display user message."""
        self._print(f"\n{self.BOLD}{self.BLUE}User >{self.RESET} {message}")
    
    def assistant_response(self, message: str, turn_number: int):
        """Display assistant text response."""
        self._print(f"\n{self.BOLD}{self.GREEN}Assistant{self.RESET} {self.DIM}(Turn {turn_number}){self.RESET}")
        self._print(f"{message}")
    
    def llm_thinking(self, iteration: int):
        """Display LLM thinking indicator."""
        self._print(f"{self.DIM}🤔 Thinking... (iteration {iteration}){self.RESET}")
    
    def tool_call_start(self, tool_name: str, iteration: int):
        """Display tool call header."""
        emoji = "🐍" if tool_name == "execute_dsl" else "🗄️"
        self._print(f"\n{self.BOLD}{self.CYAN}{emoji} {tool_name}{self.RESET} {self.DIM}(iteration {iteration}){self.RESET}")
    
    def tool_call_code(self, code: str, language: str = "python"):
        """Display tool call code."""
        # Syntax highlighting would be nice but keeping it simple
        lang_display = "Python" if language == "python" else "SQL"
        self._print(f"{self.DIM}┌─ {lang_display} Code ─{self.RESET}")
        
        # Print code with line numbers for better readability
        lines = code.split('\n')
        max_line_num = len(str(len(lines)))
        for i, line in enumerate(lines, 1):
            line_num = str(i).rjust(max_line_num)
            self._print(f"{self.DIM}{line_num} │{self.RESET} {line}")
        
        self._print(f"{self.DIM}└{'─' * 40}{self.RESET}")
    
    def tool_result(self, result: str, is_error: bool = False):
        """Display tool result."""
        if is_error:
            self._print(f"{self.RED}✗ Error:{self.RESET}")
            # Show first few lines of error
            lines = result.split('\n')[:10]
            for line in lines:
                self._print(f"  {line}")
            if len(result.split('\n')) > 10:
                self._print(f"  {self.DIM}... (truncated){self.RESET}")
        else:
            self._print(f"{self.GREEN}✓ Result:{self.RESET}")
            # Show first few lines of result
            lines = result.split('\n')[:15]
            for line in lines:
                self._print(f"  {line}")
            if len(result.split('\n')) > 15:
                self._print(f"  {self.DIM}... (truncated, see full output in chat.md){self.RESET}")
    
    def turn_complete(self, turn_number: int):
        """Display turn completion."""
        self._print(f"\n{self.DIM}{'─' * 60}{self.RESET}")
        self._print(f"{self.DIM}Turn {turn_number} complete{self.RESET}")
        self._print(f"{self.DIM}{'─' * 60}{self.RESET}\n")
    
    def max_iterations_warning(self, turn_number: int):
        """Display max iterations warning."""
        self._print(f"\n{self.YELLOW}⚠️  Turn {turn_number}: Reached max iterations{self.RESET}")
    
    def error(self, message: str):
        """Display error message."""
        self._print(f"{self.RED}❌ Error: {message}{self.RESET}")
    
    def info(self, message: str):
        """Display info message."""
        self._print(f"{self.CYAN}ℹ️  {message}{self.RESET}")
    
    def system_notification(self, notification: str):
        """Display system notification from game events."""
        self._print(f"\n{self.BOLD}{self.MAGENTA}📢 Game Notification:{self.RESET}")
        # Print each line of the notification with indentation
        for line in notification.split('\n'):
            self._print(f"{self.MAGENTA}{line}{self.RESET}")
        self._print("")  # Empty line after notification
    
    def success(self, message: str):
        """Display success message."""
        self._print(f"{self.GREEN}✓ {message}{self.RESET}")
