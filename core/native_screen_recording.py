"""Native macOS MP4 recording: synchronized display and system sound and optional microphone."""
import os
import threading
import time

_DELEGATE = None


def record(owner, monitor, fps):
    import ScreenCaptureKit as SC
    import AVFoundation as AV
    import Foundation as NS
    import CoreMedia as CM
    import objc

    if not hasattr(SC, 'SCRecordingOutput'):
        raise RuntimeError('System-audio recording requires macOS 15 or later. Choose audio=none for video only.')

    global _DELEGATE
    if _DELEGATE is None:
        class JarvisRecordingDelegate(NS.NSObject):
            def recordingOutputDidStartRecording_(self, output):
                self.owner._ready.set()
            def recordingOutputDidFinishRecording_(self, output):
                self.finished.set()
            def recordingOutput_didFailWithError_(self, output, error):
                self.errors.append(str(error));self.owner._ready.set();self.finished.set()
        _DELEGATE = JarvisRecordingDelegate
    finished=threading.Event();errors=[];loaded=threading.Event();contents=[]
    def got_content(content,error):
        if error:errors.append(str(error))
        else:contents.append(content)
        loaded.set()
    SC.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(False,True,got_content)
    if not loaded.wait(10):raise RuntimeError('macOS display discovery timed out.')
    if errors:raise RuntimeError(errors[0])
    displays=contents[0].displays()
    if monitor<1 or monitor>len(displays):raise ValueError('That display does not exist.')
    display=displays[monitor-1]
    include_mic=owner._audio_mode == 'both'
    if include_mic:
        from core.recording_echo import ffmpeg_path
        ffmpeg_path()
    if include_mic and AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio) != AV.AVAuthorizationStatusAuthorized:
        raise PermissionError('Enable Microphone access for Mark LVI in System Settings → Privacy & Security → Microphone, then reopen the app.')
    config=SC.SCStreamConfiguration.alloc().init()
    scale=min(1,1600/display.width(),1000/display.height())
    config.setWidth_(int(display.width()*scale)//2*2);config.setHeight_(int(display.height()*scale)//2*2)
    config.setMinimumFrameInterval_(CM.CMTimeMake(1,fps));config.setQueueDepth_(5)
    config.setShowsCursor_(True);config.setCapturesAudio_(True)
    config.setExcludesCurrentProcessAudio_(False)
    config.setSampleRate_(48000);config.setChannelCount_(2)
    if include_mic and not hasattr(config,'setCaptureMicrophone_'):
        raise RuntimeError('This macOS version cannot record microphone through ScreenCaptureKit.')
    if hasattr(config,'setCaptureMicrophone_'):config.setCaptureMicrophone_(include_mic)
    filter_=SC.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display,[])
    delegate=_DELEGATE.alloc().init()
    delegate.owner=owner;delegate.finished=finished;delegate.errors=errors
    stream=SC.SCStream.alloc().initWithFilter_configuration_delegate_(filter_,config,None)
    output_config=SC.SCRecordingOutputConfiguration.alloc().init()
    if include_mic:
        if not hasattr(output_config,'setMixesAudioWithMicrophone_'):
            raise RuntimeError('Mixing microphone with system sound requires macOS 27 or later on this recorder.')
        output_config.setMixesAudioWithMicrophone_(False)
    output_config.setOutputURL_(NS.NSURL.fileURLWithPath_(str(owner._path)))
    output_config.setVideoCodecType_(AV.AVVideoCodecTypeH264);output_config.setOutputFileType_(AV.AVFileTypeMPEG4)
    output=SC.SCRecordingOutput.alloc().initWithConfiguration_delegate_(output_config,delegate)
    ok,error=stream.addRecordingOutput_error_(output,None)
    if not ok:raise RuntimeError(str(error))
    started=threading.Event()
    def did_start(error):
        if error:errors.append(str(error))
        started.set()
    stream.startCaptureWithCompletionHandler_(did_start)
    if not started.wait(10):raise RuntimeError('macOS capture startup timed out.')
    if errors:raise RuntimeError(errors[0])
    notes_capture=None;next_note=0
    try:
        from core.recording_notes import RecordingNotes
        import mss
        owner._notes=RecordingNotes(owner._path)
        owner._notes.data['audio_recorded']=True
        notes_capture=mss.mss()
    except Exception as exc:owner._notes_error=str(exc)
    try:
        while not owner._stop.wait(.1):
            if errors:raise RuntimeError(errors[0])
            if owner._path.exists():os.chmod(owner._path,0o600)
            duration=CM.CMTimeGetSeconds(output.recordedDuration())
            with owner._lock:owner._frames=max(owner._frames,int(max(0,duration)*fps))
            if notes_capture is not None and duration>=next_note:
                next_note=duration+10
                try:
                    import numpy as np
                    owner._notes.sample(np.asarray(notes_capture.grab(notes_capture.monitors[monitor]))[:,:,:3],duration)
                except Exception as exc:owner._notes_error=str(exc)
        owner._ready.set()
    finally:
        if notes_capture is not None:notes_capture.close()
        stopped=threading.Event()
        def did_stop(error):
            if error:errors.append(str(error))
            stopped.set()
        stream.stopCaptureWithCompletionHandler_(did_stop)
        if not stopped.wait(10) or not finished.wait(10):
            raise RuntimeError('macOS has not finished writing the MP4 yet.')
    if errors:raise RuntimeError(errors[0])
    if owner._path.exists():os.chmod(owner._path,0o600)
    if include_mic:
        owner._finalizing = True
        try:
            from core.recording_echo import finalize
            finalize(owner._path)
            owner._echo_reduced = True
        finally:owner._finalizing = False
    asset=AV.AVURLAsset.URLAssetWithURL_options_(NS.NSURL.fileURLWithPath_(str(owner._path)),None)
    with owner._lock:
        owner._audio_recorded=bool(asset.tracksWithMediaType_(AV.AVMediaTypeAudio))
        owner._frames=max(1,int(CM.CMTimeGetSeconds(asset.duration())*fps))
    if not owner._audio_recorded:raise RuntimeError('Video saved, but macOS produced no system-audio track. Check Screen & System Audio Recording access.')
