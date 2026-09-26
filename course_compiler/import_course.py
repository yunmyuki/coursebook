"""Import course data and original assets; always regenerate trusted application code."""
import hashlib
import json
import re
import zipfile
from pathlib import Path,PurePosixPath
from .storage import atomic_json
from .pipeline import quality
from .export import export_site

def import_course(stream,store):
    with zipfile.ZipFile(stream) as z:
        infos=z.infolist()
        if len(infos)>8000 or sum(i.file_size for i in infos)>1024**3:raise ValueError('课程 ZIP 体积过大。')
        names={i.filename for i in infos}
        if 'course.json' not in names:raise ValueError('请选择 Course Compiler 导出的课程 ZIP。')
        course=json.loads(z.read('course.json'))
        cid=course.get('id','');site=store.course_path(cid)
        files=course.get('files')
        if not isinstance(files,list) or not files:raise ValueError('课程数据无效。')
        assets=set()
        for f in files:
            assets.add(f['sourceUrl'])
            for p in f['pages']:
                assets.add(p['image']);assets.update(g['image'] for g in p.get('figures',[]))
        for name in assets:
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or path.parts[0] not in ('assets','sources') or path.suffix.lower() not in ('.pdf','.pptx','.ppt','.png','.jpg','.jpeg','.webp') or name not in names:raise ValueError('课程包含无效资源路径。')
        report=quality(course)
        if report['errors']:raise ValueError('课程关联数据无效：'+report['errors'][0])
        for f in files:
            if hashlib.sha256(z.read(f['sourceUrl'])).hexdigest()!=f['sha256']:raise ValueError('原讲义校验值不匹配。')
        site.mkdir(parents=True,exist_ok=True)
        if (site/'course.json').exists():
            backup=store.root/'backups'/cid;backup.mkdir(parents=True,exist_ok=True)
            previous=(site/'course.json').read_bytes();(backup/(hashlib.sha256(previous).hexdigest()[:12]+'.json')).write_bytes(previous)
        for name in assets:
            target=site/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
        course['quality']=report
        for name,value in [('course.json',course),('quality-report.json',report),('terminology.json',course.get('terminology',{}))]:atomic_json(site/name,value)
        export_site(course,site)
        ready=report['visualValidated']==report['pages'] and report['transcriptionValidated']==report['pages'] and report['readingTranslated']==report['readingUnits']
        item={'id':cid,'title':course['title'],'pages':report['pages'],'figures':report.get('figures',0),'updatedAt':course.get('compiledAt'),'status':'complete' if ready else 'partial','quality':report,'fileIds':[],'readerUrl':f'/courses/{cid}/index.html','downloadUrl':f'/download/{cid}.zip'}
        store.save_course(item);return item
