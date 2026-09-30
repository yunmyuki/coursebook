import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image,ImageDraw
from course_compiler.hybrid_parser import parse,native_blocks,table_result,prompt_for,trusted_native,uncovered_visual
from course_compiler.local_layout import decode
from course_compiler.storage import validate_profile
from course_compiler.model import ModelError

def region(label='text',box=None,order=0):
    return {'label':label,'bbox':box or [.1,.1,.9,.3],'score':.95,'readingOrder':order}

class HybridTests(unittest.TestCase):
    def test_bundled_model_fallback_and_user_override(self):
        from course_compiler.local_layout import model_path
        bundle=self.root/'bundle';model=bundle/'models/PP-DocLayoutV3/inference.onnx'
        model.parent.mkdir(parents=True);model.write_bytes(b'fixture')
        user=self.root/'user'
        with patch('course_compiler.local_layout.resource_root',return_value=bundle):
            self.assertEqual(model_path(user),model)
            override=user/'models/PP-DocLayoutV3/inference.onnx';override.parent.mkdir(parents=True);override.write_bytes(b'override')
            self.assertEqual(model_path(user),override)

    def test_fresh_settings_default_to_hybrid_with_separate_text_models(self):
        from course_compiler.storage import Store
        with patch('course_compiler.storage.local_settings',return_value={}):
            store=Store(self.root);settings=store.settings();profiles=store.profiles()
        self.assertEqual(settings['settingsMode'],'advanced')
        self.assertEqual(profiles['parse']['engine'],'local-layout-ocr')
        self.assertEqual(profiles['parse']['model'],'PaddlePaddle/PaddleOCR-VL-1.5')
        self.assertEqual(profiles['parse']['ocrFlavor'],'paddle')
        for role in ('translation','explanation'):
            self.assertEqual(profiles[role]['engine'],'vision')
            self.assertFalse(profiles[role]['inherit'])
            self.assertNotIn('OCR',profiles[role]['model'])
        for profile in profiles.values():validate_profile(profile)

    def test_new_default_preserves_explicit_saved_configuration(self):
        from course_compiler.storage import Store,atomic_json
        profile={'engine':'vision','provider':'openai','baseUrl':'https://example.invalid/v1','model':'my-model'}
        store=Store(self.root)
        atomic_json(self.root/'settings.json',{'settingsMode':'simple','profiles':{'parse':profile,'translation':{'inherit':True},'explanation':{'inherit':True}}})
        settings=store.settings()
        self.assertEqual(settings['profiles']['parse']['model'],'my-model')
        self.assertEqual(settings['profiles']['parse']['engine'],'vision')
        self.assertEqual(settings['settingsMode'],'simple')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.image=self.root/'page.png';Image.new('RGB',(1000,600),'white').save(self.image)
        self.model=Mock();self.model.request.return_value='Visible text'
        self.profile={'engine':'local-layout-ocr','provider':'siliconflow','baseUrl':'https://api.siliconflow.cn/v1','model':'PaddlePaddle/PaddleOCR-VL-1.5'}
    def tearDown(self):self.temp.cleanup()
    def run_parse(self,page,regions):
        result={'regions':regions,'seconds':.3,'model':'fixture','sha256':'fixture'}
        with patch('course_compiler.local_layout.detect',return_value=result):return parse(page,self.image,self.model,self.profile,self.root)
    def test_model_reading_order_not_confidence_or_y(self):
        import numpy as np
        rows=np.array([[22,.99,50,20,200,80,12],[22,.8,300,20,450,80,4],[22,.7,302,22,449,78,6]])
        result=decode(rows,500,500)
        self.assertEqual([r['modelOrder'] for r in result],[4,12]);self.assertEqual(len(result),2)
    def test_wrapped_native_paragraph_costs_zero(self):
        lines=[{'text':'a domestic deal','position':[.1,.1,.8,.16]},{'text':'pipeline rather than pure cash.','position':[.1,.18,.8,.24]}]
        result=self.run_parse({'textLines':lines},[region()])
        self.assertEqual(result['blocks'][0]['text'],'a domestic deal pipeline rather than pure cash.')
        self.assertIn('\n',result['blocks'][0]['rawText']);self.model.request.assert_not_called()
    def test_columns_preserve_complete_questions(self):
        lines=[];regions=[]
        for i,x in enumerate((.05,.37,.69)):
            regions.append(region(box=[x,.1,x+.25,.3],order=i))
            lines.extend([{'text':f'Question {i}','position':[x,.1,x+.2,.15]},{'text':'continued?','position':[x,.2,x+.2,.25]}])
        result=self.run_parse({'textLines':lines},regions)
        self.assertEqual([b['text'] for b in result['blocks']],[f'Question {i} continued?' for i in range(3)])
    def test_chart_kept_and_ocr_even_with_text_layer(self):
        result=self.run_parse({'textLines':[{'text':'2024','position':[.2,.2,.3,.25]}]},[region('chart')])
        self.assertEqual(len(result['figures']),1);self.assertEqual(result['blocks'][0]['contentOrigin'],'figure-transcription')
        self.assertEqual(self.model.request.call_args.args[1],'OCR:')
    def test_missing_native_lines_not_dropped(self):
        result=self.run_parse({'textLines':[{'text':'Source note','position':[.1,.8,.8,.85]}]},[region()])
        self.assertIn('Source note',[b['text'] for b in result['blocks']]);self.assertEqual(result['hybridMetrics']['unassignedTextLines'],1)
    def test_pdf_overflow_text_keeps_original_coordinates_for_review(self):
        result=self.run_parse({'textLines':[{'text':'Overflowing heading','position':[.1,.8,1.01,.85]}]},[region()])
        block=next(b for b in result['blocks'] if b['text']=='Overflowing heading')
        self.assertEqual(block['bbox'][2],1);self.assertEqual(block['rawPosition'][2],1.01);self.assertTrue(block['uncertain'])
    def test_scan_uses_region_ocr(self):
        result=self.run_parse({'textLines':[]},[region()])
        self.assertEqual(result['hybridMetrics']['ocrRegions'],1);self.assertEqual(result['blocks'][0]['text'],'Visible text')
    def test_table_uses_whole_crop_and_preserves_span(self):
        self.model.request.return_value='<table><tr><td colspan="2">Header</td></tr><tr><td>1</td><td>2</td></tr></table>'
        result=self.run_parse({},[region('table')])
        from course_compiler.parsers import table_cells
        self.assertEqual(table_cells(result['tables'][0])[0]['colSpan'],2)
        self.assertEqual(self.model.request.call_count,1);self.assertEqual(self.model.request.call_args.args[1],'Table Recognition:')
    def test_preflight_region_cap_does_not_spend(self):
        self.profile['maxOcrRegions']=1
        with self.assertRaisesRegex(ModelError,'尚未发送'):self.run_parse({},[region(),region(order=1)])
        self.model.request.assert_not_called()
    def test_native_text_with_missing_raster_line_is_not_trusted(self):
        im=Image.new('RGB',(1000,600),'white');ImageDraw.Draw(im).rectangle((100,120,800,150),fill='black')
        lines=[{'text':'Present line','position':[.1,.1,.8,.15]}]
        self.assertFalse(trusted_native(region(),lines,im,{}))
    def test_unclassified_visual_coverage_alarm(self):
        im=Image.new('RGB',(1000,600),'white');ImageDraw.Draw(im).ellipse((100,200,700,450),fill='black')
        pixels,fraction=uncovered_visual(im,[[.1,.1,.9,.2]])
        self.assertGreater(pixels,500);self.assertGreater(fraction,.15)
    def test_protocols_and_markdown_table_validation(self):
        self.assertEqual(prompt_for('glm','text'),'Text Recognition:')
        self.assertEqual(prompt_for('paddle','display_formula'),'Formula Recognition:')
        self.assertIn('<|grounding|>',prompt_for('deepseek','table'))
        self.assertEqual(table_result('| A | B |\n| --- | --- |\n| 1 | 2 |',[0,0,1,1])['rows'][1],['1','2'])
        with self.assertRaises(ModelError):table_result('not a table',[0,0,1,1])
    def test_siliconflow_ocr_allowed_only_for_region_engine(self):
        validate_profile(self.profile)
        with self.assertRaises(ValueError):validate_profile({**self.profile,'engine':'vision'})
        with self.assertRaises(ValueError):validate_profile({**self.profile,'maxOcrRegions':0})
    def test_bullets_stay_separate(self):
        blocks=native_blocks(region(),[{'text':'• A','position':[.1,.1,.2,.15]},{'text':'• B','position':[.1,.2,.2,.25]}])
        self.assertEqual([b['type'] for b in blocks],['bullet','bullet'])
    def test_corrupt_model_rejected(self):
        from course_compiler.local_layout import verify
        with self.assertRaises(ModelError):verify(self.image)
    def test_otsl_preserves_rectangular_merged_cells(self):
        from course_compiler.otsl import to_html
        from course_compiler.parsers import table_cells
        cells=table_cells({'html':to_html('<fcel>A<lcel><fcel>B<nl><ucel><xcel><fcel>C<nl>')})
        self.assertEqual((cells[0]['rowSpan'],cells[0]['colSpan']),(2,2))
        self.assertEqual([c['text'] for c in cells],['A','B','C'])
        with self.assertRaises(ModelError):to_html('<ucel><nl>')
    def test_otsl_endpoint_missing_first_marker_preserves_header(self):
        from course_compiler.parsers import table_cells
        cells=table_cells(table_result("LEVEL<fcel>PAY<nl><fcel>Analyst<fcel>250–350<nl>",[0,0,1,1]))
        self.assertEqual([c['text'] for c in cells],['LEVEL','PAY','Analyst','250–350'])
    def test_fullpage_evidence_does_not_relabel_prose_as_chart_text(self):
        from course_compiler.figures import mark_figure_text
        p={'units':[{'id':'u','sourceText':'body','type':'paragraph','position':[.1,.1,.9,.2]}],
           'figures':[{'id':'f','position':[0,0,1,1],'contextOnly':True}]}
        mark_figure_text(p)
        self.assertNotIn('contentOrigin',p['units'][0])
    def test_markdown_keeps_table_spans_and_escapes_source_html(self):
        from course_compiler.markdown_export import transcript
        course={'title':'Test','files':[{'pages':[{'id':'page1','number':1,'source':{'file':'lecture.pdf'},'units':[
            {'id':'cell1','sourceText':'<script>bad</script>','tableId':'t','type':'table-cell','row':0,'col':0,'colSpan':2,'readingOrder':0},
            {'id':'hidden','sourceText':'old text','type':'paragraph','reviewOnly':True}],
            'figures':[{'id':'fig','image':'assets/chart.png','readingOrder':1}]}]}]}
        text=transcript(course)
        self.assertIn('colspan="2"',text);self.assertIn('id="cell1"',text);self.assertNotIn('<script>',text)
        self.assertIn('assets/chart.png',text);self.assertNotIn('old text',text)
    def test_hybrid_forces_layout_on_native_readable_page(self):
        from test_v2 import page,PROFILE
        from course_compiler.pipeline_v2 import compile_course
        source=self.root/'lecture.pdf';source.write_bytes(b'fixture');p=page('Simple native text with enough words to bypass conventional OCR routing.');p['units'][0].update(translatedText='译文',translationStatus='complete')
        called=[]
        class Parser:
            def __init__(self,*args):pass
            def parse(self,page,output):
                called.append(page['id']);u=page['units'][0]
                return {'blocks':[{'text':u['sourceText'],'bbox':u['position'],'type':u['type']}],'hybridMetrics':{'nativeRegions':1,'ocrRegions':0}}
        with patch('course_compiler.pipeline_v2.extract_files',return_value=[{'id':'lecture-test','name':'lecture.pdf','pages':[p]}]),patch('course_compiler.pipeline_v2.DocumentParser',Parser),patch('course_compiler.local_layout.session'):
            course=compile_course([source],self.root/'site',{'parse':{**PROFILE,'engine':'local-layout-ocr'},'translation':PROFILE},self.root/'cache',workers=1,translation_context={'subject':'Test','style':'Faithful'})
        self.assertEqual(len(called),1);self.assertEqual(course['metrics']['hybridPages'],1)
    def test_changed_table_cell_retains_history_without_overlapping_slot(self):
        from test_v2 import page
        from course_compiler.parsers import commit_layout
        p=page('');p['units']=[]
        commit_layout(p,{'tables':[{'bbox':[.1,.1,.9,.5],'rows':[['Profit','-6%']]}]},self.root)
        old=p['units'][1]['id']
        commit_layout(p,{'tables':[{'bbox':[.1,.1,.9,.5],'rows':[['Profit','-8%']]}]},self.root)
        active=[u for u in p['units'] if not u.get('reviewOnly')]
        self.assertEqual(len(active),2);self.assertTrue(active[1]['uncertain'])
        self.assertEqual(active[1]['corrections'][0]['before'],'-6%')
        self.assertTrue(next(u for u in p['units'] if u['id']==old)['reviewOnly'])

    def test_table_inline_symbol_escaping_preserves_values_and_expressions(self):
        from course_compiler.parsers import table_cells
        raw=r'<fcel>250–350 (\\(\\approx\\) $35–50K)<fcel>-6%<nl><fcel>\(\approx\)<fcel>\(x+1\)<nl>'
        cells=table_cells(table_result(raw,[0,0,1,1]))
        self.assertEqual([c['text'] for c in cells],['250–350 (≈ $35–50K)','-6%','≈',r'\(x+1\)'])

if __name__=='__main__':unittest.main()
