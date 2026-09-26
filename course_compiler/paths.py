"""Separate bundled application resources from the user's writable local workspace."""
import os
import sys
from pathlib import Path

def resource_root():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))

def data_root():
    if os.environ.get('COURSE_DATA_DIR'):return Path(os.environ['COURSE_DATA_DIR']).resolve()
    if getattr(sys,'frozen',False):return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Course Compiler'
    return resource_root()/'local-data'
