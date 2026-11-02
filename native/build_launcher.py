"""Rebuild the dedicated macOS launcher after relocating/upgrading Python."""
from pathlib import Path
import plistlib, subprocess, sysconfig
root=Path(__file__).resolve().parents[1]
bundle=root.parent/'Mark LVI.app'
macos=bundle/'Contents'/'MacOS'
macos.mkdir(parents=True,exist_ok=True)
info={'CFBundleName':'Mark LVI','CFBundleDisplayName':'Mark LVI','CFBundleIdentifier':'com.maneesh.marklvi','CFBundleExecutable':'MarkLVI','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSLocationUsageDescription':'JARVIS uses your location only when you choose My device location to center Earth and maps.','NSLocationWhenInUseUsageDescription':'JARVIS uses your location only when you choose My device location to center Earth and maps.','NSCameraUsageDescription':'JARVIS uses the camera only when you request camera assistance. Requested images are shared with your configured vision service.','NSMicrophoneUsageDescription':'JARVIS uses the microphone for voice commands when you enable it.','NSAppleEventsUsageDescription':'JARVIS arranges app windows only when you request an app-control action.'}
with (bundle/'Contents'/'Info.plist').open('wb') as stream:plistlib.dump(info,stream)
framework=Path(sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX'))/'Python.framework'/'Versions'/sysconfig.get_config_var('VERSION')/'Python'
subprocess.run(['clang',str(root/'native'/'launcher.c'),'-I'+sysconfig.get_paths()['include'],str(framework),'-o',str(macos/'MarkLVI')],check=True)
subprocess.run(['codesign','--force','--sign','-',str(bundle)],check=True)
print(bundle)
