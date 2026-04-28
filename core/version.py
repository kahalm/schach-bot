"""Bot-Version (major.minor.bugfix) und Startzeitpunkt."""

import os
from datetime import datetime, timezone

VERSION = '2.26.0'
GIT_SHA = os.environ.get('GIT_SHA', 'dev')
START_TIME = datetime.now(timezone.utc)
EMBED_COLOR = 0x4e9e4e
