#!/usr/bin/env python3
"""ns-3 congestion research runner / offline evaluator.
IMPORTANT: Offline ML predictions are NOT closed-loop predictive ECN control.
Requires Python stdlib; optional numpy/scikit-learn/matplotlib for ML and graphs.
"""
import argparse, csv, json, math, os, pathlib, shutil, statistics, subprocess, sys, time
from collections import defaultdict
ROOT=pathlib.Path(__file__).resolve().parent
FILES={'queue':'bursty-queue.dat','ecn':'bursty-ecn.dat','fct':'bursty-short-fct.dat','pred':'bursty-predictions.dat','cwnd':'bursty-cwnd.dat','cc':'bursty-cc-response.dat','drops':'bursty-drops.dat','retrans':'bursty-retransmissions.dat','rx':'bursty-short-flow-rx.dat'}
def rows(path):
    p=pathlib.Path(path)
    if not p.exists(): return []
    out=[]
    for line in p.read_text(errors='replace').splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        a=line.split()
        try: out.append([float(x) if (i==0 or x.replace('.','',1).replace('-','',1).isdigit()) else x for i,x in enumerate(a)])
        except ValueError: continue
    return out
def pct(a,p):
    if not a:return None
    x=sorted(a); k=(len(x)-1)*p/100; lo=math.floor(k); hi=math.ceil(k)
    return x[lo]*(hi-k)+x[hi]*(k-lo) if hi!=lo else x[lo]
def events(pred,queue,horizon=0.005,threshold=20):
    # Episodes: rising threshold crossings, one true positive per episode.
    q=sorted([(r[0],r[1]) for r in queue if len(r)>1])
    starts=[t for j,(t,v) in enumerate(q) if v>=threshold and (j==0 or q[j-1][1]<threshold)]
    alerts=sorted(r[0] for r in pred if len(r)>4 and r[4]>=0.5)
    matched=set(); true=0; leads=[]
    for a in alerts:
        for j,t in enumerate(starts):
            if j not in matched and a<t<=a+horizon+1e-12:
                matched.add(j);true+=1;leads.append(1000*(t-a));break
    return {'episodes':len(starts),'alerts':len(alerts),'matched_events':len(matched),'precision_per_alert':true/len(alerts) if alerts else None,'recall_per_episode':len(matched)/len(starts) if starts else None,'warning_lead_ms_median':pct(leads,50),'caveat':'Sampled instantaneous queue crossing; not RED averaged queue or a demonstrated control action'}
def analyze(directory):
    d=pathlib.Path(directory); x={k:rows(d/v) for k,v in FILES.items()}
    q=x['queue']; f=x['fct']; t=[r[3] for r in f if len(r)>=5 and isinstance(r[3],float)]; rx=[r[4] for r in f if len(r)>=5]
    stop=max([r[0] for r in q]+[r[2] for r in f if len(r)>2]+[0]); start=min([r[0] for r in q]+[r[1] for r in f if len(r)>1]+[0]); duration=max(stop-start,0)
    pred=x['pred']; target=pred[0][5] if pred and len(pred[0])>5 else 20; horizon=(pred[0][6]/1000) if pred and len(pred[0])>6 else 0.005
    summary={'directory':str(d),'files_present':{k:(d/v).exists() for k,v in FILES.items()},'queue_sample_count':len(q),'queue_mean_packets':statistics.mean(r[1] for r in q) if q else None,'queue_max_packets':max([r[1] for r in q],default=None),'ecn_event_rows':len(x['ecn']),'ecn_packet_count_not_validated':len(x['ecn']),'short_flow_count':len(t),'short_fct_mean_ms':statistics.mean(t) if t else None,'short_fct_median_ms':pct(t,50),'short_fct_p95_ms':pct(t,95),'short_fct_p99_ms':pct(t,99),'short_fct_max_ms':max(t,default=None),'short_flow_delivered_bytes':sum(rx),'short_flow_aggregate_goodput_mbps_over_observation_window':8*sum(rx)/duration/1e6 if duration else None,'cwnd_events':len(x['cwnd']),'drop_event_rows':len(x['drops']),'retransmission_event_rows':len(x['retrans']),'predictor':events(pred,q,horizon,target) if pred and q else None,'limitations':['The ECN event count is trace-row count, not independently checked mark count','Goodput is short-flow bytes divided by overall observed window, not sum of per-flow rates','Fairness requires validated per-sender delivered-byte/throughput counters','A retrospective prediction file cannot establish a control benefit','One run cannot establish statistical superiority']}
    return summary

