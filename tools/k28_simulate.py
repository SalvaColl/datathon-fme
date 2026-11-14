"""Deterministic transport-only toy simulation. No network, models or submissions.

Uses the real request buffer; timing/event scheduling is simplified. No claim of
hidden conversion or real-world reliability. Both modes see the same arrivals and
absolute-time network profile. POST acknowledgement is twice delivery delay here.
"""
import heapq
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from recsys.prefetch import RequestReader


def percentile(values,q):
    if not values: return None
    v=sorted(values); x=(len(v)-1)*q; i=int(x)
    return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)


def simulate(mode,scenario='steady',duration=120,rate=3):
    clock=[0.]; events=[]; seq=[0]; busy=[False]
    buffer=RequestReader(lambda:[],now=lambda:clock[0])
    pending={}; seen=set(); delivered={}; attempts={}; reads=[0]
    def event(t,kind,payload=None):
        seq[0]+=1; heapq.heappush(events,(t,seq[0],kind,payload))
    def latency(kind,t):
        base={'steady':(.4,.7),'slower':(.9,.8),'jitter':(.45,.6),'outage':(.4,.7)}[scenario][kind=='post']
        if scenario=='jitter' and 9 <= t%20 < 11: base+=1.0
        if scenario=='outage' and t<44 and t+base>40: base+=44-max(t,40)
        return base
    def poll(t):
        if t>duration+8: return
        delay=latency('poll',t)
        event(t+delay,'read',t+delay/2)
        reads[0]+=1
    def work(t):
        if busy[0]: return
        todo=sorted((i for i in pending if i not in seen),key=lambda i:i/rate)
        for i in todo:
            if t-i/rate>2.5: seen.add(i); pending.pop(i,None)
        todo=[i for i in todo if i not in seen][:4]
        if not todo:
            if mode=='serial': poll(t+.1)
            return
        busy[0]=True
        delay=0. if t-todo[0]/rate>=1.8 else .01
        event(t+delay,'write',todo)
    poll(0.)
    while events:
        t,_,kind,payload=heapq.heappop(events); clock[0]=t
        if kind=='read':
            last=min(int(payload*rate),int(duration*rate)-1)
            records=[dict(request_id=str(i),ts=datetime.fromtimestamp(i/rate,timezone.utc).isoformat()) for i in range(max(0,last-59),last+1)]
            buffer.offer(records)
            for r in buffer.take(0):
                i=int(r['request_id'])
                if i not in seen: pending[i]=r
            if mode=='k28': poll(t)
            work(t)
        elif kind=='write':
            ids=[i for i in payload if t-i/rate<=2.5]
            for i in payload: seen.add(i); pending.pop(i,None)
            if not ids:
                busy[0]=False; work(t); continue
            delay=latency('post',t)
            for i in ids:
                attempts[i]=attempts.get(i,0)+1
                if t+delay/2-i/rate<=3: delivered[i]=t+delay/2-i/rate
            event(t+delay,'ack')
        else:
            busy[0]=False
            work(t)
    cohort=[i for i in range(int(duration*rate)) if 5<=i/rate<duration-5]
    ages=[delivered[i]*1000 for i in cohort if i in delivered]
    return dict(mode=mode,scenario=scenario,N=len(cohort),on_time=sum(i in delivered for i in cohort),
        on_time_pct=100*sum(i in delivered for i in cohort)/len(cohort),read_queries=reads[0],
        duplicate_attempts=sum(max(0,n-1) for n in attempts.values()),
        latency_ms={f'p{int(q*100)}':percentile(ages,q) for q in (.5,.95,.99)})


if __name__=='__main__':
    results=[simulate(mode,scenario) for scenario in ('steady','slower','jitter','outage') for mode in ('serial','k28')]
    print(json.dumps(dict(evidence='SYNTHETIC ENGINEERING CHECK; not a live SLA estimate',results=results,
        limitations=['Assumed 3/sec arrivals, fixed/absolute-time latency profiles and half-RTT server receipt.',
        'No actual API limits, client socket timeouts, CPU contention, catalog refresh or persistent-journal costs.',
        'Overlap issues more read queries and can hurt if server/link contention dominates; must be measured on the actual host.',
        'Neither mode can meet deadlines through a long outage.']),indent=2))
