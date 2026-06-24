from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BOX_CONFIG_PATH = Path('secrets/box_config.json')


def get_box_client(config_path: Path = DEFAULT_BOX_CONFIG_PATH):
    """Return a Box JWT service-account client, or None when unavailable."""
    if not config_path.exists():
        logger.warning("Box credentials not found at '%s'.", config_path)
        return None
    try:
        from boxsdk import JWTAuth, Client
        auth = JWTAuth.from_settings_file(str(config_path))
        return Client(auth)
    except Exception as exc:
        logger.error("Failed to build Box client: %s", exc)
        return None
