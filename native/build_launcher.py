"""Rebuild the dedicated macOS launcher after relocating/upgrading Python."""
from pathlib import Path
import json, plistlib, subprocess, sys, sysconfig
if sys.platform != "darwin":raise SystemExit("The native app launcher is for macOS only.")
root=Path(__file__).resolve().parents[1]
bundle=root.parent/'Mark LVI.app'
macos=bundle/'Contents'/'MacOS'
macos.mkdir(parents=True,exist_ok=True)
info={'CFBundleName':'Mark LVI','CFBundleDisplayName':'Mark LVI','CFBundleIdentifier':'com.maneesh.marklvi','CFBundleExecutable':'MarkLVI','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSLocationUsageDescription':'JARVIS uses your location only when you choose My device location to center Earth and maps.','NSLocationWhenInUseUsageDescription':'JARVIS uses your location only when you choose My device location to center Earth and maps.','NSCameraUsageDescription':'JARVIS uses the camera only when you request camera assistance. Requested images are shared with your configured vision service.','NSMicrophoneUsageDescription':'JARVIS uses the microphone for voice commands when you enable it.','NSAppleEventsUsageDescription':'JARVIS arranges app windows only when you request an app-control action.'}
with (bundle/'Contents'/'Info.plist').open('wb') as stream:plistlib.dump(info,stream)
framework=Path(sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX'))/'Python.framework'/'Versions'/sysconfig.get_config_var('VERSION')/'Python'
definitions={'VENV_PYTHON':str(root/'.venv'/'bin'/'python'),'MAIN_SCRIPT':str(root/'main.py'),'PROJECT_ROOT':str(root),'STARTUP_LOG':str(root/'native-startup.log')}
if not Path(definitions['VENV_PYTHON']).exists():raise SystemExit('Create .venv in the project first; see INSTALL-MAC.md.')
flags=['-D'+key+'='+json.dumps(value,ensure_ascii=False) for key,value in definitions.items()]
subprocess.run(['clang',*flags,str(root/'native'/'launcher.c'),'-I'+sysconfig.get_paths()['include'],str(framework),'-o',str(macos/'MarkLVI')],check=True)
subprocess.run(['codesign','--force','--sign','-',str(bundle)],check=True)
print(bundle)
