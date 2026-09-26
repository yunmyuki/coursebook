import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from course_compiler.extract import natural_key,unit
from course_compiler.pipeline import apply_translations,apply_terminology,merge_visual,quality,build_sections,request_units
from course_compiler.model import ModelError
from course_compiler.export import export_site


class FidelityTests(unittest.TestCase):
    def setUp(self):
        source={'file':'lecture1.pdf','fileId':'lecture1','page':1}
        self.u=unit('lecture1-page1',1,'A definition repeated in a later lecture.','paragraph',source,[.1,.2,.8,.3])
        self.p={'id':'lecture1-page1','source':source,'number':1,'title':'Introduction','units':[self.u],'rawUnits':[copy.deepcopy(self.u)],'rawText':self.u['rawText'],'warnings':[],'visualStatus':'pending','transcriptionStatus':'pending'}
    def test_translation_missing_extra_duplicate_ids_rejected_atomically(self):
        for rows in [[],[{'id':'unknown','translatedText':'定义'}],[{'id':self.u['id'],'translatedText':'定义'}]*2]:
            with self.assertRaises(ModelError):apply_translations([self.u],{'translations':rows})
            self.assertIsNone(self.u['translatedText'])
    def test_translation_keeps_source_and_exact_anchor(self):
        before=copy.deepcopy(self.u)
        apply_translations([self.u],{'translations':[{'id':self.u['id'],'translatedText':'后续讲义中重复出现的一个定义。'}]})
        for key in ['id','source','sourceText','rawText']:self.assertEqual(before[key],self.u[key])
    def test_terminology_changes_only_exact_labels_and_keeps_translation_history(self):
        self.u.update(sourceText='Momentum',translatedText='趋势惯性',translationStatus='complete')
        paragraph=unit(self.p['id'],2,'Momentum predicts returns.','paragraph',self.p['source'])
        paragraph.update(translatedText='动量可以预测收益。',translationStatus='complete')
        self.p['units'].append(paragraph)
        self.assertEqual(apply_terminology(self.p,{'momentum':'动量'}),1)
        self.assertEqual(self.u['translatedText'],'动量');self.assertEqual(self.u['sourceText'],'Momentum')
        self.assertEqual(self.u['translationCorrections'][0]['before'],'趋势惯性')
        self.assertEqual(paragraph['translatedText'],'动量可以预测收益。')
    def test_short_request_ids_restore_exact_persisted_anchors(self):
        class WireModel:
            def request(self,prompt,data,**kwargs):
                assert data['units'][0]['id']=='u1'
                assert data['protectedContentIds']==['u1']
                return {'translations':[{'id':'u1','translatedText':'完整译文'}],'verifiedContentIds':['u1'],'explanations':[{'relatedContentIds':['u1']}]}
        result=request_units(WireModel(),'prompt',[self.u],{'protectedContentIds':[self.u['id']]})
        self.assertEqual(result['translations'][0]['id'],self.u['id'])
        self.assertEqual(result['verifiedContentIds'],[self.u['id']])
        self.assertEqual(result['explanations'][0]['relatedContentIds'],[self.u['id']])
    def test_visual_cannot_silently_replace_original_with_summary(self):
        merge_visual(self.p,{'corrections':[{'id':self.u['id'],'sourceText':'Summary.'}],'additions':[]},'audit')
        self.assertEqual(self.u['sourceText'],self.u['rawText']);self.assertTrue(self.u['uncertain'])
    def test_repeated_table_values_remain_separate_cells(self):
        merge_visual(self.p,{'corrections':[],'additions':[{'type':'table-cell','sourceText':'0.01','tableId':'table1','row':0,'col':i,'position':[.1,.4,.2,.5]} for i in range(2)]},'audit')
        self.assertEqual(len(self.p['units']),3);self.assertEqual(len({u['id'] for u in self.p['units']}),3)
    def test_table_position_correction_retains_source_and_resolves_overlap(self):
        self.u.update(type='table-cell',tableId='table1',row=0,col=0)
        other=unit(self.p['id'],2,'Second original cell','table-cell',self.p['source'],tableId='table1',row=0,col=0)
        self.p['units'].append(other)
        course={'files':[{'pages':[self.p]}],'explanations':[]}
        self.assertTrue(any('Overlapping' in e for e in quality(course)['errors']))
        merge_visual(self.p,{'corrections':[{'id':other['id'],'row':1,'reason':'Second source row'}]},'audit')
        self.assertEqual(other['rawText'],'Second original cell');self.assertEqual(other['sourceText'],other['rawText'])
        self.assertFalse(quality(course)['errors'])
    def test_manual_transcription_cannot_be_overwritten_by_later_model(self):
        self.u['origin']='conversation-visual-review'
        merge_visual(self.p,{'corrections':[{'id':self.u['id'],'sourceText':'A model reinterpretation.'}],'additions':[],'verifiedContentIds':[self.u['id']]},'audit')
        self.assertEqual(self.u['sourceText'],self.u['rawText'])
        self.assertEqual(len(self.u['suggestedCorrections']),1)
    def test_audit_reuses_table_anchors_and_does_not_duplicate_same_cell(self):
        cell={'type':'table-cell','sourceText':'0.01','tableId':'table1','row':0,'col':0,'position':[.1,.4,.2,.5]}
        merge_visual(self.p,{'corrections':[],'additions':[cell]},'visual')
        cell['tableId']=self.p['id']+'-table1'
        merge_visual(self.p,{'corrections':[],'additions':[cell]},'audit')
        self.assertEqual(len(self.p['units']),2)
    def test_compact_table_preserves_cells_blanks_and_estimated_positions(self):
        result={'corrections':[],'additions':[],'tables':[{'tableId':'t','position':[.1,.4,.9,.8],'rows':[['Variable','(1)','(2)'],['X','0.02\n(2.4)',''],['Y','0.02\n(2.4)','−0.1']]}]}
        merge_visual(self.p,result,'visual')
        cells=[u for u in self.p['units'] if u['type']=='table-cell']
        self.assertEqual(len(cells),8)
        self.assertEqual(sum(u['sourceText']=='0.02\n(2.4)' for u in cells),2)
        self.assertTrue(all(u['positionEstimated'] for u in cells))
    def test_compact_response_may_omit_empty_optional_lists(self):
        self.u['uncertain']=True
        merge_visual(self.p,{'verifiedAll':True,'uncertainContentIds':[self.u['id']]},'audit')
        self.assertTrue(self.u['uncertain'])
        merge_visual(self.p,{'verifiedAll':True},'audit')
        self.assertFalse(self.u['uncertain'])
        with self.assertRaises(ModelError):merge_visual(self.p,{'irrelevant':True},'audit')
    def test_archived_ocr_does_not_block_a_validated_replacement(self):
        self.u.update(translationStatus='complete',translatedText='译文')
        old=unit(self.p['id'],2,'Old uncertain OCR','paragraph',self.p['source'],uncertain=True,reviewOnly=True,supersededBy=self.u['id'])
        self.p['units'].append(old);self.p.update(visualStatus='complete',transcriptionStatus='complete')
        self.assertTrue(quality({'files':[{'pages':[self.p]}],'explanations':[]})['complete'])
    def test_artifact_rejection_cannot_hide_extracted_source(self):
        merge_visual(self.p,{'verifiedAll':True,'rejectedContentIds':[self.u['id']]},'audit')
        self.assertFalse(self.u.get('reviewOnly',False))
        self.u['origin']='visual-transcription'
        merge_visual(self.p,{'verifiedAll':True,'rejectedContentIds':[self.u['id']]},'audit')
        self.assertTrue(self.u['reviewOnly']);self.assertTrue(self.u['rejectedArtifact'])
        self.assertEqual(self.u['rawText'],'A definition repeated in a later lecture.')
    def test_natural_lecture_order(self):
        self.assertEqual(sorted(['Lecture10.pdf','Lecture2.pdf','Lecture1.pdf'],key=natural_key),['Lecture1.pdf','Lecture2.pdf','Lecture10.pdf'])
    def test_quality_rejects_missing_raw_and_dangling_explanation(self):
        c={'files':[{'pages':[self.p]}],'explanations':[{'id':'e','relatedContentIds':['missing']}]}
        self.assertTrue(quality(c)['errors']);self.assertFalse(quality(c)['complete'])
    def test_offline_export_escapes_script_and_excludes_intermediate(self):
        with tempfile.TemporaryDirectory(dir=Path('tmp').resolve()) as d:
            output=Path(d)/'site';output.mkdir();(output/'.intermediate').mkdir();(output/'.intermediate'/'private').write_text('x')
            (output/'.env.local').write_text('fixture-secret');(output/'compiler.html').write_text('requires a local server')
            export_site({'title':'</script><script>alert(1)</script>'},output,Path(d)/'site.zip')
            self.assertNotIn('</script>',(output/'course-data.js').read_text('utf-8'))
            with zipfile.ZipFile(Path(d)/'site.zip') as z:
                self.assertFalse(any('.intermediate' in n for n in z.namelist()))
                self.assertNotIn('.env.local',z.namelist());self.assertNotIn('compiler.html',z.namelist())


if __name__=='__main__':unittest.main()
