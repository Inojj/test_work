from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.worker.worker import main


def _configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().LOG_LEVEL.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


if __name__ == "__main__":
    _configure_logging()
    asyncio.run(main())
