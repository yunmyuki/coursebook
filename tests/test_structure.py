import copy,tempfile,unittest
from pathlib import Path
from course_compiler.structure import restore_heading_groups
from course_compiler.parsers import DocumentParser
from course_compiler.extract import extract_pdf
from test_v2 import page,PROFILE


def heading_page():
    p=page('How do Real World CFOs Make');a=p['units'][0]
    a.update(type='title',position=[.16,.09,.81,.12],typography={'fontName':'HeadingBold','fontSize':24.8,'dominance':1},translatedText='现实中的 CFO 如何作出',translationStatus='complete')
    b=copy.deepcopy(a);b.update(id=a['id']+'-second',type='paragraph',sourceText='Corporate Financial Decisions?',rawText='Corporate Financial Decisions?',translatedText='公司财务决策？',position=[.17,.128,.80,.158])
    p['units']=[a,b];return p


class HeadingStructureTests(unittest.TestCase):
    def test_wrapped_title_preserves_text_ids_translations_and_is_idempotent(self):
        p=heading_page();before=[(u['id'],u['sourceText'],u['rawText'],u['translatedText'],u['position']) for u in p['units']]
        groups=restore_heading_groups(p);self.assertEqual(len(groups),1)
        self.assertEqual(p['title'],'How do Real World CFOs Make Corporate Financial Decisions?')
        self.assertTrue(all(u['type']=='title' for u in p['units']))
        self.assertEqual(before,[(u['id'],u['sourceText'],u['rawText'],u['translatedText'],u['position']) for u in p['units']])
        once=copy.deepcopy(p);restore_heading_groups(p);self.assertEqual(once,p)

    def test_body_subtitle_and_separate_column_are_not_merged(self):
        for change in [{'typography':{'fontName':'Body','fontSize':24.8,'dominance':1}},{'position':[.17,.22,.80,.25]},{'position':[.65,.128,.97,.158]},{'type':'bullet'}]:
            p=heading_page();p['units'][1].update(change);self.assertEqual(restore_heading_groups(p),[])

    def test_three_line_centered_title_in_middle_of_page_keeps_last_line(self):
        p=heading_page();p['units'][0]['position']=[.1,.304,.9,.35];p['units'][1]['position']=[.1,.357,.9,.403]
        last=copy.deepcopy(p['units'][1]);last.update(id='third',sourceText='or pessimism',position=[.41,.410,.59,.456]);p['units'].append(last)
        self.assertEqual(len(restore_heading_groups(p)[0]['contentIds']),3)

    def test_same_pptx_title_container_does_not_require_font_guess(self):
        p=heading_page()
        for u in p['units']:u.pop('typography');u.update(headingContainerId='same-shape',position=[.1,.1,.9,.3],type='title')
        self.assertEqual(len(restore_heading_groups(p)),1)
        p['units'][1]['headingContainerId']='different-shape';self.assertEqual(restore_heading_groups(p),[])

    def test_pdf_font_extraction_restores_heading_and_keeps_body(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'wrapped.pdf';c=canvas.Canvas(str(source),pagesize=(600,700))
            c.setFont('Helvetica-Bold',24);c.drawCentredString(300,640,'How do Real World CFOs Make');c.drawCentredString(300,611,'Corporate Financial Decisions?')
            c.setFont('Helvetica',16);c.drawString(80,550,'A complete body paragraph.');c.save()
            result=extract_pdf(source,root/'site','lecture')[0]
            self.assertEqual(len(result['headingGroups']),1);self.assertEqual(result['units'][2]['type'],'paragraph')
            self.assertEqual(result['units'][1]['type'],'title');self.assertEqual(len(result['textLines']),3)

    def test_siliconflow_paddle_chat_is_rejected_before_a_paid_page_request(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            with self.assertRaisesRegex(ValueError,'完整页面版面接口'):DocumentParser({**PROFILE,'baseUrl':'https://api.siliconflow.cn/v1','model':'PaddlePaddle/PaddleOCR-VL-1.5'},d)
            DocumentParser({**PROFILE,'engine':'paddle-layout','baseUrl':'http://127.0.0.1:8080','model':'PaddleOCR-VL'},d)

if __name__=='__main__':unittest.main()
