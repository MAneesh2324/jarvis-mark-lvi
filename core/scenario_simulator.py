"""Reproducible hypothetical scenarios. No orders, scans or real system changes."""
from datetime import datetime,timezone
from pathlib import Path
import json,math,uuid
import numpy as np
from core.mission_store import write_file
REPORTS=Path(__file__).resolve().parent.parent/'memory'/'scenarios'
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

def run(kind,parameters):
 if not isinstance(parameters,dict):raise ValueError('Provide a parameter object.')
 functions={'forex':forex,'trade_stress':trade_stress,'outage':outage}
 if kind not in functions:raise ValueError('Choose forex, trade_stress or outage.')
 try:result=functions[kind](**parameters)
 except TypeError:raise ValueError('Missing or unsupported scenario parameters.') from None
 result['created']=datetime.now(timezone.utc).isoformat();return result

def save(result):
 if not isinstance(result,dict) or result.get('kind') not in ('forex','trade_stress','outage','comparison'):raise ValueError('Run a scenario first.')
 REPORTS.mkdir(parents=True,exist_ok=True,mode=0o700);path=REPORTS/('scenario-'+uuid.uuid4().hex[:12]+'.json')
 write_file(path,json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2));return str(path)

def compare(kind,baseline,alternative):
    a=run(kind,baseline);b=run(kind,{**baseline,**alternative})
    changed={k:{'baseline':baseline.get(k),'alternative':v} for k,v in alternative.items() if baseline.get(k)!=v}
    metrics={k:{'baseline':a[k],'alternative':b[k],'difference':b[k]-a[k]} for k in a if isinstance(a[k],(int,float)) and not isinstance(a[k],bool) and isinstance(b.get(k),(int,float)) and not isinstance(b[k],bool)}
    return {'kind':'comparison','scenario_kind':kind,'changed_assumptions':changed,'metrics':metrics,'baseline':a,'alternative':b,'limits':'Both runs are hypothetical and conditional on their assumptions. Using the same random seed improves controlled comparison; it does not establish real-world probabilities.'}
