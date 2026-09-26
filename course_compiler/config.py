"""Read local settings without executing shell syntax or exposing credential values."""
import os
import re
from pathlib import Path


def local_settings(path=None):
    values=dict(os.environ)
    path=Path(path) if path else Path(__file__).resolve().parent.parent/'.env.local'
    if path.is_file():
        for line in path.read_text('utf-8-sig').splitlines():
            match=re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$',line)
            if not match:continue
            key,value=match.groups()
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            else:value=re.split(r'\s+#',value,maxsplit=1)[0].rstrip()
            values[key]=value
    return values
