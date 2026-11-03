"""Small deterministic checks for stalled voice transport and playback."""
import asyncio


def enqueue_latest(queue, message):
    """Run on the asyncio thread; keep recent microphone audio under congestion."""
    while queue.full():
        try:queue.get_nowait()
        except asyncio.QueueEmpty:break
    queue.put_nowait(message)


def microphone_stalled(active, last_callback, now, limit=3.0):
    return not active or now-last_callback>limit


def playback_drained(speaking, queue_empty, now, last_write, output_latency):
    # A missing server turn_complete must not leave the user's mic gated forever.
    return speaking and queue_empty and now-last_write>max(1.5,output_latency+.5)


def has_answer_progress(response):
    content=getattr(response,'server_content',None)
    return bool(getattr(response,'data',None) or getattr(response,'tool_call',None) or
                (content is not None and (getattr(content,'model_turn',None) or
                 getattr(content,'output_transcription',None) or getattr(content,'turn_complete',False))))
