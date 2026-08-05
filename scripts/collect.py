#!/usr/bin/env python3
"""Daily occupancy collector for the badminton project.

Reads data/venues.json (Matchday slugs), sweeps a rolling date window
(-2 days .. +14 days), merges results into data/history.json, and rewrites
data/market-latest.json + data/booking-latest.json for the site cards.
Stdlib only. Run from the repo root:  python3 scripts/collect.py
"""
import json,os,re,sys,time,datetime,statistics as st
import urllib.request,urllib.parse,http.cookiejar
import concurrent.futures as cf
from zoneinfo import ZoneInfo

BKK=ZoneInfo('Asia/Bangkok')
NOWDT=datetime.datetime.now(BKK)
NOW=NOWDT.strftime('%F %H:%M')
TODAY=NOWDT.date()
CURH=NOWDT.hour
DATES=[(TODAY+datetime.timedelta(days=i)).isoformat() for i in range(-2,15)]
THWD=['จันทร์','อังคาร','พุธ','พฤหัส','ศุกร์','เสาร์','อาทิตย์']

B='https://app2.matchday-backend.com/api'
UA={'User-Agent':'Mozilla/5.0','Accept':'application/json','Content-Type':'application/json'}
EVE=set(range(18,22)); DAY=set(range(10,17))

def get(u,tries=3):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=25) as f:
                return json.load(f)
        except Exception:
            if a==tries-1: raise
            time.sleep(1+a)

def slots(cid,date,pid,tries=3):
    for a in range(tries):
        try:
            r=urllib.request.Request(f'{B}/courts/{cid}/slots',
                data=json.dumps({'date':date,'providerId':str(pid)}).encode(),headers=UA,method='POST')
            with urllib.request.urlopen(r,timeout=25) as f: return json.load(f)
        except Exception:
            if a==tries-1: return None
            time.sleep(1+a)

def pct_windows(bucket):
    def pct(hours):
        f=sum(bucket[h][0] for h in bucket if h in hours)
        dn=sum(bucket[h][1] for h in bucket if h in hours)
        return None if dn==0 else round((dn-f)/dn*100)
    return {'e':pct(EVE),'d':pct(DAY),'a':pct(set(bucket)),
            'bh':{str(h):round((bucket[h][1]-bucket[h][0])/bucket[h][1]*100) for h in sorted(bucket) if bucket[h][1]}}

# ---------------- Matchday sweep ----------------
reg=json.load(open('data/venues.json'))['venues']
meta=[];jobs=[]
errs=[]
for v in reg:
    try:
        a=get(f'{B}/affiliate/{urllib.parse.quote(v["slug"])}')
        cid=a['contextId']
        courts=get(f'{B}/providers/{cid}/courts')
    except Exception as e:
        errs.append(f'{v["slug"]}: {e}'); continue
    SPMAP={'แบดมินตัน':'badminton','เทนนิส':'tennis','พิคเคิล':'pickleball','บาสเกตบอล':'basketball'}
    bysport={}
    for c in courts:
        if not (c.get('physicalCourts') or []): continue
        sp=next((v2 for k,v2 in SPMAP.items() if k in (c.get('sport') or '')),None)
        if sp: bysport.setdefault(sp,[]).append(c)
    bas=bysport.get('basketball',[])
    for sport,grp in bysport.items():
        pr=sorted({c.get('pricePerHour') for c in grp if c.get('pricePerHour')})
        vi=len(meta)
        meta.append({'venue':v['name'],'district':v['district'],'prov':v['prov'],'sport':sport,
                     'courts':sum(len(c['physicalCourts']) for c in grp),
                     'price':pr[0] if len(pr)==1 else (f'{pr[0]}–{pr[-1]}' if pr else None),
                     'open':grp[0].get('openTime'),'close':grp[0].get('closeTime'),
                     'cid':cid,'slug':v['slug'],
                     'bas':[(c['id'],len(c['physicalCourts'])) for c in bas] if sport=='basketball' else []})
        for c in grp:
            gc=len(c['physicalCourts'])
            for d in DATES: jobs.append((vi,c['id'],gc,d))

res={}
def work(j):
    vi,gid,gc,d=j
    return (vi,d,gc,slots(gid,d,meta[vi]['cid']))
with cf.ThreadPoolExecutor(6) as ex:
    for vi,d,gc,ss in ex.map(work,jobs):
        if ss is None: continue
        b=res.setdefault((vi,d),{})
        for s in ss:
            try: h=int(str(s['start'])[:2])
            except Exception: continue
            e=b.setdefault(h,[0,0])
            e[0]+=len(s.get('availableCourts') or []); e[1]+=gc

