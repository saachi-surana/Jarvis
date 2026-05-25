import logging
import os
from datetime import datetime

log_dir = os.path.expanduser("~/Projects/Jarvis/logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    force=True,
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, f"jarvis_{datetime.now().strftime('%Y%m%d')}.log")
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("jarvis")
