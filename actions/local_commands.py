from core import outcome
from core.local_commands import execute


def run(parameters,player=None,**kwargs):
    try:return execute(parameters.get('command',''),player)
    except Exception as exc:return outcome.failed('local_commands',str(exc))

TOOL={'name':'local_commands','description':'Execute a supported deterministic local command without an additional model call: open APP, volume 0–100, timer N seconds/minutes/hours, remember KEY is VALUE, recall TOPIC, run routine NAME, project status, time. Use only for a command the user explicitly requested. This tool does not itself switch microphone recognition; Local Voice mode is a separate control.',
'parameters':{'type':'OBJECT','properties':{'command':{'type':'STRING'}},'required':['command']},'handler':run,'tier':'core'}
