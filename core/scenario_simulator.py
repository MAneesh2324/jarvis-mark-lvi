"""Reproducible hypothetical scenarios. No orders, scans or real system changes."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,math,uuid
import numpy as np
from core.mission_store import write_file
REPORTS=Path(__file__).resolve().parent.parent/'memory'/'scenarios'
LAST=REPORTS/'last-shown.json'
def number(value,name,low=None,high=None):
 try:result=float(value)
 except (ValueError,TypeError):raise ValueError(name+' must be a finite number.')
 if not math.isfinite(result) or low is not None and result<low or high is not None and result>high:raise ValueError(name+' is outside the allowed range.')
 return result
def integer(value,name,low,high):
 result=number(value,name,low,high)
 if result!=int(result):raise ValueError(name+' must be an integer.')
 return int(result)
def forex(start_rate,annual_return_percent,annual_volatility_percent,days=90,paths=1000,shock_percent=0,seed=42):
 start=number(start_rate,'Starting rate',.000001,1e9);mu=number(annual_return_percent,'Assumed annual return %',-100,100)/100
 sigma=number(annual_volatility_percent,'Assumed annual volatility %',0,300)/100;shock=number(shock_percent,'Immediate shock %',-95,1000)/100
 days=integer(days,'Trading days',1,2520);paths=integer(paths,'Paths',100,10000);seed=integer(seed,'Random seed',0,2**32-1)
 if days*paths>2_000_000:raise ValueError('Keep trading days × paths at or below 2,000,000.')
 rng=np.random.default_rng(seed);values=np.full(paths,start*(1+shock));peaks=np.maximum(start,values);drawdown=(peaks-values)/peaks
 steps=set(np.linspace(0,days,min(21,days+1),dtype=int));fan=[{'day':0,'p05':float(values[0]),'median':float(values[0]),'p95':float(values[0])}]
 dt=1/252
 for day in range(1,days+1):
  values*=np.exp((mu-.5*sigma*sigma)*dt+sigma*math.sqrt(dt)*rng.standard_normal(paths))
  peaks=np.maximum(peaks,values);drawdown=np.maximum(drawdown,(peaks-values)/peaks)
  if day in steps:
   a,b,c=np.percentile(values,[5,50,95]);fan.append({'day':day,'p05':float(a),'median':float(b),'p95':float(c)})
 percentiles=np.percentile(values,[5,50,95]);result={'kind':'forex','assumptions':{'start_rate':start,'annual_return_percent':mu*100,'annual_volatility_percent':sigma*100,'trading_days':days,'paths':paths,'immediate_shock_percent':shock*100,'seed':seed,'trading_days_per_year':252},'terminal_rate_p05':float(percentiles[0]),'terminal_rate_median':float(percentiles[1]),'terminal_rate_p95':float(percentiles[2]),'simulated_fraction_below_unshocked_start_percent':float(np.mean(values<start)*100),'median_path_max_drawdown_percent':float(np.median(drawdown)*100),'p95_path_max_drawdown_percent':float(np.percentile(drawdown,95)*100),'fan_chart':fan,'method':'Geometric Brownian motion with constant user-assumed drift/volatility, independent normal daily log-return shocks and an optional immediate shock.','limits':'Hypothetical model outcomes, not market probabilities or price predictions. No leverage, broker spreads, fees, liquidity, jumps, regimes or orders. Percentile bands are conditional simulation quantiles, not confidence guarantees.'}
 return result

def trade_stress(equity,units,pair_start,pair_move_percent,quote_to_account,spread_cost=0,slippage_cost=0,direction='long'):
 equity=number(equity,'Equity',.01,1e15);units=number(units,'Base units',0,1e15);rate=number(pair_start,'Starting quote/base rate',.000001,1e9)
 move=number(pair_move_percent,'Rate move %',-99,1000)/100;conversion=number(quote_to_account,'Quote-to-account conversion',.000001,1e9)
 if direction not in ('long','short'):raise ValueError('Choose long or short.')
 spread=number(spread_cost,'Spread cost in account currency',0,1e15);slippage=number(slippage_cost,'Slippage cost in account currency',0,1e15)
 gross=units*rate*move*conversion*(1 if direction=='long' else -1);net=gross-spread-slippage
 return {'kind':'trade_stress','assumptions':{'equity':equity,'units':units,'starting_rate':rate,'move_percent':move*100,'quote_to_account':conversion,'direction':direction,'spread_cost':spread,'slippage_cost':slippage},'gross_pnl_account_currency':gross,'net_pnl_account_currency':net,'equity_after_scenario':equity+net,'equity_change_percent':net/equity*100,'limits':'Single hypothetical mark-to-market move with fixed conversion and user-supplied costs. No broker order, stop guarantee, margin/liquidation model or trading recommendation.'}

def outage(requests_per_minute,outage_minutes,affected_percent,capacity_per_minute,retry_percent=0,backlog_before=0):
 arrival=number(requests_per_minute,'Requests/minute',0,1e9);minutes=number(outage_minutes,'Outage duration',0,100000)
 affected=number(affected_percent,'Affected %',0,100)/100;capacity=number(capacity_per_minute,'Recovery capacity/minute',0,1e10);retry=number(retry_percent,'Retry %',0,100)/100;prior=number(backlog_before,'Existing backlog',0,1e12)
 lost=arrival*minutes*affected;backlog=prior+lost*retry;spare=capacity-arrival
 clearance=0.0 if backlog==0 and spare>=0 else backlog/spare if spare>0 else None
 return {'kind':'outage','assumptions':{'normal_requests_per_minute':arrival,'outage_minutes':minutes,'affected_percent':affected*100,'post_recovery_capacity_per_minute':capacity,'failed_request_retry_percent':retry*100,'initial_backlog':prior},'failed_or_interrupted_requests':lost,'new_retries':lost*retry,'total_recovery_backlog':backlog,'spare_recovery_capacity_per_minute':spare,'estimated_backlog_clearance_minutes':clearance,'stable_recovery':spare>0 or backlog==0 and spare>=0,'method':'Deterministic fluid queue: retries join a single backlog after recovery; new normal traffic consumes capacity first.','limits':'Planning arithmetic, not an operational forecast. Constant rates, perfect retry eligibility, no queue limits, dependencies, timeouts or service-time variance. No systems were contacted or changed.'}

def _fan(step,matrix):
 a,b,c=np.percentile(matrix,[5,50,95]);return {'day':int(step),'p05':float(a),'median':float(b),'p95':float(c)}

def goal(total_hours,hours_per_day,consistency_percent=80,hours_done=0,deadline_days=None,daily_variation_percent=25,max_days=1095,paths=2000,seed=42):
 """How long a goal measured in hours takes when real days are uneven: some are skipped, some run short or long."""
 total=number(total_hours,'Total hours needed',.1,1e6);rate=number(hours_per_day,'Planned hours per day',.01,24)
 consistency=number(consistency_percent,'Consistency % (days you actually work)',1,100)/100;done=number(hours_done,'Hours already done',0,1e6)
 variation=number(daily_variation_percent,'Daily variation %',0,200)/100;horizon=integer(max_days,'Longest horizon in days',1,3650)
 paths=integer(paths,'Paths',100,10000);seed=integer(seed,'Random seed',0,2**32-1)
 deadline=None if deadline_days in (None,'',0) else integer(deadline_days,'Deadline in days',1,3650)
 if horizon*paths>4_000_000:raise ValueError('Keep horizon days × paths at or below 4,000,000.')
 remaining=max(0.0,total-done);rng=np.random.default_rng(seed);progress=np.full(paths,min(done,total));finish=np.full(paths,np.nan)
 if remaining==0:finish[:]=0
 history=[progress.copy()];day=0
 while day<horizon and np.isnan(finish).any():
  day+=1;worked=rng.random(paths)<consistency;hours=np.clip(rng.normal(rate,rate*variation,paths),0,24)
  progress=np.minimum(total,progress+worked*hours);newly=np.isnan(finish)&(progress>=total);finish[newly]=day;history.append(progress.copy())
 span=len(history)-1;steps=sorted(set(np.linspace(0,span,min(31,span+1),dtype=int)))
 fan=[_fan(s,history[s]) for s in steps];finished=finish[~np.isnan(finish)]
 pct=(lambda q:float(np.percentile(finished,q)) if len(finished) else None)
 today=datetime.now().date()
 when=(lambda d:(today+timedelta(days=math.ceil(d))).isoformat() if d is not None else None)
 p05,p50,p95=pct(5),pct(50),pct(95)
 result={'kind':'goal','assumptions':{'total_hours':total,'hours_per_day':rate,'consistency_percent':consistency*100,'hours_done':done,'daily_variation_percent':variation*100,'deadline_days':deadline,'max_days':horizon,'paths':paths,'seed':seed},
  'x_unit':'days','y_unit':'hours','target':total,'deadline':deadline,
  'finish_day_p05':p05,'finish_day_median':p50,'finish_day_p95':p95,'finish_date_p05':when(p05),'finish_date_median':when(p50),'finish_date_p95':when(p95),
  'naive_finish_day':math.ceil(remaining/rate) if rate else None,'simulated_fraction_unfinished_at_horizon_percent':float(np.mean(np.isnan(finish))*100),
  'fan_chart':fan,'method':'Monte Carlo over days: each day is worked with the consistency probability, worked hours are normal around the plan (clipped to 0–24 h).',
  'limits':'Hypothetical arithmetic on your own assumptions. Real study plans also depend on difficulty, fatigue, exams and breaks that this model does not see.'}
 if deadline:result['simulated_fraction_done_by_deadline_percent']=float(np.mean(finish<=deadline)*100)
 return result

def savings(monthly_contribution,months,start_balance=0,annual_return_percent=0,annual_volatility_percent=0,target=None,paths=2000,seed=42):
 """A savings plan month by month. Returns and volatility are the user's own assumptions, never JARVIS's."""
 add=number(monthly_contribution,'Monthly contribution',-1e9,1e9);months=integer(months,'Months',1,1200);start=number(start_balance,'Starting balance',0,1e15)
 mu=number(annual_return_percent,'Assumed annual return %',-100,100)/100;sigma=number(annual_volatility_percent,'Assumed annual volatility %',0,300)/100
 paths=integer(paths,'Paths',100,10000);seed=integer(seed,'Random seed',0,2**32-1);goal_value=None if target in (None,'',0) else number(target,'Target balance',0,1e15)
 if months*paths>2_000_000:raise ValueError('Keep months × paths at or below 2,000,000.')
 rng=np.random.default_rng(seed);balance=np.full(paths,start);dt=1/12;hit=np.full(paths,np.nan);steps=set(np.linspace(0,months,min(31,months+1),dtype=int));fan=[_fan(0,balance)]
 if goal_value is not None:hit[balance>=goal_value]=0
 for m in range(1,months+1):
  balance=np.maximum(0,balance*np.exp((mu-.5*sigma*sigma)*dt+sigma*math.sqrt(dt)*rng.standard_normal(paths))+add)
  if goal_value is not None:hit[np.isnan(hit)&(balance>=goal_value)]=m
  if m in steps:fan.append(_fan(m,balance))
 a,b,c=np.percentile(balance,[5,50,95]);paid=start+add*months
 result={'kind':'savings','assumptions':{'start_balance':start,'monthly_contribution':add,'months':months,'annual_return_percent':mu*100,'annual_volatility_percent':sigma*100,'target':goal_value,'paths':paths,'seed':seed},
  'x_unit':'months','y_unit':'balance','target':goal_value,'final_balance_p05':float(a),'final_balance_median':float(b),'final_balance_p95':float(c),'total_paid_in':paid,'fan_chart':fan,
  'method':'Monthly geometric Brownian motion on the balance with your assumed return and volatility, contribution added at each month end.',
  'limits':'Hypothetical model outcomes from your assumptions, not investment advice or a forecast. No taxes, fees, inflation or changing contributions.'}
 if goal_value is not None:
  reached=hit[~np.isnan(hit)];result['simulated_fraction_reaching_target_percent']=float(np.mean(~np.isnan(hit))*100);result['target_month_median']=float(np.median(reached)) if len(reached) else None
 return result

def from_backtest(stats):
 """A trading_lab backtest as a board result: the equity line in R, shaded down to its running peak (drawdown)."""
 money=stats.get('money') or None
 curve=(money or {}).get('curve') or stats.get('equity_curve_r') or [[0,0.0]];peak=float('-inf');rows=[]
 for n,eq in curve:
  peak=max(peak,eq);rows.append({'day':int(n),'p05':float(eq),'median':float(eq),'p95':float(peak)})
 trades=[{k:t.get(k) for k in ('n','direction','entry_time','exit_time','entry','stop','exit','r','pnl','balance','result')} for t in (stats.get('trades') or [])][-300:]
 return {'kind':'backtest','x_unit':'trades','y_unit':'money' if money else 'R','target':None,'fan_chart':rows,'trades':trades,'money':money and {k:v for k,v in money.items() if k!='curve'},
  'band_label':('line = balance' if money else 'line = equity in R')+'  ·  shaded = drawdown  ·  bars = each trade (green win, red loss)',
  'assumptions':{'strategy':stats.get('strategy'),'instrument':str(stats.get('requested') or stats.get('instrument') or '').upper(),'interval':stats.get('interval'),'reward_to_risk':(stats.get('settings') or {}).get('reward_to_risk'),'period':stats.get('period')},
  'stats':{k:stats.get(k) for k in ('closed_trades','wins','losses','win_rate_percent','total_r','average_r_per_trade','profit_factor','max_drawdown_r','longest_losing_streak')},
  'limits':stats.get('assumptions','Past results do not predict future ones.'),'created':datetime.now(timezone.utc).isoformat()}

_FMT=lambda v,d=1:'—' if v is None else (f'{v:,.{d}f}' if abs(v)<1e6 else f'{v:,.3g}')

def headline(result):
 """Title, metric cards and a one-line verdict for the holographic display and for JARVIS to say."""
 kind=result.get('kind');a=result.get('assumptions',{});m=[]
 if kind=='comparison':
  inner=headline(result.get('alternative',{}));base=headline(result.get('baseline',{}))
  changed=', '.join(f"{k} {v['baseline']}→{v['alternative']}" for k,v in result.get('changed_assumptions',{}).items()) or 'no assumption changed'
  lead=''
  if inner['metrics'] and base['metrics'] and inner['metrics'][0][0]==base['metrics'][0][0]:
   lead=f" {inner['metrics'][0][0].capitalize()}: {base['metrics'][0][1]} → {inner['metrics'][0][1]}."
  return {'title':'COMPARISON · '+inner['title'],'metrics':inner['metrics'],'verdict':'Changed '+changed+'.'+lead+' '+inner['verdict']}
 if kind=='goal':
  p50=result.get('finish_day_median');p05=result.get('finish_day_p05');p95=result.get('finish_day_p95')
  m=[('MEDIAN FINISH',f"day {_FMT(p50,0)}",'pri'),('LIKELY RANGE',f"{_FMT(p05,0)}–{_FMT(p95,0)} days",'acc2'),('IF EVERY DAY WENT TO PLAN',f"day {_FMT(result.get('naive_finish_day'),0)}",'dim'),('PLAN',f"{_FMT(a.get('hours_per_day'))} h/day · {_FMT(a.get('consistency_percent'),0)}% of days",'dim')]
  if a.get('deadline_days'):
   chance=result.get('simulated_fraction_done_by_deadline_percent',0);m.insert(1,(f"DONE BY DAY {a['deadline_days']}",f"{chance:.0f}% of runs",'green' if chance>=70 else 'acc2' if chance>=40 else 'red'))
  verdict=(f"At {_FMT(a.get('hours_per_day'))} hours a day, working {a.get('consistency_percent',0):.0f}% of days, the median run reaches {_FMT(a.get('total_hours'),0)} hours on day {_FMT(p50,0)} ({result.get('finish_date_median') or 'beyond the horizon'})." if p50 is not None else 'Most runs did not finish inside the horizon; raise the hours or the consistency.')
  return {'title':'GOAL TIMELINE','metrics':m,'verdict':verdict}
 if kind=='savings':
  m=[('MEDIAN BALANCE',_FMT(result.get('final_balance_median'),0),'pri'),('5TH–95TH PERCENTILE',f"{_FMT(result.get('final_balance_p05'),0)} – {_FMT(result.get('final_balance_p95'),0)}",'acc2'),('PAID IN',_FMT(result.get('total_paid_in'),0),'dim')]
  if result.get('target') is not None:
   chance=result.get('simulated_fraction_reaching_target_percent',0);m.insert(1,('RUNS REACHING TARGET',f'{chance:.0f}%','green' if chance>=70 else 'acc2' if chance>=40 else 'red'))
  return {'title':'SAVINGS PLAN','metrics':m,'verdict':f"After {a.get('months')} months the median run ends near {_FMT(result.get('final_balance_median'),0)} from {_FMT(result.get('total_paid_in'),0)} paid in, under your assumed {a.get('annual_return_percent',0):.1f}% return."}
 if kind=='backtest':
  st=result.get('stats',{});tot=st.get('total_r') or 0;wr=st.get('win_rate_percent');mo=result.get('money')
  m=[('WINS / LOSSES',f"{st.get('wins',0)} W  /  {st.get('losses',0)} L",'green' if st.get('wins',0)>=st.get('losses',0) else 'red'),
     ('WIN RATE','—' if wr is None else f'{wr:.1f}%','acc2'),('TOTAL R',f"{tot:+.2f}R",'green' if tot>0 else 'red')]
  if mo:
   net=mo.get('net_pnl',0)
   m=[('NET P&L',f"{net:+,.2f}  ({mo.get('return_percent',0):+.2f}%)",'green' if net>0 else 'red')]+m+[
      ('BALANCE',f"{mo.get('start_balance',0):,.0f} → {mo.get('end_balance',0):,.2f}",'pri'),
      ('BEST / WORST',f"{mo.get('largest_win',0):+,.2f} / {mo.get('largest_loss',0):+,.2f}",'dim'),
      ('MAX DRAWDOWN',f"{mo.get('max_drawdown',0):,.2f}  ({st.get('max_drawdown_r') or 0:.1f}R)",'red')]
  else:
   m+=[('MAX DRAWDOWN',f"{st.get('max_drawdown_r') or 0:.1f}R",'red'),('PROFIT FACTOR',_FMT(st.get('profit_factor'),2),'pri')]
  name=str(a.get('strategy') or 'strategy').replace('_',' ');inst=a.get('instrument') or ''
  return {'title':f"BACKTEST · {name.upper()} · {inst} {a.get('interval') or ''}".strip(),'metrics':m,
   'verdict':f"{st.get('closed_trades',0)} trades at 1:{a.get('reward_to_risk') or '?'} from {(a.get('period') or ['?'])[0][:10]} to {(a.get('period') or ['?','?'])[-1][:10]}: {st.get('wins',0)} wins, {st.get('losses',0)} losses, {tot:+.2f}R"+(f", net {mo['net_pnl']:+,.2f}" if mo else '')+". Past results; hover a bar for that trade."}
 if kind=='forex':
  m=[('MEDIAN END RATE',_FMT(result.get('terminal_rate_median'),5),'pri'),('5TH–95TH PERCENTILE',f"{_FMT(result.get('terminal_rate_p05'),5)} – {_FMT(result.get('terminal_rate_p95'),5)}",'acc2'),('RUNS BELOW START',f"{result.get('simulated_fraction_below_unshocked_start_percent',0):.0f}%",'dim'),('P95 MAX DRAWDOWN',f"{result.get('p95_path_max_drawdown_percent',0):.1f}%",'red')]
  return {'title':'FOREX PATHS','metrics':m,'verdict':f"Over {a.get('trading_days')} trading days the median path ends at {_FMT(result.get('terminal_rate_median'),5)}; one run in twenty ends below {_FMT(result.get('terminal_rate_p05'),5)}."}
 if kind=='trade_stress':
  net=result.get('net_pnl_account_currency',0)
  m=[('NET P&L',_FMT(net,2),'green' if net>=0 else 'red'),('EQUITY AFTER',_FMT(result.get('equity_after_scenario'),2),'pri'),('EQUITY CHANGE',f"{result.get('equity_change_percent',0):+.2f}%",'acc2')]
  return {'title':'TRADE STRESS TEST','metrics':m,'verdict':f"A {a.get('move_percent',0):+.2f}% move on this {a.get('direction')} position changes equity by {result.get('equity_change_percent',0):+.2f}%."}
 if kind=='outage':
  clear=result.get('estimated_backlog_clearance_minutes')
  m=[('FAILED REQUESTS',_FMT(result.get('failed_or_interrupted_requests'),0),'red'),('RECOVERY BACKLOG',_FMT(result.get('total_recovery_backlog'),0),'acc2'),('CLEARS IN',('never — no spare capacity' if clear is None else f'{clear:.0f} min'),'green' if result.get('stable_recovery') else 'red')]
  return {'title':'OUTAGE RECOVERY','metrics':m,'verdict':('Recovery is stable.' if result.get('stable_recovery') else 'Recovery never catches up: capacity is below normal traffic.')}
 return {'title':'SIMULATION','metrics':[],'verdict':''}

def run(kind,parameters):
 if not isinstance(parameters,dict):raise ValueError('Provide a parameter object.')
 functions={'forex':forex,'trade_stress':trade_stress,'outage':outage,'goal':goal,'savings':savings}
 if kind not in functions:raise ValueError('Choose forex, trade_stress, outage, goal or savings.')
 import inspect
 accepted=inspect.signature(functions[kind]).parameters
 ignored=sorted(k for k in parameters if k not in accepted)
 missing=[k for k,v in accepted.items() if v.default is inspect.Parameter.empty and k not in parameters]
 if missing:raise ValueError(f'{kind} needs: '+', '.join(missing)+'.')
 result=functions[kind](**{k:v for k,v in parameters.items() if k in accepted})
 if ignored:result['ignored_parameters']=ignored     # a stray model key must not cancel the whole run
 result['created']=datetime.now(timezone.utc).isoformat();return result

def save(result):
 if not isinstance(result,dict) or result.get('kind') not in ('forex','trade_stress','outage','goal','savings','backtest','comparison'):raise ValueError('Run a scenario first.')
 REPORTS.mkdir(parents=True,exist_ok=True,mode=0o700);path=REPORTS/('scenario-'+uuid.uuid4().hex[:12]+'.json')
 write_file(path,json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2));return str(path)

def compare(kind,baseline,alternative):
    a=run(kind,baseline);b=run(kind,{**baseline,**alternative})
    changed={k:{'baseline':baseline.get(k),'alternative':v} for k,v in alternative.items() if baseline.get(k)!=v}
    metrics={k:{'baseline':a[k],'alternative':b[k],'difference':b[k]-a[k]} for k in a if isinstance(a[k],(int,float)) and not isinstance(a[k],bool) and isinstance(b.get(k),(int,float)) and not isinstance(b[k],bool)}
    return {'kind':'comparison','scenario_kind':kind,'changed_assumptions':changed,'metrics':metrics,'baseline':a,'alternative':b,'limits':'Both runs are hypothetical and conditional on their assumptions. Using the same random seed improves controlled comparison; it does not establish real-world probabilities.'}


def remember(result):
 """Keep the last result so "show me the simulation again" works, also after a restart."""
 try:REPORTS.mkdir(parents=True,exist_ok=True,mode=0o700);write_file(LAST,json.dumps(result,ensure_ascii=False,allow_nan=False))
 except Exception:pass

def last():
 try:return json.loads(LAST.read_text())
 except (OSError,ValueError):return None

def demo():
 """Something to show when nothing has been simulated yet: a study plan vs one more hour a day."""
 return compare('goal',{'total_hours':300,'hours_per_day':3,'consistency_percent':80,'deadline_days':150},{'hours_per_day':4})
