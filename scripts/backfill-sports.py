import json,urllib.request,datetime,concurrent.futures as cf,sys,time
B='https://app2.matchday-backend.com/api'
UA={'User-Agent':'Mozilla/5.0','Accept':'application/json','Content-Type':'application/json'}
today=datetime.date(2026,8,5)
DATES=[(today+datetime.timedelta(days=i)).isoformat() for i in range(-56,15)]
def slots(cid,date,pid,tries=3):
    for a in range(tries):
        try:
            r=urllib.request.Request(f'{B}/courts/{cid}/slots',data=json.dumps({'date':date,'providerId':str(pid)}).encode(),headers=UA,method='POST')
            with urllib.request.urlopen(r,timeout=25) as f: return json.load(f)
        except Exception:
            if a==tries-1: return None
            time.sleep(1+a)
vs=[v for v in json.load(open('sports_resolved.json')) if v.get('groups')]
meta=[];jobs=[]
for v in vs:
    bysport={}
    for g in v['groups']: bysport.setdefault(g['sport'],[]).append(g)
    for sport,gs in bysport.items():
        vi=len(meta)
        pr=sorted({g['price'] for g in gs if g['price']})
        meta.append({'venue':v['name'],'district':v['loc'].split(',')[0].strip(),'prov':v['loc'].split(',')[-1].strip(),
                     'sport':sport,'courts':sum(g['n'] for g in gs),
                     'price':pr[0] if len(pr)==1 else (f"{pr[0]}–{pr[-1]}" if pr else None),
                     'open':gs[0]['open'],'close':gs[0]['close'],'cid':v['contextId']})
        for g in gs:
            for d in DATES: jobs.append((vi,g['id'],g['n'],d))
print('rows',len(meta),'jobs',len(jobs),file=sys.stderr)
res={}
def work(j):
    vi,gid,gc,d=j
    return (vi,d,gc,slots(gid,d,meta[vi]['cid']))
done=0
with cf.ThreadPoolExecutor(8) as ex:
    for vi,d,gc,ss in ex.map(work,jobs):
        done+=1
        if done%300==0: print('done',done,file=sys.stderr)
        if ss is None: continue
        b=res.setdefault((vi,d),{})
        for s in ss:
            try: h=int(str(s['start'])[:2])
            except Exception: continue
            e=b.setdefault(h,[0,0]); e[0]+=len(s.get('availableCourts') or []); e[1]+=gc
def windows(b):
    def pct(hours):
        f=sum(b[h][0] for h in b if h in hours); dn=sum(b[h][1] for h in b if h in hours)
        return None if dn==0 else round((dn-f)/dn*100)
    return {'e':pct(set(range(18,22))),'d':pct(set(range(10,17))),'a':pct(set(b)),
            'bh':{str(h):round((b[h][1]-b[h][0])/b[h][1]*100) for h in sorted(b) if b[h][1]}}
# merge into history.json with sport keys
H='/Users/gearsecond/badminton-court-plan/data/history.json'
hist=json.load(open(H))
for v in hist['venues']: v.setdefault('sport','badminton')
key={(v['venue'],v['sport']):v for v in hist['venues']}
for vi,m in enumerate(meta):
    daymap={d:windows(res[(vi,d)]) for d in DATES if (vi,d) in res}
    k=(m['venue'],m['sport'])
    if k in key:
        key[k]['days'].update(daymap)
        key[k].update({'courts':m['courts'],'price':m['price']})
    else:
        v={'venue':m['venue'],'district':m['district'],'prov':m['prov'],'sport':m['sport'],
           'courts':m['courts'],'price':m['price'],'open':m['open'],'close':m['close'],'days':daymap}
        hist['venues'].append(v); key[k]=v
dl=sorted({d for v in hist['venues'] for d in v['days']})
hist['first'],hist['last']=dl[0],dl[-1]
json.dump(hist,open(H,'w'),ensure_ascii=False,separators=(',',':'))
import os
bysp={}
for v in hist['venues']: bysp.setdefault(v['sport'],[0,0]); bysp[v['sport']][0]+=1; bysp[v['sport']][1]+=v['courts']
print('WROTE',os.path.getsize(H),'bytes'); print(json.dumps(bysp,ensure_ascii=False))
