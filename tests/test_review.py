import copy,json,tempfile,unittest
from pathlib import Path
from course_compiler.storage import Store,atomic_json
from course_compiler.review import review_course,apply_overrides
from test_v2 import page

class ReviewTests(unittest.TestCase):
    def test_user_correction_keeps_source_and_anchor_and_invalidates_formula(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);p=page('x = -5');u=p['units'][0];u.update(type='formula',latex='x=-5');c={'id':'course-0123456789abcdef','title':'Review','files':[{'pages':[p]}],'explanations':[{'id':'exp','relatedContentIds':[u['id']]}]};site=store.course_path(c['id']);atomic_json(site/'course.json',c)
            review_course(store,c['id'],{'contentId':u['id'],'sourceText':'x = 5','translatedText':'x = 5','latex':'x=5'})
            result=json.loads((site/'course.json').read_text());new=result['files'][0]['pages'][0]['units'][0]
            self.assertEqual(new['id'],u['id']);self.assertEqual(new['rawText'],'x = -5');self.assertEqual(new['latex'],'x=5');self.assertTrue(result['explanations'][0]['needsReview'])
            apply_overrides(c,Path(d));self.assertEqual(c['files'][0]['pages'][0]['units'][0]['sourceText'],'x = 5')
    def test_page_review_never_clears_uncertain_units(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);p=page();p.update(reviewRequired=True,reviewReasons=['scan']);p['units'][0]['uncertain']=True;c={'id':'course-0123456789abcdef','title':'Review','files':[{'pages':[p]}],'explanations':[]};site=store.course_path(c['id']);atomic_json(site/'course.json',c)
            review_course(store,c['id'],{'pageId':p['id']});result=json.loads((site/'course.json').read_text());self.assertFalse(result['files'][0]['pages'][0]['reviewRequired']);self.assertEqual(result['quality']['readingUncertain'],1);self.assertFalse(result['quality']['complete'])
if __name__=='__main__':unittest.main()
