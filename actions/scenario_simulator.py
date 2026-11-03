import json
from core import outcome

def simulate(parameters,**kwargs):
 from core.scenario_simulator import run,save,compare
 try:
  base=json.loads(parameters.get('parameters_json','{}'))
  result=compare(parameters.get('kind',''),base,json.loads(parameters['alternative_json'])) if parameters.get('alternative_json') else run(parameters.get('kind',''),base)
  if parameters.get('save_report'):result['report_path']=save(result)
  return outcome.untrusted('hypothetical-scenario',json.dumps(result,ensure_ascii=False,allow_nan=False))
 except Exception as exc:return outcome.failed('scenario_simulator',str(exc))
TOOL={'name':'scenario_simulator','description':'Run bounded local hypothetical scenarios without contacting brokers or systems. kind forex: parameters_json requires start_rate, annual_return_percent, annual_volatility_percent; optional days=90, paths=1000, shock_percent=0, seed=42. All assumptions must be supplied/confirmed by user; do not invent expected returns. kind trade_stress: equity, units, pair_start, pair_move_percent, quote_to_account; optional spread_cost, slippage_cost, direction long/short. kind outage: requests_per_minute, outage_minutes, affected_percent, capacity_per_minute; optional retry_percent, backlog_before. Report assumptions, model method and limitations; simulated fractions are not real-world forecast probabilities. Optional alternative_json supplies changed assumptions for a baseline/alternative comparison. save_report stores a private JSON report.', 'parameters':{'type':'OBJECT','properties':{'kind':{'type':'STRING','enum':['forex','trade_stress','outage']},'parameters_json':{'type':'STRING'},'alternative_json':{'type':'STRING'},'save_report':{'type':'BOOLEAN'}},'required':['kind','parameters_json']},'handler':simulate,'tier':'core'}
