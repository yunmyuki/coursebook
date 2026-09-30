"""Derived, source-only Markdown; canonical JSON remains authoritative for anchors."""
from html import escape
from urllib.parse import quote

def transcript(course):
    output=['# '+escape(course.get('title','Coursebook')),
            '> 原讲义转录。译文、学习记录和 AI 回答保存在独立数据层；待复核内容保留标记。']
    for file in course.get('files',[]):
        for page in file.get('pages',[]):
            output.append(f'<a id="{escape(page["id"],quote=True)}"></a>\n\n## {escape(page["source"]["file"])} · {page["number"]}')
            units=[u for u in page['units'] if not u.get('reviewOnly')]
            figures=page.get('figures',[]);tables={};items=[]
            for u in units:
                tid=u.get('tableId')
                if tid:
                    if tid not in tables:tables[tid]=[];items.append({'tableId':tid,'readingOrder':u.get('readingOrder',1e9)})
                    tables[tid].append(u)
                else:items.append(u)
            items+=figures
            for item in sorted(items,key=lambda i:i.get('readingOrder',1e9)):
                if 'tableId' in item:
                    rows={}
                    for cell in tables[item['tableId']]:rows.setdefault(cell['row'],[]).append(cell)
                    markup=['<table>']
                    for row in sorted(rows):
                        markup.append('<tr>')
                        for c in sorted(rows[row],key=lambda c:c['col']):
                            markup.append(f'<td id="{escape(c["id"],quote=True)}" rowspan="{c.get("rowSpan",1)}" colspan="{c.get("colSpan",1)}">{escape(c["sourceText"]).replace(chr(10),"<br>")}</td>')
                        markup.append('</tr>')
                    output.append(''.join(markup)+'</table>');continue
                output.append(f'<a id="{escape(item["id"],quote=True)}"></a>')
                if 'image' in item:output.append(f'![原讲义图示]({quote(item["image"],safe="/")})');continue
                text=escape(item['sourceText']);kind=item['type']
                if item.get('uncertain'):output.append('> 待复核')
                if item.get('contentOrigin')=='figure-transcription':output.append('> 图中可见文字')
                if kind=='title':text='### '+text
                elif kind=='bullet':text='  '*item.get('level',0)+'- '+text.lstrip('•●▪◦‣ ')
                elif kind=='formula':text='$$\n'+item.get('latex',item['sourceText'])+'\n$$'
                elif kind=='code':text='<pre><code>'+text+'</code></pre>'
                output.append(text)
    return '\n\n'.join(output)+'\n'
