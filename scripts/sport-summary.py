#!/usr/bin/env python3
"""Derive data/sport-summary.json from data/history.json.

Per sport: median evening / daytime / all-day occupancy across venues, using
only days the venue was actually open (>=6 hours returned). Venues whose
booking system is not really in use are dropped rather than averaged in:
a flat 0% means nobody books online there, a flat 100% means the courts are
not offered online at all. Run after scripts/collect.py.
"""
import json,statistics as st

MIN_HOURS=6      # fewer hours returned than this = the venue was closed that day
MIN_DAYS=3       # too little history to judge

def med(a):
    a=[x for x in a if x is not None]
    return round(st.median(a),1) if a else None

h=json.load(open('data/history.json'))
TODAY=h['today']
res={};excluded=[]
for sp in ['badminton','tennis','pickleball','basketball']:
    vs=[]
    for v in h['venues']:
        if v.get('sport','badminton')!=sp: continue
        od={d:x for d,x in v['days'].items() if d<=TODAY and len(x['bh'])>=MIN_HOURS}
        if len(od)<MIN_DAYS:
            excluded.append({'venue':v['venue'],'sport':sp,'why':'ข้อมูลยังน้อยเกินไป'}); continue
        m=med([x['a'] for x in od.values()])
        if m==0:
            excluded.append({'venue':v['venue'],'sport':sp,'why':'ระบบจองว่าง 0% ตลอด = ยังไม่ได้ใช้จริง'}); continue
        if m==100:
            excluded.append({'venue':v['venue'],'sport':sp,'why':'เต็ม 100% ตลอด = คอร์ทไม่ได้เปิดขายออนไลน์'}); continue
        vs.append((v,od))
    pr=[v['price'] for v,_ in vs if isinstance(v['price'],(int,float))]
    def agg(f): return med([med([x[f] for x in od.values() if x[f] is not None]) for v,od in vs])
    fut=sorted(d for d in {d for v,_ in vs for d in v['days']} if d>TODAY)[:14]
    def adv(d): return med([v['days'][d]['e'] for v,_ in vs if v['days'].get(d) and v['days'][d]['e'] is not None])
    res[sp]={'n':len(vs),'courts':sum(v['courts'] for v,_ in vs),
             'price':round(st.median(pr)) if pr else None,
             'e':agg('e'),'d':agg('d'),'a':agg('a'),
             'advance':[{'d':d,'e':adv(d)} for d in fut],
             'venues':sorted([{'venue':v['venue'],'district':v['district'],'courts':v['courts'],
                 'price':v['price'],
                 'e':med([x['e'] for x in od.values() if x['e'] is not None]),
                 'd':med([x['d'] for x in od.values() if x['d'] is not None]),
                 'a':med([x['a'] for x in od.values()])} for v,od in vs],
                 key=lambda x:-(x['a'] or 0))}
days=len([d for d in {d for v in h['venues'] for d in v['days']} if d<=TODAY])
json.dump({'generated':h['generated'],'first':h['first'],'today':TODAY,'days':days,
           'excluded':excluded,'sports':res},
          open('data/sport-summary.json','w'),ensure_ascii=False,indent=1)
for k,r in res.items():
    print(f"{k:11s} {r['n']:2d} สนาม {r['courts']:3d} คอร์ท  ฿{r['price']}  เย็น {r['e']}%  กลางวัน {r['d']}%  ทั้งวัน {r['a']}%")
print(f"ตัดออก {len(excluded)} รายการ · คลัง {days} วัน")
