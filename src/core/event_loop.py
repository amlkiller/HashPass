"""Event loop initialization with uvloop support"""
import os
import sys
import logging

logger = logging.getLogger(__name__)


def init_event_loop():
    """
    Initialize event loop with platform-specific optimization

    - On Linux/macOS: Install uvloop for 30-40% performance improvement
    - On Windows: Use standard asyncio (uvloop not supported)

    CRITICAL: Must be called BEFORE any asyncio imports (before state.py)
    """
    # Emergency disable switch (for rollback if needed)
    if os.getenv("HASHPASS_DISABLE_UVLOOP", "false").lower() == "true":
        logger.info("uvloop disabled via HASHPASS_DISABLE_UVLOOP")
        return

    # Platform detection
    is_unix = sys.platform in ('linux', 'darwin')

    if not is_unix:
        logger.info("Running on %s - using standard asyncio", sys.platform)
        logger.info("Note: For uvloop performance on Windows, use WSL2")
        return

    # Try to install uvloop
    try:
        import uvloop
        uvloop.install()
        logger.info("uvloop installed successfully on %s", sys.platform)
        logger.info("Expected: 30-40%% faster WebSocket, 5-10%% faster lock ops")
    except ImportError:
        logger.warning("uvloop not available - using standard asyncio")
        logger.warning("Install with: pip install uvloop")
    except Exception as e:
        logger.error("Failed to install uvloop: %s", e)
        logger.error("Falling back to standard asyncio")


def get_event_loop_info() -> dict:
    """
    Get current event loop information for debugging

    Returns:
        Dict with event loop type and platform info
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop_type = type(loop).__module__ + "." + type(loop).__name__
    except RuntimeError:
        loop_type = "no running loop"

    return {
        "platform": sys.platform,
        "loop_type": loop_type,
        "is_uvloop": "uvloop" in loop_type,
    }
