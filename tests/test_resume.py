import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from course_compiler.pipeline import compile_course,write_json,merge_visual
from course_compiler.extract import unit,normalize


class ResumeTests(unittest.TestCase):
    def test_math_compatibility_characters_survive(self):
        self.assertEqual(normalize('x² + ½ + β'),'x² + ½ + β')

    def test_source_correction_invalidates_translation(self):
        u=unit('p1',1,'Risk premlum','paragraph',{'file':'f','page':1})
        u.update(translatedText='旧译文',translationStatus='complete')
        p={'id':'p1','units':[u],'warnings':[]}
        merge_visual(p,{'corrections':[{'id':u['id'],'sourceText':'Risk premium'}],'additions':[]},'audit')
        self.assertEqual(u['rawText'],'Risk premlum');self.assertIsNone(u['translatedText'])

    def test_cancelled_resume_keeps_all_cached_explanations(self):
        with tempfile.TemporaryDirectory(dir=Path('tmp').resolve()) as d:
            prior=Path.cwd()
            try:
                os.chdir(d);source=Path('lecture.pdf');source.write_bytes(b'fixture-content')
                digest=hashlib.sha256(('pipeline-v1'+hashlib.sha256(source.read_bytes()).hexdigest()).encode()).hexdigest()[:16]
                cache=Path('.course-cache')/digest
                pages=[]
                for n in (1,2):
                    src={'file':'lecture.pdf','fileId':'lecture','page':n}
                    u=unit('page'+str(n),1,'A full definition','paragraph',src)
                    p={'id':'page'+str(n),'number':n,'source':src,'units':[u],'rawUnits':[copy.deepcopy(u)],'title':'Definition','visualStatus':'complete','transcriptionStatus':'complete','warnings':[]}
                    pages.append(p)
                    e={'id':'explanation'+str(n),'relatedContentIds':[u['id']],'source':src}
                    write_json(cache/(p['id']+'.json'),{'page':p,'explanations':[e]})
                files=[{'id':'lecture','name':'lecture.pdf','pages':pages}]
                class NoNetworkModel:
                    available=True;model='fixture'
                    def request(self,*a,**kw):raise AssertionError('Cancelled job must not call a model')
                cancel=threading.Event();cancel.set()
                with patch('course_compiler.pipeline.extract_files',return_value=files):
                    c=compile_course([source],Path('site'),model=NoNetworkModel(),cancel=cancel,workers=1)
                self.assertEqual(c['status'],'cancelled');self.assertEqual(len(c['explanations']),2)
                self.assertEqual(c['quality']['errors'],[])
            finally:os.chdir(prior)

if __name__=='__main__':unittest.main()
