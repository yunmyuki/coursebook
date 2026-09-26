import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from course_compiler.study_agent import CourseIndex,answer,StudyService,validate_action
from course_compiler.requests_control import RequestBudget
from course_compiler.storage import Store,atomic_json

CID='course-1234567890abcdef'
def course():
    return {'id':CID,'files':[{'name':'Lecture01.pdf','pages':[{'number':1,'units':[
        {'id':'u1','type':'paragraph','sourceText':'Price elasticity measures sensitivity of demand.','translatedText':'需求价格弹性衡量需求的敏感程度。'},
        {'id':'u2','type':'bullet','sourceText':'• Risk 😀 and return','translatedText':'风险与回报'},
        {'id':'u3','type':'paragraph','sourceText':'Archived noise','reviewOnly':True},
        {'id':'u4','type':'paragraph','sourceText':'Inflation affects interest rates.','translatedText':'通货膨胀影响利率。'}]}]}]}

class FakeModel:
    available=True
    def __init__(self,steps):self.steps=iter(steps);self.calls=[]
    def request(self,system,data,**kw):
        self.calls.append(data)
        result=next(self.steps);kw['validator'](result);return result

class AgentTests(unittest.TestCase):
    def test_bilingual_retrieval_excludes_archived(self):
        i=CourseIndex(course());self.assertEqual(i.search('需求弹性')[0]['contentId'],'u1');self.assertEqual(i.search('inflation')[0]['contentId'],'u4');self.assertEqual(i.search('Archived noise'),[])
    def test_selection_utf16_bullet_and_stale(self):
        i=CourseIndex(course());r={'contentId':'u2','layer':'source','start':5,'end':7,'text':'😀'}
        self.assertEqual(i.selection([r])[0]['text'],'😀')
        with self.assertRaises(ValueError):i.selection([{**r,'text':'bad'}])
        with self.assertRaises(ValueError):i.selection([{**r,'contentId':'u3'}])
    def test_agent_executes_search_and_read_with_exact_citations(self):
        m=FakeModel([{'action':'course_search','query':'inflation'},{'action':'read_content','contentIds':['u2']},{'action':'answer','text':'利率受通胀影响 [L1]','citations':['L1']}])
        result=answer(CourseIndex(course()),'查找相关段落',[],[],m,RequestBudget())
        self.assertEqual(result['sources'][0]['contentId'],'u4');self.assertEqual(len(m.calls),3)
        self.assertTrue(any(v.get('contentId')=='u2' for v in m.calls[-1]['evidence'].values()))
    def test_web_is_opt_in_and_citations_validated(self):
        m=FakeModel([{'action':'web_search','query':'latest rates'},{'action':'answer','text':'尚未联网核实。','citations':[]}])
        with patch('course_compiler.study_agent.web_search') as search:
            answer(CourseIndex(course()),'最新数据',[],[],m,RequestBudget(),search=search)
            search.assert_not_called()
        m=FakeModel([{'action':'web_search','query':'rates'},{'action':'answer','text':'检索摘要 [W1]','citations':['W1']}])
        def search(q,k,b):self.assertEqual(k,'separate-search-key');return [{'url':'https://example.com/rates','title':'Rates','text':'摘要'}]
        result=answer(CourseIndex(course()),'最新数据',[],[],m,RequestBudget(),'separate-search-key',search=search)
        self.assertEqual(result['sources'][0]['url'],'https://example.com/rates')
        with self.assertRaisesRegex(ValueError,'引用'):
            answer(CourseIndex(course()),'弹性',[],[],FakeModel([{'action':'answer','text':'虚构 [L99]','citations':['L99']}]),RequestBudget())
    def test_loop_limit_cancel_and_history_recall(self):
        m=FakeModel([{'action':'course_search','query':'risk'}]*5)
        with self.assertRaisesRegex(ValueError,'上限'):answer(CourseIndex(course()),'解释',[],[],m,RequestBudget())
        self.assertEqual(len(m.calls),5)
        stop=threading.Event();stop.set()
        with self.assertRaisesRegex(ValueError,'停止'):answer(CourseIndex(course()),'解释',[],[],m,RequestBudget(cancel=stop))
        m=FakeModel([{'action':'answer','text':'延续上文 [L1]','citations':['L1']}])
        out=answer(CourseIndex(course()),'再举一个例子',[],[{'role':'assistant','text':'前文','sources':[{'contentId':'u1'}]}],m,RequestBudget())
        self.assertEqual(out['sources'][0]['contentId'],'u1')
    def test_invalid_tool_arguments(self):
        for obj in ({'action':'shell'},{'action':'web_search','query':[]},{'action':'read_content','contentIds':[{}]},{'action':'answer','text':''}):
            with self.assertRaises(ValueError):validate_action(obj)
    def test_local_service_persists_and_rejects_parallel_question(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);atomic_json(store.course_path(CID)/'course.json',course());service=StudyService(store);gate=threading.Event()
            model=FakeModel([{'action':'answer','text':'解释需求弹性 [L1]','citations':['L1']}]);original=model.request
            def request(*a,**kw):gate.wait(2);return original(*a,**kw)
            model.request=request
            with patch.object(store,'profiles',return_value={'explanation':{}}),patch('course_compiler.study_agent.make_model',return_value=model):
                service.start(CID,{'question':'需求弹性'})
                with self.assertRaisesRegex(ValueError,'尚未结束'):service.start(CID,{'question':'重复'})
                gate.set()
                for _ in range(100):
                    snap=service.snapshot(CID)
                    if snap['run']['status']!='running':break
                    time.sleep(.01)
            self.assertEqual(snap['run']['status'],'complete');self.assertEqual(len(snap['messages']),2)
            self.assertEqual(StudyService(store).snapshot(CID)['messages'][1]['sources'][0]['contentId'],'u1')
            self.assertNotIn('cancel',snap['run'])
    def test_search_key_encrypted_and_public_redacted(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);settings=store.settings();settings['webSearch']={'apiKey':'test-bocha-secret'}
            result=store.save_settings(settings)
            self.assertTrue(result['webSearch']['hasApiKey']);self.assertNotIn('apiKey',result['webSearch'])
            self.assertNotIn('test-bocha-secret',(Path(d)/'settings.json').read_text())
            self.assertEqual(store.settings()['webSearch']['apiKey'],'test-bocha-secret')
            result['webSearch']={'clearKey':True};store.save_settings(result)
            self.assertFalse(store.settings(public=True)['webSearch']['hasApiKey'])

    def test_http_routes_and_cancel(self):
        import urllib.request
        from course_compiler.app_server import make_server
        from course_compiler.server import TOKEN
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            server=make_server(0,d);atomic_json(server.store.course_path(CID)/'course.json',course())
            worker=threading.Thread(target=server.serve_forever);worker.start();gate=threading.Event()
            model=FakeModel([{'action':'answer','text':'应被取消','citations':[]}]);original=model.request
            def request(*a,**kw):gate.wait(3);return original(*a,**kw)
            model.request=request
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_port}'
            def post(path,data):return json.load(opener.open(urllib.request.Request(base+path,json.dumps(data).encode(),{'Content-Type':'application/json','X-Course-Token':TOKEN})))
            try:
                with patch.object(server.store,'profiles',return_value={'explanation':{}}),patch('course_compiler.study_agent.make_model',return_value=model):
                    self.assertTrue(post('/api/assistant/'+CID,{'question':'解释需求弹性'})['id'])
                    self.assertTrue(post('/api/assistant-cancel/'+CID,{})['cancelled']);gate.set()
                    for _ in range(100):
                        snap=json.load(opener.open(base+'/api/assistant/'+CID))
                        if snap['run']['status']!='running':break
                        time.sleep(.01)
                self.assertEqual(snap['run']['status'],'cancelled');self.assertEqual(len(snap['messages']),1)
            finally:gate.set();server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
