import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit
MAX_CONVERSATION_LENGTH = 50  # Maximum number of messages to keep
DEFAULT_MODEL = "claude-sonnet-4-6"  # Default Claude model
GIT_TIMEOUT = 30  # Git command timeout in seconds
API_MAX_TOKENS = 8192  # Maximum tokens for API requests
API_TIMEOUT = float(
    os.environ.get("NTCODE_API_TIMEOUT", "600")
)  # API call timeout in seconds (default 10 min)

# Security Configuration
ALLOWED_BASE_PATHS = [Path.cwd()]  # Only allow current directory and subdirectories

# ---------------------------------------------------------------------------
# Token rate limiter constants
# ---------------------------------------------------------------------------

TOKEN_LIMIT_PER_MINUTE: int = int(
    os.environ.get("NTCODE_TOKEN_LIMIT_PER_MINUTE", "30000")
)
_RATE_WINDOW_SECONDS: int = 60

# ---------------------------------------------------------------------------
# Debug / logging configuration
# ---------------------------------------------------------------------------

DEBUG_MODE = os.environ.get("NTCODE_DEBUG", "false").lower() in ["true", "1", "yes"]
VERBOSE_MODE = os.environ.get("NTCODE_VERBOSE", "false").lower() in ["true", "1", "yes"]
LOG_CONVERSATIONS = os.environ.get("NTCODE_LOG_CONVERSATIONS", "true").lower() in [
    "true",
    "1",
    "yes",
]

# Configure logging
log_handlers: list = []
if DEBUG_MODE:
    log_handlers.append(logging.StreamHandler(sys.stdout))
if LOG_CONVERSATIONS:
    log_handlers.append(logging.FileHandler("ntcode.log", mode="a"))
if not log_handlers:  # If no logging enabled, use null handler
    log_handlers.append(logging.NullHandler())

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger("ntCode")

# ---------------------------------------------------------------------------
# ANSI color constants (used by the TUI frontend)
# ---------------------------------------------------------------------------

YOU_COLOR = "\u001b[94m"
ASSISTANT_COLOR = "\u001b[93m"
RESET_COLOR = "\u001b[0m"
