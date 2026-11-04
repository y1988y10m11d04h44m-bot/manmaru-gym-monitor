"""Conservative scheduler: never tight-loop or crash-loop on scan failures."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Tokyo')
INTERVAL_MINUTES = int(os.getenv('INTERVAL_MINUTES', '30'))
if INTERVAL_MINUTES < 30:
    raise ValueError('INTERVAL_MINUTES must be at least 30')


def log(message):
    print(f'[{dt.datetime.now(TZ).isoformat()}] {message}', flush=True)


def preflight():
    if os.getenv('SITE_ACCESS_APPROVED') != 'yes':
        return 'SITE_ACCESS_APPROVED is not yes'
    try:
        config = json.loads((Path(__file__).parent / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return f'Invalid config: {exc}'
    if not config.get('site', {}).get('verified', False):
        return 'Live site adapter NOT validated (site.verified=false); no site requests made'
    if not config.get('site', {}).get('complete_scan_verified', False):
        return 'Complete scan NOT validated (site.complete_scan_verified=false); no site requests made'
    if os.getenv('DRY_RUN') != '1' and not (os.getenv('LINE_CHANNEL_ACCESS_TOKEN') and os.getenv('LINE_TO')):
        return 'LINE credentials missing; use DRY_RUN=1 for validation'
    return None


while True:
    reason = preflight()
    if reason:
        log(f'PAUSED: {reason}. Recheck after {INTERVAL_MINUTES} minutes')
    else:
        log('starting scan')
        try:
            result = subprocess.run([sys.executable, '-u', 'monitor.py'], check=False)
            log(f'scan exit={result.returncode}; next check after {INTERVAL_MINUTES} minutes')
        except Exception as exc:
            log(f'scan launch failed: {exc}; next check after {INTERVAL_MINUTES} minutes')
    time.sleep(INTERVAL_MINUTES * 60)
