import json,tempfile,threading,unittest,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from unittest.mock import patch,MagicMock
from course_compiler.search_providers import build_request,normalize,search,NoRedirect,PROVIDERS
from course_compiler.storage import Store,atomic_json,protect
from course_compiler.requests_control import RequestBudget
from course_compiler.model import ModelAuthorizationError

FIXTURES={
 'bocha':{'code':200,'data':{'webPages':{'value':[{'name':'Result','url':'https://example.com/','summary':'Evidence'}]}}},
 'baidu':{'references':[{'title':'Result','url':'https://example.com/','content':'Evidence','type':'web'}]},
 'tavily':{'results':[{'title':'Result','url':'https://example.com/','content':'Evidence'}]},
 'exa':{'results':[{'title':'Result','url':'https://example.com/','highlights':['Evidence']}]},
 'brave':{'web':{'results':[{'title':'Result','url':'https://example.com/','description':'Evidence','extra_snippets':['More']}] }},
 'serpapi':{'search_metadata':{'status':'Success'},'organic_results':[{'title':'Result','link':'https://example.com/','snippet':'Evidence'}]}
}

class SearchTests(unittest.TestCase):
 def test_official_request_contracts(self):
  expected={'bocha':('api.bochaai.com','Authorization','Bearer fixture'),'baidu':('qianfan.baidubce.com','Authorization','Bearer fixture'),'tavily':('api.tavily.com','Authorization','Bearer fixture'),'exa':('api.exa.ai','X-api-key','fixture'),'brave':('api.search.brave.com','X-subscription-token','fixture'),'serpapi':('serpapi.com',None,None)}
  for p,(host,header,value) in expected.items():
   with self.subTest(provider=p):
    req=build_request('学习方法 & evidence',{'provider':p,'apiKey':'fixture'})
    self.assertEqual(urllib.parse.urlsplit(req.full_url).hostname,host)
    if header:self.assertEqual(req.get_header(header),value)
    body=json.loads(req.data) if req.data else urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
    if p=='baidu':self.assertEqual(body['resource_type_filter'],[{'type':'web','top_k':5}]);self.assertEqual(body['messages'][0]['content'],'学习方法 & evidence')
    if p=='tavily':self.assertEqual(body['search_depth'],'basic');self.assertFalse(body['auto_parameters']);self.assertFalse(body['include_answer'])
    if p=='exa':self.assertEqual(body['type'],'fast');self.assertEqual(body['contents'],{'highlights':True,'text':False})
    if p=='brave':self.assertEqual(req.get_method(),'GET');self.assertEqual(body['q'],['学习方法 & evidence'])
    if p=='serpapi':self.assertEqual(body['api_key'],['fixture']);self.assertEqual(body['engine'],['google'])
  for engine in ('google','bing','baidu'):
   req=build_request('term',{'provider':'serpapi','apiKey':'fixture','engine':engine});self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)['engine'],[engine])
 def test_normalization_and_unsafe_links(self):
  for p,body in FIXTURES.items():
   with self.subTest(provider=p):
    rows=normalize(p,body);self.assertEqual(rows[0]['title'],'Result');self.assertIn('Evidence',rows[0]['text']);self.assertEqual(rows[0]['url'],'https://example.com/')
  rows=[{'title':'<b>标题</b> &amp; 内容','link':'http://example.com/x','rich_snippet':[{'extensions':['<em>词</em>']}]}]
  rows+= [{'title':'bad','link':u} for u in ['javascript:alert(1)','https://user:pass@example.com','https://bad\n.com','file:///c:/secret']]
  rows+=[rows[0]]
  out=normalize('serpapi',{'organic_results':rows});self.assertEqual(out,[{'title':'标题 & 内容','url':'http://example.com/x','text':'词'}])
  self.assertEqual(len(normalize('tavily',{'results':[{'url':f'https://example.com/{i}','content':'x'*4000} for i in range(12)]})),5)
  self.assertEqual(len(normalize('exa',{'results':[{'url':'https://example.com','highlights':['x'*4000]}]})[0]['text']),2000)
 def test_actual_transport_once_per_search_and_no_fallback(self):
  for p,body in FIXTURES.items():
   with self.subTest(provider=p):
    response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(body).encode();opener=MagicMock();opener.open.return_value=response
    with patch('course_compiler.search_providers.urllib.request.build_opener',return_value=opener):
     budget=RequestBudget(1);out=search('study',{'provider':p,'apiKey':'fixture'},budget);self.assertEqual(out[0]['title'],'Result');self.assertEqual(budget.calls,1);opener.open.assert_called_once()
     with self.assertRaises(ModelAuthorizationError):search('again',{'provider':p,'apiKey':'fixture'},budget)
     opener.open.assert_called_once()
  self.assertIsNone(NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.example'))
 def test_errors_are_redacted_and_not_retried(self):
  opener=MagicMock();opener.open.side_effect=urllib.error.HTTPError('https://serpapi.com/search?api_key=private-key',429,'private-key',{},None)
  with patch('course_compiler.search_providers.urllib.request.build_opener',return_value=opener):
   with self.assertRaises(ValueError) as e:search('study',{'provider':'serpapi','apiKey':'private-key'},RequestBudget())
   self.assertIn('429',str(e.exception));self.assertNotIn('private-key',str(e.exception));opener.open.assert_called_once()
  for body in ({'error':'private-key'}, {'code':'bad'}, {'results':{}}, []):
   with self.assertRaises(ValueError):normalize('tavily',body)
  for provider in PROVIDERS:
   with self.assertRaises(ValueError):normalize(provider,{})
  stop=threading.Event();stop.set()
  with patch('course_compiler.search_providers.urllib.request.build_opener') as network:
   with self.assertRaises(ModelAuthorizationError):search('study',{'provider':'bocha','apiKey':'fixture'},RequestBudget(cancel=stop))
   network.assert_not_called()
 def test_invalid_config_never_requests_network(self):
  with patch('course_compiler.search_providers.urllib.request.build_opener') as network:
   for profile in ({'provider':'unknown','apiKey':'fixture'},{'provider':'serpapi','apiKey':'fixture','engine':'evil'},{'provider':'baidu','apiKey':''},{'provider':'tavily','apiKey':'secret\nheader'}):
    with self.assertRaises(ValueError):search('q',profile,RequestBudget())
   network.assert_not_called()
 def test_migrate_old_bocha_and_isolate_saved_keys(self):
  with tempfile.TemporaryDirectory(dir='tmp') as d:
   store=Store(d);base=store.settings();store.save_settings(base)
   raw=json.loads((Path(d)/'settings.json').read_text());raw['webSearch']={'provider':'bocha','encryptedKey':protect('old-bocha')};atomic_json(Path(d)/'settings.json',raw)
   self.assertEqual(store.search_profile()['apiKey'],'old-bocha')
   public=store.settings(True);public['webSearch']={'provider':'tavily'};store.save_settings(public)
   self.assertEqual(store.search_profile()['apiKey'],'');self.assertEqual(store.search_profile({'provider':'bocha'})['apiKey'],'old-bocha')
   public=store.settings(True);public['webSearch']={'provider':'serpapi','profiles':{'tavily':{'apiKey':'tv-secret'},'serpapi':{'apiKey':'serp-secret','engine':'bing'}}};store.save_settings(public)
   self.assertEqual(store.search_profile()['engine'],'bing');self.assertEqual(store.search_profile()['apiKey'],'serp-secret')
   self.assertEqual(store.search_profile({'provider':'tavily'})['apiKey'],'tv-secret')
   raw=(Path(d)/'settings.json').read_text();pub=json.dumps(store.settings(True))
   for secret in ('old-bocha','tv-secret','serp-secret'):self.assertNotIn(secret,raw);self.assertNotIn(secret,pub)
   public=store.settings(True);public['webSearch']={'provider':'tavily','profiles':{'tavily':{'clearKey':True}}};store.save_settings(public)
   self.assertEqual(store.search_profile()['apiKey'],'');self.assertEqual(store.search_profile({'provider':'serpapi'})['apiKey'],'serp-secret')
   public=store.settings(True);public.pop('webSearch');store.save_settings(public)
   self.assertEqual(store.search_profile({'provider':'bocha'})['apiKey'],'old-bocha')
 def test_probe_http_uses_only_requested_provider_without_saving(self):
  from course_compiler.app_server import make_server
  from course_compiler.server import TOKEN
  with tempfile.TemporaryDirectory(dir='tmp') as d:
   server=make_server(0,d);t=threading.Thread(target=server.serve_forever);t.start()
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));url=f'http://127.0.0.1:{server.server_port}/api/search/probe'
   try:
    with patch('course_compiler.search_providers.search',return_value=normalize('tavily',FIXTURES['tavily'])) as run:
     payload={'provider':'serpapi','engine':'bing','apiKey':'probe-only'}
     req=urllib.request.Request(url,json.dumps(payload).encode(),{'Content-Type':'application/json','X-Course-Token':TOKEN})
     result=json.load(opener.open(req));self.assertTrue(result['ok']);self.assertIn('Bing',result['message']);self.assertEqual(run.call_args.args[1],payload)
     self.assertEqual(run.call_args.args[0],'effective study methods')
    self.assertFalse((Path(d)/'settings.json').exists())
   finally:server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