def write_csv(path,records):
    if not records:return
    keys=list(dict.fromkeys(k for row in records for k in row))
    with open(path,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(records)

def make_plots(d,out):
    try: import matplotlib.pyplot as plt
    except ImportError: print('matplotlib missing: skipping figures');return
    q=rows(d/FILES['queue']); e=rows(d/FILES['ecn']); p=rows(d/FILES['pred']); cw=rows(d/FILES['cwnd']); f=rows(d/FILES['fct'])
    if q:
        fig,ax=plt.subplots(figsize=(11,4));ax.plot([r[0] for r in q],[r[1] for r in q],lw=1,label='Queue (sampled)')
        for i,r in enumerate(e):ax.axvline(r[0],alpha=.07,lw=.35,label='ECN event' if i==0 else None)
        ap=[r[0] for r in p if len(r)>4 and r[4]>.5]
        if ap:ax.scatter(ap,[max(0,next((r[1] for r in q if r[0]>=z),0)) for z in ap],s=5,label='Trend alert')
        ax.set(xlabel='Simulation time (s)',ylabel='Queue occupancy (packets)',title='Queue occupancy, ECN trace rows, and trend alerts');ax.legend();fig.tight_layout();fig.savefig(out/'queue_ecn_alerts.png',dpi=170);plt.close(fig)
    if cw:
        fig,ax=plt.subplots(figsize=(11,4));series=defaultdict(list)
        for r in cw:
            if len(r)>=4:series[str(r[1])].append((r[0],r[3]))
        for sender,xx in series.items():ax.plot([z[0] for z in xx],[z[1] for z in xx],label=sender,lw=1)
        ax.set(xlabel='Simulation time (s)',ylabel='Congestion window (bytes)',title='Observed sender congestion-window changes');ax.legend();fig.tight_layout();fig.savefig(out/'cwnd.png',dpi=170);plt.close(fig)
    if f:
        fig,ax=plt.subplots(figsize=(8,4));ax.hist([r[3] for r in f if len(r)>3],bins=min(15,max(3,len(f)//2)));ax.set(xlabel='Short-flow FCT (ms)',ylabel='Number of flows',title='Short-flow FCT distribution');fig.tight_layout();fig.savefig(out/'fct_histogram.png',dpi=170);plt.close(fig)

def collected(args):
    output=pathlib.Path(args.output);output.mkdir(parents=True,exist_ok=True)
    records=[]
    for p in args.directories:
        s=analyze(p);records.append({k:v for k,v in s.items() if not isinstance(v,(dict,list))});(output/(pathlib.Path(p).name+'_summary.json')).write_text(json.dumps(s,indent=2))
        sub=output/pathlib.Path(p).name;sub.mkdir(exist_ok=True);make_plots(pathlib.Path(p),sub)
        print(json.dumps({k:v for k,v in s.items() if k in ('directory','short_flow_count','short_fct_median_ms','short_fct_p95_ms','queue_mean_packets','ecn_event_rows')},indent=2))
    write_csv(output/'run_summaries.csv',records)

def runbatch(args):
    ns=pathlib.Path(args.ns3).expanduser().resolve();script=ns/'ns3'
    if not script.exists():sys.exit('ERROR: ns-3 runner missing: '+str(script))
    root=pathlib.Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    configs={'standard':(args.minth,args.maxth),'lower_fixed':(args.lower_minth,args.lower_maxth)}
    if args.mode in ('trend_closed_loop','ml_closed_loop'):
        sys.exit('CLOSED-LOOP MODE DISABLED: cannot activate until the attached C++ source implements a verified packet-control action. Offline alerts are not control.')
    for name,(mn,mx) in configs.items():
        if mn>=mx or mn<0:sys.exit('Invalid thresholds for '+name)
        for seed in range(args.first_run,args.first_run+args.runs):
            dst=root/f'{name}_seed{args.seed}_run{seed}'
            if dst.exists():sys.exit(f'Run dir already exists, refusing overwrite: {dst}')
            dst.mkdir();cmd=[str(script),'run',f'{args.program} --enableSwitchEcn=1 --minTh={mn} --maxTh={mx} --delAckTimeoutMs={args.delack} --RngSeed={args.seed} --RngRun={seed}']
            (dst/'command.json').write_text(json.dumps({'argv':cmd,'source_version':'USER LOCAL SOURCE -- NOT VERIFIED','mode':name,'thresholds':[mn,mx],'seed':args.seed,'run':seed,'time':time.strftime('%Y-%m-%d %H:%M:%S')},indent=2))
            # ns-3 writes output in current directory; program is resolved in ns3 root.
            print('Running',name,seed,flush=True)
            with (dst/'run.log').open('w') as log:
                process=subprocess.run(cmd,cwd=dst,stdout=log,stderr=subprocess.STDOUT)
            # ns-3 wrapper may require cwd in ns3 root; error is preserved, never hidden.
            missing=[v for k,v in FILES.items() if k in ('queue','ecn','fct') and not (dst/v).exists()]
            (dst/'status.json').write_text(json.dumps({'returncode':process.returncode,'missing_required':missing},indent=2))
            if process.returncode or missing:print('RUN INCOMPLETE',dst, 'code',process.returncode,'missing',missing,flush=True)
    print('Batch finished; use analyze on successful run directories.')

def train(args):
    try:import numpy as np
    except ImportError:sys.exit('For model training: pip install numpy scikit-learn')
    try:from sklearn.linear_model import LogisticRegression
    except ImportError:sys.exit('For model training: pip install scikit-learn')
    # Derive features at observation t only: queue, 1/3/5-sample trend, rolling mean,
    # and past queue deviations. Future queue labels are constructed ONLY within the same run.
    sample=[];groups=[]
    for folder in args.directories:
        q=rows(pathlib.Path(folder)/FILES['queue']);q=[(r[0],r[1]) for r in q if len(r)>=2]
        if len(q)<30:continue
        X=[];Y=[];times=[]
        for i in range(5,len(q)):
            t,v=q[i]; fut=[z for tm,z in q[i+1:] if tm<=t+args.horizon_ms/1000+1e-12]
            if not fut or v>=args.threshold:continue # forecast ONSET only, not sustained congestion
            X.append([v,v-q[i-1][1],(v-q[i-3][1])/3,(v-q[i-5][1])/5,sum(z for _,z in q[i-5:i+1])/6,max(z for _,z in q[i-5:i+1])-min(z for _,z in q[i-5:i+1])]);Y.append(int(max(fut)>=args.threshold));times.append(t)
        if X:groups.append((str(folder),X,Y,times))
    if len(groups)<3:sys.exit('At least THREE independent run directories needed: training/validation/test. A single queue file is not an independent ML experiment.')
    # Order randomized with fixed seed, partition by whole runs; test untouched during fitting.
    rng=np.random.default_rng(args.split_seed);idx=rng.permutation(len(groups)); n=len(idx); ntest=max(1,round(n*.2));nval=max(1,round(n*.2)); split={'test':idx[:ntest],'val':idx[ntest:ntest+nval],'train':idx[ntest+nval:]}
    if not len(split['train']):sys.exit('Insufficient independent training runs')
    def cat(which):return np.asarray(sum([groups[int(i)][1] for i in split[which]],[]),float),np.asarray(sum([groups[int(i)][2] for i in split[which]],[]),int)
    X,y=cat('train'); Xv,yv=cat('val'); Xt,yt=cat('test')
    if len(set(y))<2:sys.exit('Training labels contain only one class; vary workloads/threshold or collect more independent runs')
    mean=X.mean(axis=0);scale=X.std(axis=0);scale[scale==0]=1
    X=(X-mean)/scale;Xv=(Xv-mean)/scale;Xt=(Xt-mean)/scale
    model=LogisticRegression(max_iter=1000,class_weight='balanced',random_state=args.split_seed).fit(X,y)
    candidates=np.arange(.1,.91,.05)
    def pr(y,p,threshold):
        z=p>=threshold; tp=int(np.sum(z&(y==1)));fp=int(np.sum(z&(y==0)));fn=int(np.sum((~z)&(y==1)))
        return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0}
    pv=model.predict_proba(Xv)[:,1];chosen=max(candidates,key=lambda k:pr(yv,pv,k)['f1']); pt=model.predict_proba(Xt)[:,1]
    result={'label':'queue currently below threshold and a future sample reaches/exceeds threshold (onset), not packet loss','prediction_horizon_ms':args.horizon_ms,'queue_threshold_packets':args.threshold,'split_by_independent_runs':{k:[groups[int(i)][0] for i in v] for k,v in split.items()},'features':['q','delta1','slope3','slope5','mean_last6','range_last6'],'scaler_mean':mean.tolist(),'scaler_std':scale.tolist(),'logistic_coefficients':model.coef_[0].tolist(),'logistic_intercept':float(model.intercept_[0]),'validation_selected_probability_threshold':float(chosen),'validation':pr(yv,pv,chosen),'held_out_test':pr(yt,pt,chosen),'CAUTION':'Offline model evaluation only. No ns-3 inference or closed-loop control has been installed. Adjacent time samples are correlated; report run-level estimates.'}
    pathlib.Path(args.output).write_text(json.dumps(result,indent=2))
    model_txt=pathlib.Path(args.output).with_suffix('.model')
    model_txt.write_text('NS3_LOGISTIC_V1\n' +
        f'{args.horizon_ms:.12g} {args.threshold:.12g} {float(chosen):.17g} {float(model.intercept_[0]):.17g}\n' +
        ' '.join(f'{a:.17g}' for a in mean)+'\n' +
        ' '.join(f'{a:.17g}' for a in scale)+'\n' +
        ' '.join(f'{a:.17g}' for a in model.coef_[0])+'\n')
    print('NS3 inference model:',model_txt)
    print(json.dumps({'test':result['held_out_test'],'output':args.output},indent=2))

def fourway(args):
    """Sequentially run 4 configs, preserve every output; avoid optimistic success."""
    ns=pathlib.Path(args.ns3).expanduser().resolve()
    if not (ns/'ns3').exists():sys.exit('ns3 runner absent')
    out=pathlib.Path(args.output).resolve()
    if out.exists():sys.exit(f'Refusing overwrite existing batch: {out}')
    existing=list(ns.glob('bursty-*.dat'))
    if existing:sys.exit('Existing bursty-*.dat outputs in ns3 root: archive/move them before launching the batch to avoid mixing old and new results: '+', '.join(x.name for x in existing[:5]))
    out.mkdir(parents=True)
    model=pathlib.Path(args.ml_model).resolve() if args.ml_model else None
    choices=[('baseline',args.minth,args.maxth,'baseline'),
             ('lower_fixed',args.lower_minth,args.lower_maxth,'baseline'),
             ('trend',args.minth,args.maxth,'trend-hysteresis')]
    if model:
        if not model.exists():sys.exit(f'Model not found: {model}')
        choices.append(('ml_adapted',args.minth,args.maxth,'ml-adapted'))
    for name,mn,mx,mode in choices:
      for run in range(args.first_run,args.first_run+args.runs):
        dst=out/f'{name}_seed{args.seed}_run{run}';dst.mkdir()
        opts=f'{args.program} --controllerMode={mode} --enableSwitchEcn=1 --minTh={mn} --maxTh={mx} --earlyMinTh={args.lower_minth} --earlyMaxTh={args.lower_maxth} --minActiveMs={args.hold_ms} --releaseBelowPackets={args.release_below} --delAckTimeoutMs={args.delack} --predictorHorizonMs={args.horizon_ms} --RngSeed={args.seed} --RngRun={run}'
        if mode=='ml-adapted':opts+=f' --mlModelPath={model}'
        command=[str(ns/'ns3'),'run',opts]
        (dst/'command.json').write_text(json.dumps({'cmd':command,'mode':mode,'seed':args.seed,'run':run,'note':'EXPERIMENTAL: runtime RedQueueDisc::SetTh requires independent ECN semantics validation'},indent=2))
        print('RUN',name,run,flush=True)
        # ns3 launcher normally requires cwd root; moving outputs after each serial run prevents overwrites.
        with (dst/'run.log').open('w') as log:
          p=subprocess.run(command,cwd=ns,stdout=log,stderr=subprocess.STDOUT)
        files=list(ns.glob('bursty-*.dat'))
        for f in files:shutil.move(str(f),str(dst/f.name))
        missing=[f for f in ('bursty-queue.dat','bursty-ecn.dat','bursty-short-fct.dat') if not (dst/f).exists()]
        flowcount=len(rows(dst/'bursty-short-fct.dat'))
        markcount=len(rows(dst/'bursty-ecn.dat'))
        status={'returncode':p.returncode,'missing':missing,'completed_flows':flowcount,'ecn_trace_rows':markcount,'pass':p.returncode==0 and not missing and flowcount==24}
        (dst/'status.json').write_text(json.dumps(status,indent=2))
        if not status['pass']:print('FAILED OR INCOMPLETE',dst,status,flush=True)
    valid=[p for p in out.iterdir() if p.is_dir() and (p/'status.json').exists() and json.loads((p/'status.json').read_text()).get('pass')]
    if valid:
      summaries=[analyze(p) for p in valid]
      write_csv(out/'comparison.csv',summaries)
      (out/'comparison.json').write_text(json.dumps(summaries,indent=2))
      print('Comparison:',out/'comparison.csv')

def train_dirs(args):
    # training is separate from a final test batch; sources should be passive baseline runs only.
    args.directories=[str(p) for p in pathlib.Path(args.source).resolve().glob(args.glob) if p.is_dir() and (p/'bursty-queue.dat').exists()]
    if len(args.directories)<3:sys.exit('Need >=3 separate simulation runs for ML train/validate/test.')
    train(args)

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='action',required=True)
    a=s.add_parser('analyze');a.add_argument('directories',nargs='+');a.add_argument('--output',default='research_analysis');a.set_defaults(func=collected)
    r=s.add_parser('run');r.add_argument('--ns3',default='~/ns3/ns-3.47');r.add_argument('--program',default='bursty-dctcp-baseline');r.add_argument('--output',default='research_runs');r.add_argument('--minth',type=float,default=20);r.add_argument('--maxth',type=float,default=60);r.add_argument('--lower-minth',type=float,default=10);r.add_argument('--lower-maxth',type=float,default=30);r.add_argument('--seed',type=int,default=1);r.add_argument('--first-run',type=int,default=1);r.add_argument('--runs',type=int,default=7);r.add_argument('--delack',type=int,default=200);r.add_argument('--mode',choices=['reactive','trend_closed_loop','ml_closed_loop'],default='reactive');r.set_defaults(func=runbatch)
    m=s.add_parser('train');m.add_argument('directories',nargs='+');m.add_argument('--output',default='offline_model.json');m.add_argument('--horizon-ms',type=float,default=5);m.add_argument('--threshold',type=float,default=20);m.add_argument('--split-seed',type=int,default=123);m.set_defaults(func=train)
    k=s.add_parser('fourway');k.add_argument('--ns3',default='~/ns3/ns-3.47');k.add_argument('--program',default='bursty-dctcp-baseline');k.add_argument('--output',required=True);k.add_argument('--minth',type=float,default=20);k.add_argument('--maxth',type=float,default=60);k.add_argument('--lower-minth',type=float,default=10);k.add_argument('--lower-maxth',type=float,default=30);k.add_argument('--seed',type=int,default=1);k.add_argument('--first-run',type=int,default=101);k.add_argument('--runs',type=int,default=7);k.add_argument('--delack',type=int,default=200);k.add_argument('--horizon-ms',type=float,default=5);k.add_argument('--hold-ms',type=float,default=10);k.add_argument('--release-below',type=float,default=8);k.add_argument('--ml-model',default='');k.set_defaults(func=fourway)
    t=s.add_parser('train-batch');t.add_argument('--source',required=True);t.add_argument('--glob',default='baseline_*');t.add_argument('--output',default='ml_reference.json');t.add_argument('--horizon-ms',type=float,default=5);t.add_argument('--threshold',type=float,default=20);t.add_argument('--split-seed',type=int,default=123);t.set_defaults(func=train_dirs)
    args=p.parse_args();args.func(args)
if __name__=='__main__':main()
