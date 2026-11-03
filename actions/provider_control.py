"""Explicit user-requested provider switching; no credential generation."""
import json
from core import quota_failover,outcome

def configure(parameters,player=None,**kwargs):
    provider=str(parameters.get('provider','status')).lower()
    if provider=='status':return json.dumps(quota_failover.status())
    if provider not in ('groq','gemini'):return outcome.failed('provider_control','Choose groq, gemini or status.')
    if player is not None and callable(getattr(player,'on_text_command',None)):
        player.on_text_command('/provider '+provider)
        return outcome.done('provider_control',requested_provider=provider,activation='Switch requested; the UI label confirms actual provider. Cooldowns are respected.')
    return json.dumps(quota_failover.prefer(provider))

TOOL={'name':'provider_control','description':'Switch reasoning providers only when the user explicitly asks Use Groq or Use Gemini. Keeps the configured speech voice. Rate-limited providers wait for cooldown. status returns configured preference and eligibility, not proof of current connection.','parameters':{'type':'OBJECT','properties':{'provider':{'type':'STRING','enum':['groq','gemini','status']}},'required':['provider']},'handler':configure,'tier':'core','brief':'Use Groq / Use Gemini on explicit user request; respect cooldowns.'}
