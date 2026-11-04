# Per-room atomic updates; preserve state on failures and unpublished dates.
import datetime as dt
import hashlib,json,os,sqlite3,urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
import jpholiday
BASE=Path(__file__).parent
CONFIG=json.loads((BASE/'config.json').read_text(encoding='utf8'))
DB=Path(os.getenv('STATE_DB',str(BASE/'state.sqlite3')))
TODAY=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date()

def allowed(r):
    day=dt.date.fromisoformat(r['date']);start=dt.time.fromisoformat(r['start']);end=dt.time.fromisoformat(r['end'])
    mins=(dt.datetime.combine(day,end)-dt.datetime.combine(day,start)).total_seconds()/60
    return TODAY<=day<=TODAY+dt.timedelta(days=CONFIG['days_ahead']) and (day.weekday()>=5 or jpholiday.is_holiday(day)) and start>=dt.time(9) and end<=dt.time(17) and mins>=180 and r['status']=='○'

def send(msg):
    if os.getenv('DRY_RUN')=='1':print('DRY RUN:',msg);return
    token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'];to=os.environ['LINE_TO']
    payload=json.dumps({'to':to,'messages':[{'type':'text','text':msg[:4900]}]}).encode()
    req=urllib.request.Request('https://api.line.me/v2/bot/message/push',data=payload,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=20) as resp:resp.read()

def main():
    if os.getenv('SITE_ACCESS_APPROVED')!='yes':raise RuntimeError('Site access approval required')
    from site_adapter import read_slots
    report=read_slots(CONFIG)
    DB.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS slots (room TEXT, slot_key TEXT, date TEXT, active INTEGER, notified INTEGER, PRIMARY KEY(room,slot_key))')
    con.execute('CREATE TABLE IF NOT EXISTS baseline (room TEXT PRIMARY KEY, created_at TEXT)')
    for room,scan in report['targets'].items():
        dates=set(scan['days_seen']);rows=[r for r in scan['slots'] if allowed(r)]
        first=con.execute('SELECT 1 FROM baseline WHERE room=?',(room,)).fetchone() is None
        # In a transaction, update only dates successfully observed for this room.
        try:
            con.execute('BEGIN')
            active_keys=set()
            for r in rows:
                raw=json.dumps([room,r['date'],r['start'],r['end']],ensure_ascii=False)
                key=hashlib.sha256(raw.encode()).hexdigest();active_keys.add(key)
                old=con.execute('SELECT active,notified FROM slots WHERE room=? AND slot_key=?',(room,key)).fetchone()
                if old is None:con.execute('INSERT INTO slots VALUES (?,?,?,?,?)',(room,key,r['date'],1,1 if first else 0))
                elif not old[0]:con.execute('UPDATE slots SET active=1,notified=0 WHERE room=? AND slot_key=?',(room,key))
                if not first and (old is None or not old[0] or not old[1]):
                    msg=f'【体育館の空き】\n{r["facility"]}\n{r["date"]} {r["start"]}〜{r["end"]}\n{CONFIG["site"]["url"]}\n※予約可能か再確認してください。'
                    send(msg)
                    con.execute('UPDATE slots SET notified=1 WHERE room=? AND slot_key=?',(room,key))
            # Do not invalidate slots on unobserved dates or failed rooms.
            for key,date in con.execute('SELECT slot_key,date FROM slots WHERE room=? AND active=1',(room,)).fetchall():
                if date in dates and key not in active_keys:
                    con.execute('UPDATE slots SET active=0 WHERE room=? AND slot_key=?',(room,key))
            if first:con.execute('INSERT INTO baseline VALUES (?,?)',(room,dt.datetime.now(dt.timezone.utc).isoformat()))
            con.commit()
        except Exception:
            con.rollback();raise
        print(f'{scan["name"]}: {len(rows)} qualifying slots; published through {scan["last_date"]}',flush=True)
    for room,error in report['errors'].items():print(f'ERROR {room}: {error}',flush=True)
    con.close()
if __name__=='__main__':main()
