"""Strict rectangular OTSL grid decoding; span markers never become empty cells."""
import re
from html import escape
from .model import ModelError

def to_html(text):
    parts=re.split(r'(<(?:fcel|ecel|lcel|ucel|xcel|nl)>)',text)
    # Some endpoints strip the initial special token but keep the first cell text.
    if parts[0].strip():parts=['','<fcel>']+parts
    grid=[];row=[];origins={}
    for i in range(1,len(parts),2):
        token=parts[i];content=parts[i+1].strip() if i+1<len(parts) else ''
        r=len(grid);c=len(row)
        if token=='<nl>':
            if content:raise ModelError('OTSL 行结束标记后出现未定位内容。')
            if row:grid.append(row);row=[]
            continue
        if token in ('<fcel>','<ecel>'):
            origin=(r,c);origins[origin]=content;row.append(origin)
        else:
            if content:raise ModelError('OTSL 合并占位符包含异常内容。')
            if token=='<lcel>' and c:origin=row[-1]
            elif token=='<ucel>' and r and c<len(grid[-1]):origin=grid[-1][c]
            elif token=='<xcel>' and r and c and c<len(grid[-1]) and row[-1]==grid[-1][c]:origin=row[-1]
            else:raise ModelError('OTSL 合并单元格引用无效。')
            row.append(origin)
    if row:grid.append(row)
    if not grid or len({len(r) for r in grid})!=1:raise ModelError('OTSL 表格行列不完整。')
    spans={}
    for r,row in enumerate(grid):
        for c,origin in enumerate(row):spans.setdefault(origin,[]).append((r,c))
    html=['<table>']
    for r,row in enumerate(grid):
        html.append('<tr>')
        for c,origin in enumerate(row):
            if origin!=(r,c):continue
            cells=spans[origin];rs=max(p[0] for p in cells)-r+1;cs=max(p[1] for p in cells)-c+1
            if set(cells)!={(y,x) for y in range(r,r+rs) for x in range(c,c+cs)}:raise ModelError('OTSL 合并区域不是矩形。')
            html.append(f'<td rowspan="{rs}" colspan="{cs}">{escape(origins[origin]).replace(chr(10),"<br>")}</td>')
        html.append('</tr>')
    return ''.join(html)+'</table>'
