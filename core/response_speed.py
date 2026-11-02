"""Reversible low-latency voice profile; retains original settings underneath."""
from memory.config_manager import load_api_keys,_save_flag,get_turn_tuning


def get_profile():
    return 'fast' if load_api_keys().get('response_speed')=='fast' else 'standard'


def set_profile(profile):
    if profile not in ('fast','standard'):raise ValueError('Choose fast or standard response speed.')
    _save_flag('response_speed',profile)


def effective_turn_tuning():
    settings=get_turn_tuning()
    if get_profile()=='fast':
        return {**settings,'enabled':True,'silence_ms':400,'prefix_ms':150,'end_sensitivity':'high'}
    return settings


def instruction():
    if get_profile()!='fast':return ''
    return ('[FAST RESPONSE PROFILE]\nStart with the useful answer immediately, without preambles or spoken reasoning. '
            'For ordinary conversation use one or two concise sentences, unless the user requests depth. '
            'Do not search or invoke tools for stable explanations or arithmetic. Use tools when necessary '
            'for an action, current information, stored personal facts or evidence. Never trade accuracy for speed.')
