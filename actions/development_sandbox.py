import json
from core import outcome

def sandbox(parameters,**kwargs):
    from core import development_sandbox as dev
    p=parameters
    try:
        action=p.get('action','list');key=p.get('id','')
        if action=='create':data=dev.create(p.get('root',''),p.get('goal',''))
        elif action=='list':data=dev.listing()
        elif action=='review':data=dev.review(key)
        elif action=='read':data={'file':p.get('file',''),'content':dev.read(key,p.get('file',''))}
        elif action=='edit':data=dev.edit(key,p.get('file',''),p.get('content',''))
        elif action=='check':data=dev.check(key)
        elif action=='propose':data=dev.propose(key,p.get('files',[]),p.get('goal',''))
        else:raise ValueError('Use create, list, read, edit, review, check or propose. Staging, test execution and applying originals are local UI actions.')
        return outcome.untrusted('sandbox-result',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('development_sandbox',str(exc))
TOOL={'name':'development_sandbox','description':'Create an isolated source-file copy of an explicit project folder, inspect/edit copied files, review diffs, run non-executing syntax checks, or request an AI proposal for explicitly selected files. The original project is unchanged until the user reviews and applies in Mission Control → Sandbox. This is not OS isolation. Project tests run only via the disclosed local UI action. Never claim tests ran when only syntax was checked. AI proposals share selected copy contents with the configured model only when the user requests that review.', 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['create','list','read','edit','review','check','propose']},'id':{'type':'STRING'},'root':{'type':'STRING'},'goal':{'type':'STRING'},'file':{'type':'STRING'},'content':{'type':'STRING'},'files':{'type':'ARRAY','items':{'type':'STRING'}}},'required':['action']},'handler':sandbox,'tier':'core'}
