"""Persistent scheduler; exits on configuration failures, logs scan failures."""
import datetime as dt
import os
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Tokyo')
INTERVAL_MINUTES = int(os.getenv('INTERVAL_MINUTES', '30'))
if INTERVAL_MINUTES < 30:
    raise ValueError('INTERVAL_MINUTES must be at least 30')

while True:
    now = dt.datetime.now(TZ)
    print(f'[{now.isoformat()}] starting scan', flush=True)
    result = subprocess.run([sys.executable, 'monitor.py'], check=False)
    print(f'[{dt.datetime.now(TZ).isoformat()}] scan exit={result.returncode}', flush=True)
    if result.returncode and os.getenv('STOP_ON_ERROR', '1') == '1':
        raise SystemExit(result.returncode)
    time.sleep(INTERVAL_MINUTES * 60)
