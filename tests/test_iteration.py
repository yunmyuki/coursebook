import copy,io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from course_compiler.parsers import paddle_layout,glm_layout,validate_layout,commit_layout,DocumentParser
from course_compiler.model import Model,ModelError,ModelAuthorizationError
from course_compiler.requests_control import RequestBudget,post_document
from course_compiler.storage import Store,atomic_json
from course_compiler.review import review_course,suggest_translation
from test_v2 import page,PROFILE

class IterationTests(unittest.TestCase):
    def test_native_layout_http_contracts_and_cache(self):
        from PIL import Image
        for engine in ('paddle-layout','glm-ocr'):
            with self.subTest(engine=engine),tempfile.TemporaryDirectory(dir='tmp') as d:
                root=Path(d);p=page();(root/'assets').mkdir();Image.new('RGB',(200,100),'white').save(root/p['image'])
                profile={**PROFILE,'engine':engine,'authScheme':'token' if engine=='paddle-layout' else 'Bearer'}
                parser=DocumentParser(profile,root/'cache');parser.model.budget=RequestBudget(1)
                raw=({'result':{'layoutParsingResults':[{'prunedResult':{'parsing_res_list':[{'block_label':'text','block_bbox':[20,10,180,30],'block_content':'Complete text'}]}}]}}
                    if engine=='paddle-layout' else {'layout_details':[[{'index':1,'label':'text','bbox_2d':[.1,.1,.9,.3],'content':'Complete text'}]]})
                with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(raw).encode())) as send:
                    parsed=parser.parse(p,root);self.assertEqual(parser.parse(p,root),parsed);self.assertEqual(send.call_count,1)
                req=send.call_args.args[0];body=json.loads(req.data)
                if engine=='paddle-layout':
                    self.assertTrue(req.full_url.endswith('/layout-parsing'));self.assertEqual(req.get_header('Authorization'),'token fixture-only')
                    self.assertEqual(body['fileType'],1);self.assertTrue(body['useLayoutDetection']);self.assertTrue(body['useOcrForImageBlock'])
                    self.assertFalse(body['returnMarkdownImages']);self.assertFalse(body['useChartRecognition']);self.assertFalse(body['visualize'])
                else:self.assertTrue(req.full_url.endswith('/layout_parsing'));self.assertTrue(body['file'].startswith('data:image/jpeg;base64,'))
                self.assertEqual(parser.model.budget.snapshot()['cacheHits'],1)

    def test_native_api_retries_transient_errors_only(self):
        error=lambda code:urllib.error.HTTPError('https://example.invalid',code,'fixture',{},io.BytesIO(b'{}'))
        budget=RequestBudget(2)
        with patch('urllib.request.urlopen',side_effect=[error(429),io.BytesIO(b'{"ok":true}')]) as send,patch('course_compiler.requests_control.time.sleep'):
            self.assertEqual(post_document('https://example.invalid',{},'fixture',budget),{'ok':True});self.assertEqual(send.call_count,2)
        with patch('urllib.request.urlopen',side_effect=error(401)) as send:
            with self.assertRaises(ModelAuthorizationError):post_document('https://example.invalid',{},'fixture',RequestBudget(2))
            self.assertEqual(send.call_count,1)

    def test_cancelled_v2_retains_cached_explanations_without_progress(self):
        import threading
        from course_compiler.pipeline_v2 import compile_course,course_id
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'lecture.pdf';source.write_bytes(b'fixture');p=page();files=[{'id':'lecture-test','name':'lecture.pdf','pages':[p]}]
            explanation={'id':'explanation-test','relatedContentIds':[p['units'][0]['id']],'source':p['source'],'title':'Existing explanation'}
            saved=root/'cache'/course_id([source])/(p['id']+'.json');atomic_json(saved,{'page':p,'explanations':[explanation],'stages':{}})
            cancel=threading.Event();cancel.set();events=[]
            with patch('course_compiler.pipeline_v2.extract_files',return_value=files),patch('urllib.request.urlopen',side_effect=AssertionError('Cancelled run must not call API')):
                result=compile_course([source],root/'site',{r:dict(PROFILE) for r in ('parse','translation','explanation')},root/'cache',cancel=cancel,progress=lambda *e:events.append(e))
            self.assertEqual(result['explanations'],[explanation]);self.assertEqual(result['status'],'cancelled')
            self.assertFalse(any(e[0]=='page-complete' for e in events))

    def test_identical_concurrent_requests_are_coalesced(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            m=Model(provider='openai',base_url='https://example.invalid/v1',model='fixture',api_key='fixture',cache=d);m.budget=RequestBudget(1)
            def response(*a,**kw):
                time.sleep(.03)
                return io.BytesIO(b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}')
            with patch('urllib.request.urlopen',side_effect=response) as send,ThreadPoolExecutor(max_workers=2) as pool:
                values=list(pool.map(lambda _:m.request('test','identical'),range(2)))
            self.assertEqual(values,[{'ok':True}]*2);self.assertEqual(send.call_count,1)
    def test_paddle_full_pipeline_preserves_order_table_and_figure(self):
        raw={'errorCode':0,'result':{'layoutParsingResults':[{'prunedResult':{'parsing_res_list':[
            {'block_label':'text','block_bbox':[500,100,900,200],'block_content':'Right column first'},
            {'block_label':'table','block_bbox':[100,300,900,500],'block_content':'<table><tr><td>−5.0%</td><td></td></tr></table>'},
            {'block_label':'chart','block_bbox':[100,600,800,900],'block_content':'Axis label'}]}}]}}
        result=validate_layout(paddle_layout(raw,(1000,1000)))
        self.assertEqual(result['blocks'][0]['bbox'],[.5,.1,.9,.2]);self.assertEqual(result['tables'][0]['readingOrder'],1)
        self.assertEqual(result['figures'][0]['readingOrder'],2);self.assertEqual(result['blocks'][1]['text'],'Axis label')
        raw['result']['layoutParsingResults'][0]['prunedResult']['parsing_res_list'][-1]['block_content']='Reference https://example.com <img src="x">'
        self.assertEqual(paddle_layout(raw,(1000,1000))['blocks'][1]['text'],'Reference https://example.com')
        with self.assertRaises(ModelError):paddle_layout({'result':{'layoutParsingResults':[]}},(1000,1000))

    def test_original_number_sign_cannot_be_archived_by_word_coverage(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            for before,after in [('5.0%','−5.0%'),('5','15'),('rate rate','rate')]:
                p=page(before);commit_layout(p,{'blocks':[{'text':after,'bbox':[.1,.1,.9,.3]}]},d)
                original=next(u for u in p['units'] if u['origin']!='document-parser')
                self.assertFalse(original.get('reviewOnly'));self.assertTrue(original['uncertain'])

    def test_empty_and_missing_coordinates_are_rejected(self):
        for result in [{},{'blocks':[{'text':'hello'}]},{'tables':[{'bbox':[0,0,1,1],'rows':[]}]}]:
            with self.assertRaises(ModelError):validate_layout(result)

    def test_budget_counts_retries_and_cache_is_free(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            m=Model(provider='openai',base_url='https://example.invalid/v1',model='fixture',api_key='fixture',cache=d);m.max_attempts=4;m.budget=RequestBudget(2)
            with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('fixture')) as send,patch('course_compiler.requests_control.time.sleep'):
                with self.assertRaises(ModelAuthorizationError):m.request('test','test')
                self.assertEqual(send.call_count,2)
            m.budget=RequestBudget(1)
            raw={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':4,'completion_tokens':3}}
            with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(raw).encode())):
                self.assertEqual(m.request('test','test'),{'ok':True})
            with patch('urllib.request.urlopen',side_effect=AssertionError('cache must not call API')):
                self.assertEqual(m.request('test','test'),{'ok':True})
            self.assertEqual(m.budget.snapshot()['requests'],1);self.assertEqual(m.budget.snapshot()['cacheHits'],1)

    def test_cached_invalid_layout_can_recover_without_infinite_bad_cache(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            m=Model(provider='openai',base_url='https://example.invalid/v1',model='fixture',api_key='fixture',cache=d)
            def response(content):return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(content)},'finish_reason':'stop'}]}).encode())
            with patch('urllib.request.urlopen',return_value=response({})):m.request('parse','page')
            valid={'blocks':[{'text':'Full text','bbox':[.1,.1,.9,.9]}]}
            with patch('urllib.request.urlopen',return_value=response(valid)) as send:
                self.assertEqual(m.request('parse','page',validator=validate_layout),valid);self.assertEqual(send.call_count,1)

    def test_api_probe_never_reuses_key_for_a_different_address(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);store.save_settings({'settingsMode':'simple','requestLimit':25,'profiles':{r:dict(PROFILE) for r in ('parse','translation','explanation')}})
            p=store.probe_profile('parse',{**PROFILE,'apiKey':'','baseUrl':'https://another.invalid/v1'})
            self.assertEqual(p.get('apiKey',''),'');self.assertEqual(store.settings(public=True)['requestLimit'],25)
            self.assertNotIn('fixture-only',json.dumps(store.settings(public=True)))

    def test_review_draft_never_saves_and_stale_edit_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);p=page('12.5%');c={'id':'course-0123456789abcdef','files':[{'pages':[p]}],'explanations':[]};site=store.course_path(c['id']);atomic_json(site/'course.json',c)
            before=(site/'course.json').read_bytes();draft=suggest_translation(store,c['id'],{'contentId':p['units'][0]['id'],'sourceText':'12.6%'})
            self.assertEqual(draft['translatedText'],'12.6%');self.assertEqual(before,(site/'course.json').read_bytes())
            with self.assertRaises(ValueError):review_course(store,c['id'],{'contentId':p['units'][0]['id'],'sourceText':'12.6%','translatedText':'12.6%','expectedSourceText':'stale'})

if __name__=='__main__':unittest.main()
