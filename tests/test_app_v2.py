import io,json,tempfile,threading,unittest,urllib.request,urllib.error,zipfile,hashlib
from pathlib import Path
from pypdf import PdfWriter
from course_compiler.app_server import make_server
from course_compiler.import_course import import_course
from course_compiler.storage import Store
from course_compiler.server import TOKEN
from test_v2 import page

class AppTests(unittest.TestCase):
    def test_learning_and_library_api_survive_restart(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            server=make_server(0,d);thread=threading.Thread(target=server.serve_forever);thread.start();url=f'http://127.0.0.1:{server.server_port}'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                status=json.load(opener.open(url+'/api/status'));self.assertEqual(status['version'],'2.0.0');self.assertNotIn('apiKey',json.dumps(status['settings']))
                state={'courseId':'course-0123456789abcdef','savedAt':10,'notes':[{'id':'note','text':'A personal note'}]}
                req=urllib.request.Request(url+'/api/learning/'+state['courseId'],data=json.dumps(state).encode(),headers={'X-Course-Token':TOKEN,'Content-Type':'application/json'})
                self.assertTrue(json.load(opener.open(req))['saved']);self.assertEqual(json.load(opener.open(url+'/api/learning/'+state['courseId']))['state'],state)
                with self.assertRaises(urllib.error.HTTPError):opener.open(urllib.request.Request(url+'/api/settings',data=b'{}'))
                self.assertEqual(Store(d).learning(state['courseId']),state)
            finally:server.shutdown();server.server_close();thread.join()
    def test_import_uses_trusted_reader_and_rejects_asset_traversal(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            p=page();src=b'%PDF fixture';c={'id':'course-0123456789abcdef','title':'Fixture','files':[{'id':'lecture-test','name':'lecture.pdf','sha256':hashlib.sha256(src).hexdigest(),'sourceUrl':'sources/lecture.pdf','order':1,'chapters':[],'pages':[p]}],'explanations':[]}
            def bundle(c):
                out=io.BytesIO()
                with zipfile.ZipFile(out,'w') as z:
                    z.writestr('course.json',json.dumps(c));z.writestr('sources/lecture.pdf',src);z.writestr(p['image'],b'image-fixture');z.writestr('app.js','alert("untrusted imported script")')
                out.seek(0);return out
            store=Store(d);item=import_course(bundle(c),store);self.assertEqual(len(store.courses()),1)
            code=(store.course_path(c['id'])/'app.js').read_text('utf-8');self.assertNotIn('untrusted imported script',code)
            p['image']='../outside.png'
            with self.assertRaises(ValueError):import_course(bundle(c),store)
if __name__=='__main__':unittest.main()
