import copy,hashlib,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from PIL import Image
from course_compiler.storage import Store,atomic_json
from course_compiler.materials import plan_addition,add_materials,validate_addition,ordered_chapters
from course_compiler.pipeline import quality,build_sections
from course_compiler.pipeline_v2 import compile_course
from course_compiler.translation_context import validate_context,context_samples
from course_compiler.parsers import commit_layout,validate_layout
from course_compiler.model import ModelError
from test_v2 import page,PROFILE

def material_file(name,digest,n=1):
    fid='lecture-'+digest[:12];p=page('Complete original definition and every example are preserved.',n)
    p['id']=fid+'-page-001';p['source']={'file':name,'fileId':fid,'page':1};p['image']='assets/'+fid+'/page.jpg'
    for u in p['units']:
        u.update(id='content-'+p['id'],source=dict(p['source']),translatedText='完整的定义与全部示例。',translationStatus='complete')
    p['rawUnits']=copy.deepcopy(p['units']);p.update(visualStatus='complete',transcriptionStatus='complete')
    f={'id':fid,'name':name,'sha256':digest,'order':1,'sourceUrl':'sources/'+fid+'.pdf','pages':[p]};build_sections([f]);return f

class ProductFeaturesTests(unittest.TestCase):
    def test_material_addition_http_job_commits_only_after_confirmation(self):
        import urllib.request,time
        from course_compiler.app_server import make_server
        from course_compiler.server import TOKEN
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store,c,path,digest=self.setup_course(d)
            store.save_settings({'profiles':{r:PROFILE for r in ('parse','translation','explanation')}})
            server=make_server(0,d);thread=threading.Thread(target=server.serve_forever);thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_port}'
            def post(endpoint,payload):
                req=urllib.request.Request(base+endpoint,json.dumps(payload).encode(),{'Content-Type':'application/json','X-Course-Token':TOKEN})
                return json.load(opener.open(req))
            try:
                with patch('course_compiler.materials.compile_course',side_effect=self.new_compiler(path,digest)) as compile_new:
                    plan=post('/api/materials/plan',{'courseId':c['id'],'files':[digest[:16]]});self.assertFalse(compile_new.called)
                    self.assertEqual(post('/api/materials/add',plan)['id'],c['id'])
                    for _ in range(100):
                        job=json.load(opener.open(base+'/api/jobs/'+c['id']))
                        if job['status']!='running':break
                        time.sleep(.02)
                    self.assertEqual(job['status'],'complete');self.assertTrue(job['committed']);self.assertEqual(compile_new.call_count,1)
                    self.assertEqual(json.load(opener.open(base+'/api/library'))[0]['pages'],3)
            finally:server.shutdown();server.server_close();thread.join()

    def setup_course(self,root):
        store=Store(root);cid='course-0123456789abcdef'
        files=[material_file('Lecture 1.pdf','a'*64),material_file('Lecture 3.pdf','b'*64)]
        for i,f in enumerate(files):f['order']=i+1;f['chapters'][0]['title']='Chapter '+str(1+i*2)+': Asset Pricing'
        c={'id':cid,'title':'金融学','subtitle':'fixture','files':files,'explanations':[],'terminology':{'Return':'收益率'},'translationContext':{'subject':'金融学','style':'采用金融学术语，忠实完整。','status':'generated'}}
        c['quality']=quality(c);atomic_json(store.course_path(cid)/'course.json',c);store.save_course({'id':cid,'title':c['title'],'fileIds':['a'*16],'status':'complete'})
        store.save_learning(cid,{'courseId':cid,'savedAt':5,'notes':[{'id':'personal','contentId':files[0]['pages'][0]['units'][0]['id'],'text':'My note'}]})
        p=store.root/'input'/'temporary'/'Lecture 2.pdf';p.parent.mkdir(parents=True);w=PdfWriter();w.add_blank_page(width=200,height=100);w.write(p)
        digest=hashlib.sha256(p.read_bytes()).hexdigest();dest=store.root/'input'/digest[:16]/p.name;dest.parent.mkdir();p.replace(dest)
        return store,c,dest,digest

    def new_compiler(self,path,digest,seen=None,partial=False):
        def run(paths,output,profiles,cache,**kwargs):
            if seen is not None:seen.update(paths=paths,kwargs=kwargs)
            f=material_file(path.name,digest)
            if partial:f['pages'][0]['units'][0].update(translatedText=None,translationStatus='pending')
            c={'id':'course-ffffffffffffffff','title':'New','files':[f],'explanations':[],'terminology':{'Return':'回报'},'translationContext':{'subject':'金融学','style':'完整准确','status':'generated'},'status':'finished','metrics':{'requests':0}}
            c['quality']=quality(c);output=Path(output);asset=output/f['pages'][0]['image'];asset.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(200,100),'white').save(asset)
            src=output/f['sourceUrl'];src.parent.mkdir(parents=True,exist_ok=True);src.write_bytes(path.read_bytes());return c
        return run

    def test_confirmed_insertion_keeps_identity_notes_and_original_content(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store,c,path,digest=self.setup_course(d);before_notes=(store.root/'notes'/(c['id']+'.json')).read_bytes();seen={}
            plan=plan_addition(store,c['id'],[digest[:16]])
            self.assertEqual(plan['materials'][0]['beforeChapterId'],c['files'][1]['chapters'][0]['id'])
            self.assertEqual(len(json.loads((store.course_path(c['id'])/'course.json').read_text('utf-8'))['files']),2)
            # A manual override puts it at the course beginning.
            plan['materials'][0]['beforeChapterId']=c['files'][0]['chapters'][0]['id']
            settings={'workers':1,'parseMode':'adaptive','requestLimit':10}
            with patch('course_compiler.materials.compile_course',side_effect=self.new_compiler(path,digest,seen)):
                result=add_materials(store,plan,settings,{},lambda *a:None,threading.Event())
            merged=result['course'];self.assertTrue(result['committed']);self.assertEqual(merged['id'],c['id']);self.assertEqual(merged['files'][:2],c['files'])
            self.assertEqual(ordered_chapters(merged)[0]['fileName'],'Lecture 2.pdf');self.assertEqual(merged['terminology']['Return'],'收益率')
            self.assertEqual(seen['paths'],[path]);self.assertEqual(seen['kwargs']['translation_context'],c['translationContext']);self.assertEqual(before_notes,(store.root/'notes'/(c['id']+'.json')).read_bytes())
            self.assertEqual(quality(merged)['errors'],[]);self.assertTrue((store.course_path(c['id'])/'course-data.js').exists())
            with self.assertRaisesRegex(ValueError,'已在课程'):plan_addition(store,c['id'],[digest[:16]])
            with self.assertRaisesRegex(ValueError,'已更新'):validate_addition(store,plan)

    def test_partial_addition_does_not_publish_or_touch_course(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store,c,path,digest=self.setup_course(d);plan=plan_addition(store,c['id'],[digest[:16]]);target=store.course_path(c['id'])/'course.json';before=target.read_bytes()
            with patch('course_compiler.materials.compile_course',side_effect=self.new_compiler(path,digest,partial=True)):
                result=add_materials(store,plan,{'workers':1,'parseMode':'adaptive'}, {},lambda *a:None,threading.Event())
            self.assertFalse(result['committed']);self.assertEqual(target.read_bytes(),before)
            plan['materials'][0]['beforeChapterId']='invented-anchor'
            with self.assertRaisesRegex(ValueError,'有效的章节'):validate_addition(store,plan)

    def test_translation_context_precedes_translation_and_is_cached(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);src=root/'lecture.pdf';src.write_bytes(b'fixture');files=[{'id':'lecture-test','name':src.name,'pages':[page()]}];calls=[]
            class Model:
                model='fixture';available=True
                def request(self,system,payload,**kwargs):
                    calls.append((system,payload))
                    if 'samples' in payload:return {'subject':'统计学','style':'使用统计学术语，保留推导。','terminology':{'power':'检验效能'}}
                    return {'translations':[{'id':u['id'],'translatedText':'完整定义。'} for u in payload['units']]}
            with patch('course_compiler.pipeline_v2.extract_files',side_effect=lambda *a:copy.deepcopy(files)),patch('course_compiler.pipeline_v2.make_model',return_value=Model()):
                c=compile_course([src],root/'site',{r:PROFILE for r in ('parse','translation','explanation')},root/'cache',explanations=False)
                self.assertIn('samples',calls[0][1]);self.assertEqual(calls[1][1]['translationContext']['subject'],'统计学');self.assertEqual(calls[1][1]['terminology']['power'],'检验效能');self.assertNotIn('Marginal Cost',c['terminology'])
                count=len(calls);compile_course([src],root/'site',{r:PROFILE for r in ('parse','translation','explanation')},root/'cache',explanations=False)
                self.assertEqual(len(calls),count);self.assertEqual(c['translationContext']['status'],'generated')
            self.assertLessEqual(len(context_samples([{'pages':[page(n=i) for i in range(200)]}])),20)
            with self.assertRaises(ModelError):validate_context({'subject':'Statistics'})

    def test_chart_origin_is_linked_without_changing_text_or_mislabeling_body(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            p=page();path=Path(d)/p['image'];path.parent.mkdir();Image.new('RGB',(200,100),'white').save(path)
            result={'blocks':[{'text':'Body paragraph','bbox':[.1,.1,.9,.2]},{'text':'Annual return','bbox':[.2,.5,.5,.6],'contentOrigin':'figure-transcription'}],'figures':[{'kind':'chart','bbox':[.1,.4,.9,.9]}]}
            commit_layout(p,result,d);labels=[u for u in p['units'] if u['sourceText']=='Annual return'];self.assertEqual(labels[0]['contentOrigin'],'figure-transcription');self.assertEqual(labels[0]['figureIds'],[p['figures'][0]['id']]);self.assertEqual(labels[0]['rawText'],'Annual return')
            self.assertFalse(next(u for u in p['units'] if u['sourceText']=='Body paragraph').get('figureIds'))
            result['blocks'][0]['contentOrigin']='figure-description'
            with self.assertRaisesRegex(ModelError,'解读不能混入原文'):validate_layout(result)

    def test_resume_of_original_compile_does_not_remove_added_materials(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store,c,path,digest=self.setup_course(d)
            c['materialHistory']=[{'materials':[]}];c['readingOrder']=[ch['id'] for f in c['files'] for ch in f['chapters']]
            untouched=copy.deepcopy(c['files'][1]);profiles={r:PROFILE for r in ('parse','translation','explanation')}
            with patch('course_compiler.pipeline_v2.extract_files',return_value=copy.deepcopy(c['files'][:1])):
                resumed=compile_course([path],Path(d)/'resume',profiles,Path(d)/'cache',ai=False,retained_course=c)
            self.assertEqual(resumed['files'][1],untouched);self.assertEqual(resumed['readingOrder'],c['readingOrder']);self.assertEqual(resumed['quality']['errors'],[])

if __name__=='__main__':unittest.main()