# Winning basketball (for the 4-venue card)
bas_bucket={}
for m in meta:
    if m['slug']=='winning' and m['bas']:
        for gid,gc in m['bas']:
            for d in (TODAY.isoformat(),(TODAY+datetime.timedelta(days=1)).isoformat()):
                ss=slots(gid,d,m['cid'])
                if ss is None: continue
                b=bas_bucket.setdefault(d,{})
                for s in ss:
                    try: h=int(str(s['start'])[:2])
                    except Exception: continue
                    e=b.setdefault(h,[0,0])
                    e[0]+=len(s.get('availableCourts') or []); e[1]+=gc

# ---------------- BEAT via okrabook ----------------
beat={}
try:
    cj=http.cookiejar.CookieJar()
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders=[('User-Agent','Mozilla/5.0 (Macintosh) AppleWebKit/537.36')]
    DURL='https://beatdiscovery.okrabook.com/venues/detail/BEAT%20Discovery'
    tok=re.search(r'name="csrf-token" content="([^"]+)"',op.open(DURL,timeout=30).read().decode()).group(1)
    for d in DATES:
        try:
            body=urllib.parse.urlencode({'id':'1','sport_id':'8','date':d}).encode()
            r=urllib.request.Request('https://beatdiscovery.okrabook.com/venues/getTimes',data=body,
                headers={'X-CSRF-TOKEN':tok,'X-Requested-With':'XMLHttpRequest',
                         'Content-Type':'application/x-www-form-urlencoded','Referer':DURL})
            j=json.load(op.open(r,timeout=30))
            if j.get('status')!=1: continue
            have={int(x['id'])//3600%24:len(x['spaces']) for x in (j.get('times') or {}).values()}
            # okrabook omits sold-out hours (and, for today, past hours). Grid = 7..21.
            b={}
            for h in range(7,22):
                if d==TODAY.isoformat() and h<CURH: continue
                b[h]=[have.get(h,0),16]
            if b: beat[d]=b
        except Exception: pass
        time.sleep(0.3)
except Exception as e:
    errs.append(f'BEAT: {e}')

# ---------------- merge into history.json ----------------
hist={'generated':NOW,'today':TODAY.isoformat(),'venues':[]}
if os.path.exists('data/history.json'):
    hist=json.load(open('data/history.json'))
hist['generated']=NOW; hist['today']=TODAY.isoformat()
for v in hist['venues']: v.setdefault('sport','badminton')
byname={(v['venue'],v['sport']):v for v in hist['venues']}
def upsert(name,sport,info,daymap):
    v=byname.get((name,sport))
    if v is None:
        v={'venue':name,'sport':sport,**info,'days':{}}
        hist['venues'].append(v); byname[(name,sport)]=v
    else:
        v.update(info)
    v['days'].update(daymap)
for vi,m in enumerate(meta):
    daymap={}
    for d in DATES:
        b=res.get((vi,d))
        if b: daymap[d]=pct_windows(b)
    upsert(m['venue'],m['sport'],{'district':m['district'],'prov':m['prov'],'courts':m['courts'],
                       'price':m['price'],'open':m['open'],'close':m['close']},daymap)
upsert('BEAT Discovery','badminton',{'district':'พระโขนง (สุขุมวิท 66)','prov':'กรุงเทพมหานคร','courts':16,
                         'price':'250–350','open':'7:00','close':'22:00','src':'okrabook'},
       {d:pct_windows(b) for d,b in beat.items()})
dl=sorted({d for v in hist['venues'] for d in v['days']})
hist['first'],hist['last']=dl[0],dl[-1]
json.dump(hist,open('data/history.json','w'),ensure_ascii=False,separators=(',',':'))

# ---------------- market-latest.json ----------------
TMR=(TODAY+datetime.timedelta(days=1)).isoformat()
live=[]
excluded=[]
for v in hist['venues']:
    if v.get('sport','badminton')!='badminton': continue
    t=v['days'].get(TODAY.isoformat()); m=v['days'].get(TMR)
    if not t: continue
    dead=(t.get('a')==0) and (not m or m.get('a')==0)
    row={'venue':v['venue'],'district':v['district'],'prov':v['prov'],'courts':v['courts'],
         'price':v['price'],'open':v['open'],'close':v['close'],
         'eve':t.get('e'),'day':t.get('d'),'all':t.get('a'),
         'eve_tmr':m.get('e') if m else None,
         'byhour':{k:vv for k,vv in t.get('bh',{}).items()},'dead':dead}
    if v.get('src'): row['src']=v['src']
    if dead: excluded.append(v['venue'])
    else: live.append(row)
def med(f):
    x=[f(r) for r in live if f(r) is not None]
    return round(st.median(x),1) if x else None
agg={}
for r in live:
    for hh,pp in r['byhour'].items(): agg.setdefault(int(hh),[]).append(pp)
hourly=[{'h':h,'median':round(st.median(x),1),'n':len(x)} for h,x in sorted(agg.items()) if len(x)>=5]
prices=[r['price'] for r in live if isinstance(r['price'],int)]
market={'collected':NOW,'weekday':THWD[TODAY.weekday()],
        'n_venues':len(live),'n_courts':sum(r['courts'] for r in live),
        'n_excluded':len(excluded),'excluded':excluded,
        'median':{'eve':med(lambda r:r['eve']),'eve_tmr':med(lambda r:r['eve_tmr']),
                  'day':med(lambda r:r['day']),'all':med(lambda r:r['all']),
                  'courts':med(lambda r:r['courts']),'price':round(st.median(prices)) if prices else None},
        'hourly':hourly,
        'venues':sorted(live,key=lambda r:(-(r['eve'] or 0),-(r['day'] or 0)))}
json.dump(market,open('data/market-latest.json','w'),ensure_ascii=False,indent=1)
with open('data/market-log.jsonl','a') as f:
    f.write(json.dumps({'ts':NOW,'n_venues':market['n_venues'],'n_courts':market['n_courts'],
                        'median':market['median'],'hourly':hourly},ensure_ascii=False)+'\n')

# ---------------- booking-latest.json (4-venue card) ----------------
def card(name,label,courts,daymapT,daymapM):
    t=daymapT; m=daymapM
    if not t: return {'venue':label,'error':'no data'}
    full=[]
    for hh,pp in sorted(t.get('bh',{}).items(),key=lambda x:int(x[0])):
        if pp==100: full.append(hh)
    return {'venue':label,'courts':courts,'date':TODAY.isoformat(),
            'evening_pct':t.get('e'),'daytime_pct':t.get('d'),
            'full_from_to':f'{full[0]}:00–{int(full[-1])+1}:00' if full else '',
            'tomorrow_evening_pct':m.get('e') if m else None}
def days_of(name,sport='badminton'):
    v=byname.get((name,sport),{});return v.get('days',{}).get(TODAY.isoformat()),v.get('days',{}).get(TMR)
ccT,ccM=days_of('CC Badminton Court')
wT,wM=days_of('Winning Badminton & Basketball')
bT,bM=days_of('BEAT Discovery')
basT=pct_windows(bas_bucket[TODAY.isoformat()]) if TODAY.isoformat() in bas_bucket else None
basM=pct_windows(bas_bucket[TMR]) if TMR in bas_bucket else None
book={'updated':NOW,
 'note':'เย็น = 18:00–22:00 · กลางวัน = 10:00–17:00 · ดึงตรงจากระบบจองของแต่ละสนาม (CC/Winning = Matchday · BEAT = Okrabook)',
 'snapshots':[card('cc','CC Badminton',18,ccT,ccM),
              card('w','Winning แบด',16,wT,wM),
              card('wb','Winning บาสครึ่งคอร์ท',2,basT,basM),
              card('beat','BEAT Discovery',16,bT,bM)]}
json.dump(book,open('data/booking-latest.json','w'),ensure_ascii=False)
with open('data/booking-log.jsonl','a') as f:
    for s in book['snapshots']:
        f.write(json.dumps({'ts':NOW,**s},ensure_ascii=False)+'\n')

# ---------------- summary ----------------
md=market['median']
print(f"เก็บสำเร็จ {market['n_venues']} สนาม {market['n_courts']} คอร์ท ({len(DATES)} วัน: -2 ถึง +14)")
print(f"ค่ากลางวันนี้ ({market['weekday']}): เย็น {md['eve']}% · กลางวัน {md['day']}% · ทั้งวัน {md['all']}% · จองล่วงหน้าพรุ่งนี้ {md['eve_tmr']}%")
top=market['venues'][:3]; bot=market['venues'][-3:]
print('แน่นสุด:', ' · '.join(f"{r['venue']} {r['eve']}%" for r in top))
print('เบาสุด:', ' · '.join(f"{r['venue']} {r['eve']}%" for r in bot))
print('ตัดออก:', ', '.join(excluded) if excluded else '-')
bysp={}
for v in hist['venues']:
    sp=v.get('sport','badminton'); bysp.setdefault(sp,[0,0]); bysp[sp][0]+=1; bysp[sp][1]+=v['courts']
print('คลัง 4 กีฬา:', ' · '.join(f"{k} {n} สนาม/{c} คอร์ท" for k,(n,c) in sorted(bysp.items())))
if errs: print('ปัญหา:', ' | '.join(errs[:5]))
