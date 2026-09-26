import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from course_compiler import server


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path('tmp').resolve())
        self.root=Path(self.tmp.name)
        self.patch=patch.object(server,'ROOT',self.root);self.patch.start()
        server.FILES.clear();server.JOBS.clear()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.patch.stop();self.tmp.cleanup()

    def request(self,method,path,data=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=20)
        body=json.dumps(data).encode() if data is not None and not isinstance(data,bytes) else data
        conn.request(method,path,body=body,headers=headers or {})
        response=conn.getresponse();status=response.status;payload=response.read();conn.close()
        return status,json.loads(payload) if payload.startswith(b'{') else payload

    def test_host_origin_and_mutation_token(self):
        self.assertEqual(self.request('GET','/api/status',headers={'Host':'attacker.invalid'})[0],403)
        self.assertEqual(self.request('GET','/api/status',headers={'Origin':'https://attacker.invalid'})[0],403)
        self.assertEqual(self.request('POST','/api/compile',{})[0],403)
        status,result=self.request('GET','/api/status');self.assertEqual(status,200)
        self.assertNotIn('apiKey',result)
        self.assertEqual(self.request('POST','/api/compile',{}, {'X-Course-Token':result['token']})[0],400)

    def test_static_path_confinement(self):
        (self.root/'secret.txt').write_text('private')
        (self.root/'output').mkdir()
        self.assertEqual(self.request('GET','/courses/%2e%2e/secret.txt')[0],404)

    def test_upload_persistence_compile_without_model_and_zip(self):
        import io
        writer=PdfWriter();writer.add_blank_page(width=200,height=200);stream=io.BytesIO();writer.write(stream)
        headers={'X-Course-Token':server.TOKEN,'X-Filename':'lecture-test.pdf'}
        status,file=self.request('POST','/api/upload',stream.getvalue(),headers);self.assertEqual(status,200)
        server.FILES.clear();server.index_files();self.assertTrue(server.FILES)
        fid=next(iter(server.FILES))
        status,job=self.request('POST','/api/compile',{'files':[fid],'extractOnly':True},headers);self.assertEqual(status,202)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            status,result=self.request('GET','/api/jobs/'+job['id'])
            if result['status']!='running':break
            time.sleep(.05)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['quality']['pages'],1)
        self.assertEqual(self.request('GET',result['readerUrl'])[0],200)
        status,payload=self.request('GET',result['downloadUrl']);self.assertEqual(status,200);self.assertTrue(payload.startswith(b'PK'))

    def test_rejects_disguised_upload(self):
        status,_=self.request('POST','/api/upload',b'not a pdf',{'X-Course-Token':server.TOKEN,'X-Filename':'bad.pdf'})
        self.assertEqual(status,400)

if __name__=='__main__':unittest.main()
