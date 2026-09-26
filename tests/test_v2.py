import copy,io,json,tempfile,unittest,hashlib,threading
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from course_compiler.extract import unit
from course_compiler.parsers import commit_layout,table_cells,glm_layout,unlimited_layout,routing,make_model
from course_compiler.storage import Store,protect
from course_compiler.pipeline_v2 import compile_course

PROFILE={'provider':'openai','engine':'vision','model':'fixture','baseUrl':'https://example.invalid/v1','apiKey':'fixture-only'}
def page(text='Original source text must preserve the definition, conclusion and all examples.',n=1):
    src={'file':'lecture.pdf','fileId':'lecture-test','page':n};pid=f'lecture-test-page-{n:03d}'
    u=unit(pid,1,text,'paragraph',src,[.1,.1,.9,.3])
    return {'id':pid,'number':n,'title':text,'source':src,'units':[u],'rawUnits':[copy.deepcopy(u)],'rawText':text,'image':f'assets/page-{n}.jpg','imageRegions':[],'vectorCount':0,'needsOCR':False,'visualStatus':'pending','transcriptionStatus':'pending','warnings':[],'width':200,'height':100,'links':[]}

class V2Tests(unittest.TestCase):
    def test_routing_uses_one_path(self):
        p=page();self.assertEqual(routing(p)[0],'native')
        p['imageRegions']=[[.1,.3,.9,.9]];self.assertEqual(routing(p)[0],'vision')
        self.assertEqual(routing(page(),'vision')[0],'vision')
    def test_layout_contracts_normalize_native_pixels(self):
        x=glm_layout({'layout_details':[[{'label':'image','bbox_2d':[100,200,900,800]}]],'data_info':{'pages':[{'width':1000,'height':1000}]}})
        self.assertEqual(x['figures'][0]['bbox'],[.1,.2,.9,.8])
        x=unlimited_layout('<|det|>title [100, 200, 900, 300]<|/det|>Full title\n<|det|>image [100,400,900,800]<|/det|>')
        self.assertEqual(x['blocks'][0]['text'],'Full title');self.assertEqual(len(x['figures']),1)
    def test_table_preserves_blank_cells_and_merged_spans(self):
        cells=table_cells({'html':'<table><tr><th rowspan="2">A</th><td></td></tr><tr><td>B<br>C</td></tr></table>'})
        self.assertEqual([(c['row'],c['col']) for c in cells],[(0,0),(0,1),(1,1)])
        self.assertEqual(cells[-1]['text'],'B\nC');self.assertEqual(cells[0]['rowSpan'],2)
        cells=table_cells({'rows':[['A','',''],['','','']]});self.assertEqual(len(cells),6)
        with self.assertRaises(Exception):table_cells({'rows':[[{'text':'A','rowSpan':2},'B'],[{'text':'overlap','colSpan':2},'']]})
    def test_credentials_do_not_fall_back_between_providers(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'other-provider-secret'}):
            m=make_model({**PROFILE,'apiKey':''},Path('tmp/model-fixture'));self.assertFalse(m.available)
    def test_original_crop_and_anchors_survive_repeat(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            d=Path(d);p=page();(d/'assets').mkdir();Image.new('RGB',(200,100),(32,64,128)).save(d/p['image'])
            result={'blocks':[{'type':'paragraph','text':p['rawText'],'bbox':[.1,.1,.9,.3]}],'tables':[],'figures':[{'bbox':[.2,.4,.8,.9],'kind':'chart'}]}
            commit_layout(p,result,d);ids=[u['id'] for u in p['units']];fig=p['figures'][0]
            with Image.open(d/fig['image']) as im:self.assertEqual(im.size,(120,50))
            self.assertEqual(fig['source'],p['source'])
            self.assertTrue(any(u.get('reviewOnly') for u in p['units']))
            commit_layout(p,result,d);self.assertEqual([u['id'] for u in p['units']],ids)
            self.assertEqual(p['figures'][0]['id'],fig['id'])
    def test_missing_number_stays_in_original(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            p=page('A complete long definition with seven words and value 27.');commit_layout(p,{'blocks':[{'type':'paragraph','text':'A complete long definition with seven words and value','bbox':[.1,.1,.9,.3]}]},d)
            kept=[u for u in p['units'] if '27' in u['sourceText']];self.assertEqual(len(kept),1);self.assertFalse(kept[0].get('reviewOnly'));self.assertTrue(kept[0]['uncertain'])
    def test_pipeline_roles_and_resume_no_second_parse(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            d=Path(d);source=d/'lecture.pdf';source.write_bytes(b'fixture');p=page();files=[{'id':'lecture-test','name':'lecture.pdf','pages':[p]}]
            calls=[]
            class MockModel:
                available=True
                def __init__(self,name):self.model=name
                def request(self,system,payload,**kw):
                    calls.append(self.model)
                    if 'samples' in payload:return {'subject':'教学材料','style':'忠实、完整的学术翻译。','terminology':{}}
                    if 'headings' in payload:return {'terminology':{}}
                    return {'translations':[{'id':u['id'],'translatedText':'完整定义与全部例子。'} for u in payload.get('units',[])]}
            class MockParser:
                def __init__(self,*a):pass
                def parse(self,*a):raise AssertionError('Native page should not call parser')
            profiles={r:{**PROFILE,'model':r} for r in ('parse','translation','explanation')}
            with patch('course_compiler.pipeline_v2.extract_files',side_effect=lambda *a:copy.deepcopy(files)),patch('course_compiler.pipeline_v2.make_model',side_effect=lambda p,c:MockModel(p['model'])),patch('course_compiler.pipeline_v2.DocumentParser',MockParser):
                c=compile_course([source],d/'site',profiles,d/'cache',workers=1,explanations=False)
                self.assertEqual(c['metrics']['documentCalls'],0);self.assertEqual(c['quality']['readingTranslated'],1);self.assertEqual(set(calls),{'translation'})
                count=len(calls);c=compile_course([source],d/'site',profiles,d/'cache',workers=1,explanations=False)
                self.assertEqual(c['metrics']['resumedPages'],1);self.assertEqual(len(calls),count)
    def test_encrypted_profile_and_notebook_on_disk(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);public=store.save_settings({'profiles':{r:dict(PROFILE) for r in ('parse','translation','explanation')}})
            self.assertTrue(public['profiles']['parse']['hasApiKey']);self.assertNotIn('fixture-only',json.dumps(public));self.assertNotIn('fixture-only',(Path(d)/'settings.json').read_text())
            self.assertEqual(Store(d).profiles()['parse']['apiKey'],'fixture-only')
            public['profiles']['parse']['baseUrl']='https://another.invalid/v1';store.save_settings(public);self.assertEqual(store.profiles()['parse']['apiKey'],'')
            cid='course-0123456789abcdef';store.save_learning(cid,{'courseId':cid,'savedAt':20,'notes':[{'text':'latest'}]});store.save_learning(cid,{'courseId':cid,'savedAt':10,'notes':[]});self.assertEqual(Store(d).learning(cid)['notes'][0]['text'],'latest')
    def test_specialist_ocr_cannot_inherit_text_stage(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);store.save_settings({'profiles':{'parse':{**PROFILE,'engine':'glm-ocr'},'translation':{'inherit':True},'explanation':{'inherit':True}}})
            with self.assertRaises(ValueError):store.profiles()

if __name__=='__main__':unittest.main()
