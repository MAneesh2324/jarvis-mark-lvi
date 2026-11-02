from core import outcome
from core.screen_workspace import workspace


def troubleshoot(parameters,**kwargs):
    action=parameters.get('action','diagnose')
    if action not in ('diagnose','check'):return outcome.failed('screen_troubleshoot','Choose diagnose or check.')
    try:
        workspace.request_job(action,parameters.get('focus','Identify the visible error and its likely cause.'),{'case_id':parameters.get('case_id','')})
        return 'Troubleshooting requested. Do not guess or describe the screen yet; the current screenshot and, for a fix check, previous evidence will arrive in this conversation.'
    except Exception as exc:return outcome.failed('screen_troubleshoot',str(exc))

TOOL={'name':'screen_troubleshoot','description':'Diagnose a visible screen error or check a proposed fix against saved before/after screenshot evidence. Only gives guidance; does not execute fixes. A check requires a previous diagnosis on the same screen target. State visible evidence separately from inferred causes and never claim an entire system is safe from a screenshot.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['diagnose','check']},'focus':{'type':'STRING'},'case_id':{'type':'STRING'}},'required':['action']},'handler':troubleshoot,'tier':'core'}
