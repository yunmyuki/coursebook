import copy,json,tempfile,unittest
from pathlib import Path
from course_compiler.storage import Store,atomic_json
from course_compiler.cleanup import proposals,preview,clean_course,apply_cleanup
from course_compiler.review import review_course,apply_overrides
from course_compiler.extract import unit
from test_v2 import page

def fixture():
    pages=[]
    for n in range(1,6):
        p=page('A repeated definition must remain.',n)
        p['units'][0].update(translatedText='重复的定义必须保留。',translationStatus='complete')
        footer=unit(p['id'],2,f'INVESTMENT BANKING AND VALUATION · FUDAN SCHOOL OF MANAGEMENT {n}页','footnote',p['source'],[.1,.94,.9,.98])
        p['units'].append(footer);p['rawUnits']=copy.deepcopy(p['units']);pages.append(p)
    return {'id':'course-0123456789abcdef','title':'Fixture','files':[{'id':'lecture-test','pages':pages}],'explanations':[]}

class CleanupEditingTests(unittest.TestCase):
    def test_page_counters_and_margin_content(self):
        c=fixture()
        for p in c['files'][0]['pages']:
            p['units'][1]['sourceText']=f"{p['number']} / 5"
            for i,text in enumerate(('Definition of university funding','Sources: School of Management','Copyright 2026\nA meaningful second line')):
                p['units'].append(unit(p['id'],10+i,text,'footnote',p['source'],[.1,.94,.9,.98]))
        self.assertEqual(len(proposals(c)),1)
        c['files']=[dict(c['files'][0],pages=c['files'][0]['pages'][:2]),dict(c['files'][0],pages=c['files'][0]['pages'][2:4])]
        self.assertEqual(proposals(c),[])

    def test_formula_edit_and_formula_only_conflict(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);c=fixture();u=c['files'][0]['pages'][0]['units'][0]
            u.update(type='formula',sourceText='x=1',translatedText='x=1')
            atomic_json(store.course_path(c['id'])/'course.json',c)
            data={'contentId':u['id'],'sourceText':'x=1','translatedText':'x=1','latex':'x = 1','expectedLatex':None,'confirmTranslation':True}
            result=review_course(store,c['id'],data)
            self.assertEqual(result['unit']['latex'],'x = 1')
            with self.assertRaisesRegex(ValueError,'其他窗口'):review_course(store,c['id'],data)

    def test_footer_detection_and_conservative_exclusions(self):
        c=fixture();self.assertEqual(len(proposals(c)),1)
        for p in c['files'][0]['pages']:
            for i,kind in enumerate(('table-cell','formula','bullet')):
                p['units'].append(unit(p['id'],3+i,'UNIVERSITY definition',''+kind,p['source'],[.1,.94,.9,.98]))
            p['units'].append(unit(p['id'],8,'School effects explain valuation.','paragraph',p['source'],[.1,.4,.9,.5]))
        self.assertEqual(len(proposals(c)),1)
        c['files'][0]['pages']=c['files'][0]['pages'][:2];self.assertEqual(proposals(c),[])
    def test_cleanup_roundtrip_conflict_export_and_recompile(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);c=fixture();site=store.course_path(c['id']);atomic_json(site/'course.json',c)
            pr=preview(store,c['id']);data={'revision':pr['revision'],'action':'hide','groupIds':[pr['groups'][0]['id']]}
            self.assertEqual(clean_course(store,c['id'],data)['hiddenCount'],5)
            saved=json.loads((site/'course.json').read_text(encoding='utf-8'));u=saved['files'][0]['pages'][0]['units'][1]
            self.assertTrue(u['cleanupHidden']);self.assertEqual(u['rawText'],c['files'][0]['pages'][0]['units'][1]['rawText'])
            self.assertEqual(saved['quality']['unresolvedCandidates'],0)
            self.assertNotIn('FUDAN',(site/'transcript.md').read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):clean_course(store,c['id'],data)
            apply_overrides(c,Path(d));self.assertTrue(c['files'][0]['pages'][0]['units'][1]['cleanupHidden'])
            c['files'][0]['pages'][0]['units'][1]['sourceText']='Changed content';apply_cleanup(c,Path(d))
            self.assertFalse(c['files'][0]['pages'][0]['units'][1].get('cleanupHidden'))
            clean_course(store,c['id'],{'revision':preview(store,c['id'])['revision'],'action':'restore-all'})
            self.assertIn('FUDAN',(site/'transcript.md').read_text(encoding='utf-8'))
    def test_edit_untranslated_and_keep_history_and_confirm_same_translation(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);c=fixture();site=store.course_path(c['id']);atomic_json(site/'course.json',c)
            u=c['files'][0]['pages'][0]['units'][0]
            result=review_course(store,c['id'],{'contentId':u['id'],'sourceText':'Corrected definition','translatedText':u['translatedText']})
            self.assertEqual(result['unit']['translationStatus'],'pending');self.assertIsNone(result['unit']['translatedText'])
            self.assertEqual(result['unit']['corrections'][-1]['previousTranslation'],u['translatedText'])
            self.assertEqual(result['unit']['rawText'],u['rawText'])
            with self.assertRaises(ValueError):review_course(store,c['id'],{'contentId':u['id'],'sourceText':'Conflict','translatedText':'冲突','expectedSourceText':u['sourceText'],'expectedTranslatedText':u['translatedText']})
            result=review_course(store,c['id'],{'contentId':u['id'],'sourceText':'Second correction','translatedText':''})
            self.assertEqual(result['unit']['translationStatus'],'pending')
            review_course(store,c['id'],{'contentId':u['id'],'sourceText':'Second correction','translatedText':'译文'})
            result=review_course(store,c['id'],{'contentId':u['id'],'sourceText':'Third correction','translatedText':'译文','confirmTranslation':True})
            self.assertEqual(result['unit']['translationStatus'],'complete')
            apply_overrides(c,Path(d));self.assertEqual(c['files'][0]['pages'][0]['units'][0]['sourceText'],'Third correction')

if __name__=='__main__':unittest.main()
