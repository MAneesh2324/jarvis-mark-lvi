import json
from core.performance import snapshot


def report(parameters, **kwargs):
    data=snapshot()
    from core.response_speed import get_profile,effective_turn_tuning
    from core.quota_failover import status as fallback_status
    data['provider_fallback']=fallback_status()
    data['response_profile']=get_profile()
    data['effective_turn_detection']=effective_turn_tuning()
    return json.dumps(data, ensure_ascii=False)


TOOL = {'name': 'performance_report', 'description': 'Inspect measured tool runtimes, conversation-disk-write time, and typed-request-to-first-audio time for this app process. Use when asked why responses are slow. Empty timings mean no samples yet, not zero delay. Voice end-of-speech latency and speaker latency are not measured. Never invent a speedup from these numbers.',
        'parameters': {'type': 'OBJECT', 'properties': {}}, 'handler': report, 'tier': 'core'}
