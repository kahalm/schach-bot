"""Bot-Version (major.minor.bugfix) und Startzeitpunkt."""

import os
from datetime import datetime, timezone

VERSION = '2.78.11'
GIT_SHA = os.environ.get('GIT_SHA', 'dev')
GIT_REF = os.environ.get('GIT_REF', '')
START_TIME = datetime.now(timezone.utc)
EMBED_COLOR = 0x4e9e4e
