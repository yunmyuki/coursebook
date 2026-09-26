"""Build a clean Windows app; Office is a separately validated release component."""
import argparse,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dist-dir',type=Path,default=ROOT/'release'/__version__/'app')
    args=parser.parse_args()
    work=ROOT/'build'/('desktop-'+__version__);work.mkdir(parents=True,exist_ok=True)
    version=work/'version-info.txt';numbers=tuple(int(n) for n in __version__.split('.'))+(0,)
    version.write_text(f"VSVersionInfo(ffi=FixedFileInfo(filevers={numbers},prodvers={numbers},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','Course Compiler'),StringStruct('FileVersion','{__version__}'),StringStruct('ProductName','Course Compiler'),StringStruct('ProductVersion','{__version__}')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])",encoding='utf-8')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--noupx','--name','CourseCompiler','--version-file',str(version),'--distpath',str(args.dist_dir),'--workpath',str(work),'--specpath',str(work),'--add-data',str(ROOT/'web')+';web']
    for module in ('webview','pythonnet','clr_loader','pypdfium2_raw'):command+=['--collect-all',module]
    for module in ('matplotlib','pandas','scipy','torch','IPython','PyQt5','PyQt6','tkinter','pytest','jupyter'):command+=['--exclude-module',module]
    command.append(str(ROOT/'desktop_main.py'))
    env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join([str(ROOT/'.build-deps'),str(ROOT)])
    subprocess.run(command,cwd=ROOT,env=env,check=True)

if __name__=='__main__':main()
