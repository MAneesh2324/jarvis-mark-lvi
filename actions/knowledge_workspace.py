import json
from core import outcome

def knowledge(parameters,**kwargs):
    p=parameters
    try:
        action=p.get('action','lessons')
        if action=='forex':
            from core.forex_workspace import snapshot
            data=snapshot(p.get('pair','EUR/USD'))
        elif action=='position_size':
            from core.forex_workspace import position_size
            data=position_size(p['pair'],p['equity'],p['risk_percent'],p['stop_pips'],p['account_currency'],p.get('quote_to_account'))
        elif action=='kev':
            from core.cyber_workspace import kev
            data=kev(p.get('query',''))
        elif action=='cve':
            from core.cyber_workspace import cve
            data=cve(p.get('query',''))
        elif action=='cyber_research':
            from core.cyber_workspace import research
            data=research(p.get('query',''))
        elif action in ('world','science'):
            from core.auto_learning import headlines
            data=headlines(action)
        elif action=='lessons':
            from core.learning_journal import recall
            data=recall(p.get('domain','all'),p.get('query',''))
        elif action=='learn':
            from core.learning_journal import draft
            data=draft(p.get('domain','general'),p.get('title',''),p.get('lesson',''),p.get('evidence',''))
        elif action=='trade_add':
            from core.learning_journal import trade
            data=trade(p['pair'],p['pnl'],p['account_currency'],p.get('setup',''),p.get('notes',''))
        elif action=='trade_summary':
            from core.learning_journal import trade_summary
            data=trade_summary(p.get('account_currency','USD'))
        elif action=='updates':
            from core.auto_learning import current
            data=current()
        elif action in ('approve_lesson','revoke_lesson'):
            from core.learning_journal import review
            data=review(p['lesson_id'],action=='approve_lesson')
        elif action=='auto_learning':
            from core.auto_learning import configure
            data=configure(p.get('enabled',True))
        elif action=='learning_status':
            from core.auto_learning import state,settings
            data={'settings':settings(),'refresh':state()}
        else:raise ValueError('Unknown knowledge action.')
        return outcome.untrusted('knowledge-workspace',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('knowledge_workspace',str(exc))
TOOL={'name':'knowledge_workspace','description':'Forex/security/world research and local lessons. forex returns ECB daily reference history and transparent calculations, never live broker prices or buy/sell advice. position_size calculates from explicit user inputs, no order execution. kev reads CISA known exploitation, cve reads NVD details, cyber_research finds primary-source snippets; none scans a device. world/science return attributed headlines, not verified universal knowledge. Respect source/as-of dates and offline_fallback. updates reads the local automatic brief, auto_learning enables/disables hourly public refresh when the user asks. learn saves an evidence-backed DRAFT correction; approve_lesson/revoke_lesson only on the user’s explicit request for that lesson ID, never self-approve generated facts. lessons recalls reviewed or deterministic outcome lessons; no model retraining or self-modifying code. Trade entries stay local and are user-provided; add only explicitly supplied realized results, not inferred trades.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['forex','position_size','kev','cve','cyber_research','world','science','lessons','learn','trade_add','trade_summary','learning_status','updates','approve_lesson','revoke_lesson','auto_learning']},'lesson_id':{'type':'INTEGER'},'enabled':{'type':'BOOLEAN'},'pair':{'type':'STRING'},'query':{'type':'STRING'},'domain':{'type':'STRING','enum':['all','general','forex','cybersecurity']},'title':{'type':'STRING'},'lesson':{'type':'STRING'},'evidence':{'type':'STRING'},'equity':{'type':'NUMBER'},'risk_percent':{'type':'NUMBER'},'stop_pips':{'type':'NUMBER'},'account_currency':{'type':'STRING'},'quote_to_account':{'type':'NUMBER'},'pnl':{'type':'NUMBER'},'setup':{'type':'STRING'},'notes':{'type':'STRING'}},'required':['action']},'handler':knowledge,'tier':'core'}
