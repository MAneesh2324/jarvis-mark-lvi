from core import outcome
from core.screen_workspace import workspace


def highlights(parameters,**kwargs):
    action=parameters.get('action','summarize')
    try:
        if action=='mark':
            return outcome.done('recording_highlights',**workspace.recorder.mark(parameters.get('note','')))
        if action=='summarize':
            from core.recording_notes import load
            video,data=load(parameters.get('video',''))
            workspace.request_job('highlights','Summarize useful moments and next steps.',{'video':str(video)})
            return 'Recording summary requested from saved sampled keyframes and user markers, not audio or every video frame. The selected frames will arrive in this conversation. Wait for them before answering; the summary will also be saved beside the MP4.'
        raise ValueError('Choose mark or summarize.')
    except Exception as exc:return outcome.failed('recording_highlights',str(exc))

TOOL={'name':'recording_highlights','description':'Add a timestamped user marker during a recording, or summarize a local recording using its saved sampled keyframes and markers. Summaries require the configured vision model and are saved as .highlights.md beside the MP4. Recordings have no audio; never invent spoken decisions or claim full-video coverage. Default is the most recent recording in this app.',
'parameters':{'type':'OBJECT','properties':{'action':{'type':'STRING','enum':['mark','summarize']},'note':{'type':'STRING'},'video':{'type':'STRING'}},'required':['action']},'handler':highlights,'tier':'core'}
