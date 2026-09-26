import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from course_compiler.config import local_settings
from course_compiler.model import Model, ModelError


class ModelTests(unittest.TestCase):
    def test_local_settings_are_literal_not_executable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env.local'
            p.write_text('export COURSE_PROVIDER=siliconflow\nSILICONFLOW_API_KEY="fixture-$(literal)"\nCOURSE_MODEL=Qwen/example # note\n','utf-8')
            cfg=local_settings(p)
            self.assertEqual(cfg['SILICONFLOW_API_KEY'],'fixture-$(literal)')
            self.assertEqual(cfg['COURSE_MODEL'],'Qwen/example')

    def test_streamed_json_and_png_media_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'page.png';p.write_bytes(b'fixture')
            events=[{'choices':[{'delta':{'content':'{"ok":'},'finish_reason':None}]},
                    {'choices':[{'delta':{'content':'true}'},'finish_reason':'stop'}]},
                    {'choices':[],'usage':{'completion_tokens':5}}]
            stream=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n'
            model=Model(provider='siliconflow',base_url='https://fixture.invalid/v1',api_key='fixture-key',model='Qwen/test',cache=d)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(stream.encode())) as request:
                self.assertEqual(model.request('system',{},image=p),{'ok':True})
                self.assertEqual(model.request('system',{},image=p),{'ok':True})
                self.assertEqual(request.call_count,1)
                body=json.loads(request.call_args.args[0].data)
                self.assertTrue(body['stream']);self.assertFalse(body['enable_thinking'])
                self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;'))
            self.assertFalse(any('fixture-key' in f.read_text('utf-8') for f in Path(d).glob('*.json')))

    def test_truncated_stream_cannot_become_completed_cache(self):
        with tempfile.TemporaryDirectory() as d:
            model=Model(provider='siliconflow',base_url='https://fixture.invalid/v1',api_key='fixture',model='Qwen/test',cache=d)
            stream=b'data: {"choices":[{"delta":{"content":"{\\\"ok\\\":"}}]}\n\n'
            with patch('urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(stream)),patch('time.sleep'):
                with self.assertRaises(ModelError):model.request('system',{})
            self.assertFalse(any(len(f.stem)==64 for f in Path(d).glob('*.json')))

    def test_runaway_reason_stops_but_long_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            model=Model(provider='siliconflow',base_url='https://fixture.invalid/v1',api_key='fixture',model='Qwen/test',cache=d)
            def stream(value):
                event={'choices':[{'delta':{'content':json.dumps(value)},'finish_reason':'stop'}]}
                return io.BytesIO(('data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n').encode())
            with patch('urllib.request.urlopen',side_effect=lambda *a,**k:stream({'corrections':[{'reason':'The image shows the same label. '*110}]})):
                with self.assertRaisesRegex(ModelError,'异常冗长'):model.request('audit',{})
            value={'sourceText':'Full lecture material. '*200}
            with patch('urllib.request.urlopen',side_effect=lambda *a,**k:stream(value)):
                self.assertEqual(model.request('transcribe',{}),value)

if __name__=='__main__':unittest.main()
