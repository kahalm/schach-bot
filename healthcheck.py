"""Docker HEALTHCHECK script.

Prueft ob config/health.json existiert und der Timestamp < 120s alt ist.
Exit 0 = healthy, Exit 1 = unhealthy.
"""

import json
import sys
import os
from datetime import datetime, timezone

HEALTH_FILE = os.path.join('config', 'health.json')
MAX_AGE_SECONDS = 120


def main():
    try:
        with open(HEALTH_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f'UNHEALTHY: {e}')
        return 1

    ts_str = data.get('ts')
    if not ts_str:
        print('UNHEALTHY: kein Timestamp')
        return 1

    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        print(f'UNHEALTHY: ungültiger Timestamp {ts_str!r}')
        return 1

    age = (datetime.now(timezone.utc) - ts).total_seconds()
    if age > MAX_AGE_SECONDS:
        print(f'UNHEALTHY: {age:.0f}s alt (max {MAX_AGE_SECONDS}s)')
        return 1

    version = data.get('version', '?')
    latency = data.get('latency_ms', '?')
    print(f'healthy: v{version}, latency={latency}ms, age={age:.0f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
