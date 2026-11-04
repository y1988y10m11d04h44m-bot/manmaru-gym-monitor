# Multi-function site adapter; live validation required.
import datetime as dt
import re
import time
from playwright.sync_api import sync_playwright

ERRORS=('パラメータエラー','リクエストパラメータに不正','接続エラー','upstream connect error','システムエラー')

def check(page):
    body=page.locator('body').inner_text(timeout=20000)
    if any(s in body for s in ERRORS):raise RuntimeError('Site error; preserve prior state')

def select_set(page,sel,value,button,next_sel=None):
    page.locator(sel).select_option(value=value)
    page.locator(button).click()
    check(page)
    if next_sel:page.locator(next_sel).wait_for(state='visible')

def enter(page,site,target,today):
    page.goto(site['url'],wait_until='domcontentloaded',timeout=site['timeout_ms'])
    if any(s in page.locator('body').inner_text() for s in ERRORS):
        ok=page.locator('#btnOK')
        if ok.count()==1:ok.click()
    check(page)
    if page.locator('#selectBunrui1').count()==0:
        multifunction=page.get_by_role('link',name='多機能操作')
        if multifunction.count()==1:multifunction.click()
        check(page)
        page.get_by_role('link',name='空き状況の確認',exact=True).click()
    check(page)
    select_set(page,'#selectBunrui1',target['city'],'#buttonSetBunrui1','#selectShisetsu')
    select_set(page,'#selectShisetsu',target['facility'],'#buttonSetShisetsu','#selectItem')
    select_set(page,'#selectItem','48','#buttonSetItem','#selectRoom')
    select_set(page,'#selectRoom',target['room'],'#buttonSetRoom')
    opts=page.locator('#YYYY option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,text:x.textContent.trim()}))')
    matches=[o for o in opts if o['value']==str(today.year) or o['text']==str(today.year) or o['value']==str(today.year-2018) or o['text']==str(today.year-2018)]
    if len(matches)!=1:raise RuntimeError(f'Year option not unique: {opts}')
    page.locator('#YYYY').select_option(matches[0]['value'])
    def choose(sel,num):
        loc=page.locator(sel)
        opts=loc.locator('option').evaluate_all('(xs)=>xs.map(x=>({v:x.value,t:x.textContent.trim()}))')
        match=[x for x in opts if x['v'] in (str(num),f'{num:02}') or x['t'] in (str(num),f'{num:02}')]
        if len(match)!=1:raise RuntimeError(f'Ambiguous date select {sel}: {opts}')
        loc.select_option(match[0]['v'])
    choose('#MM',today.month);choose('#DD',today.day)
    # No weekday filter: otherwise week pages may skip dates/holiday intersections.
    for i in range(1,9):
        btn=page.locator(f'#youbi_{i}')
        if 'btn-info' in (btn.get_attribute('class') or '').split():btn.click()
    page.locator('#btnOK[title="検索"]').click();check(page)
    facility_view=page.get_by_role('link',name='施設別',exact=True)
    if facility_view.count()==1:facility_view.click()
    check(page)
    page.locator('table th[id^="th"]').first.wait_for(timeout=site['timeout_ms'])

def parse_week(page,target,anchor,until):
    data=page.evaluate('''() => {
      const tables=[...document.querySelectorAll('table')].filter(t=>t.querySelector('th[id^="th"]'));
      return tables.map(t=>({
        headers:[...t.querySelectorAll('th[id^="th"]')].map(h=>({id:h.id,text:h.innerText.replace(/\s+/g,'')})),
        rows:[...t.querySelectorAll('tr')].map(tr=>({
          label:(tr.cells[0]?.innerText||'').trim(),
          cells:[...tr.querySelectorAll('td[id^="td"]')].filter(c=>getComputedStyle(c).display!=='none').map(c=>({id:c.id,cls:c.className,text:c.innerText.trim(),img:!!c.querySelector('img[src$="/timetable-o.gif"][title="O"]')}))
        })).filter(r=>r.cells.length)
      }));
    }''')
    if len(data)!=1:raise RuntimeError(f'Expected one room table, found {len(data)}')
    table=data[0]; headers={h['id'].split('_')[-1]:h['text'] for h in table['headers']}
    if not headers or not table['rows']:raise RuntimeError('No time headers or status rows')
    slots=[]; dates=[]
    for row in table['rows']:
        m=re.search(r'(\d{1,2})/(\d{1,2})\s*\(',row['label'])
        if not m:raise RuntimeError(f'Unexpected date row {row["label"]!r}')
        month,day=map(int,m.groups()); candidates=[]
        for year in range(anchor.year,until.year+1):
            try:d=dt.date(year,month,day)
            except ValueError:continue
            if anchor-dt.timedelta(days=7)<=d<=until+dt.timedelta(days=7):candidates.append(d)
        if len(candidates)!=1:raise RuntimeError(f'Ambiguous date {row["label"]}')
        date=candidates[0];dates.append(date)
        for cell in row['cells']:
            suffix=cell['id'].split('_')[-1]
            band=headers.get(suffix)
            if not band:raise RuntimeError(f'Missing time header for {cell["id"]}')
            open_=cell['img'] and 'ok' in cell['cls'].split()
            unavailable=bool(re.fullmatch(r'[ＸX×]',cell['text']))
            closed=cell['text']=='休館'
            if not (open_ or unavailable or closed):raise RuntimeError(f'Unknown status {cell}')
            if open_:
                tm=re.search(r'(\d{1,2}):(\d{2})[～〜~\-](\d{1,2}):(\d{2})',band)
                if not tm:raise RuntimeError(f'Unreadable time {band}')
                sh,sm,eh,em=map(int,tm.groups())
                slots.append(dict(facility=target['name'],room=target['room'],date=date.isoformat(),start=f'{sh:02}:{sm:02}',end=f'{eh:02}:{em:02}',status='○'))
    if dates!=sorted(set(dates)):raise RuntimeError('Dates not strictly increasing')
    return slots,dates

def read_slots(config):
    site=config['site']
    if not site.get('verified'):raise RuntimeError('Adapter disabled pending live validation')
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    until=today+dt.timedelta(days=config['days_ahead'])
    output={'targets':{},'errors':{}}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            context=browser.new_context(locale='ja-JP',timezone_id='Asia/Tokyo')
            page=context.new_page()
            for target in site['targets']:
                key=target['room'];slots=[];seen=set();last=None
                try:
                    enter(page,site,target,today)
                    for _ in range(site.get('max_week_pages',16)):
                        check(page)
                        rows,dates=parse_week(page,target,today,until)
                        if last is not None and min(dates)<=last:raise RuntimeError('Paging did not advance')
                        last=max(dates);seen.update(d for d in dates if today<=d<=until)
                        slots.extend(rows)
                        if last>=until:break
                        next_link=page.get_by_role('link',name='翌週',exact=True)
                        if next_link.count()==0:break # published horizon reached
                        if next_link.count()!=1:raise RuntimeError('Ambiguous next-week link')
                        next_link.click();time.sleep(site.get('delay_ms',2000)/1000)
                    if not seen:raise RuntimeError('No dates observed')
                    # Published days may end before 90-day horizon; record coverage explicitly.
                    output['targets'][key]={'name':target['name'],'slots':slots,'first_date':min(seen).isoformat(),'last_date':max(seen).isoformat(),'days_seen':sorted(d.isoformat() for d in seen)}
                except Exception as exc:
                    output['errors'][key]=str(exc)
                time.sleep(site.get('delay_ms',2000)/1000)
        finally:browser.close()
    if not output['targets']:raise RuntimeError(f'All targets failed: {output["errors"]}')
    return output
