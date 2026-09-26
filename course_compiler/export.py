import json
import shutil
import zipfile
from pathlib import Path


def export_site(course, output, zip_output=None):
    output=Path(output)
    from .paths import resource_root
    web=resource_root()/'web'
    for name in ('index.html','styles.css','notion.css','app.js','assistant.js','review.js','favicon.svg'):
        if (web/name).exists():
            shutil.copy2(web/name,output/name)
    if (web/'vendor').exists():
        shutil.copytree(web/'vendor',output/'vendor',dirs_exist_ok=True)
    # Script assignment works on file://; fetch()/ES modules do not reliably work there.
    data=json.dumps(course,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (output/'course-data.js').write_text('window.COURSE_DATA = '+data+';\n','utf-8')
    if zip_output:
        target=Path(zip_output).resolve()
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for p in sorted(output.rglob('*')):
                relative=p.relative_to(output)
                allowed=relative.parts[0] in ('assets','sources','vendor') or str(relative) in ('index.html','styles.css','notion.css','app.js','assistant.js','review.js','favicon.svg','course-data.js','course.json','terminology.json','quality-report.json')
                if allowed and p.is_file() and p.resolve()!=target and not any(part.startswith('.') for part in relative.parts):
                    archive.write(p,relative)
        return target
