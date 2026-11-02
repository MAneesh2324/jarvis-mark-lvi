import json
from core import outcome
from core import work_projects as store
from core.undo import push_undo


def manage(parameters,**kwargs):
    p=parameters;action=p.get('action','status');name=str(p.get('name','')).strip()
    try:
        if action=='list':data=store.list_projects()
        elif action=='save':
            old=store.project(name)
            data=store.save_project(name,**{k:p.get(k) for k in ('goal','progress','next_step','root')})
            if old:
                push_undo('update project '+name,lambda:store.save_project(name,**{k:old[k] for k in ('goal','progress','next_step','root')}) and 'Previous project fields restored.')
        elif action=='activate':data=store.activate(name)
        elif action=='add_task':data={'task_id':store.add_task(p.get('text',''),name)}
        elif action in ('complete_task','reopen_task'):
            store.task_done(p['task_id'],action=='complete_task');data={'task_id':p['task_id'],'done':action=='complete_task'}
        elif action=='status':data=store.project(name)
        else:raise ValueError('Choose list, save, activate, status, add_task, complete_task or reopen_task.')
        return outcome.untrusted('project-workspace',json.dumps(data,ensure_ascii=False))
    except Exception as exc:return outcome.failed('project_workspace',str(exc))

TOOL={'name':'project_workspace','description':'Persist named project goals, progress, next step, folder and task list. Save/create, activate, list or inspect a project; add/complete/reopen tasks. Active project context helps screen co-pilot relevance. Save actual user-provided goals and observed progress, never invented completion. New projects require name and goal.',
 'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['save','activate','list','status','add_task','complete_task','reopen_task']},'name':{'type':'STRING'},'goal':{'type':'STRING'},'progress':{'type':'STRING'},'next_step':{'type':'STRING'},'root':{'type':'STRING'},'text':{'type':'STRING'},'task_id':{'type':'INTEGER'}},'required':['action']},'handler':manage,'tier':'core'}
