import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_compiler.extract import extract_pdf
from course_compiler.layout import paragraph_continuation,geometric_order
from course_compiler.parsers import commit_layout,routing,DocumentParser
from course_compiler.pipeline_v2 import compile_course,course_id,fingerprint
from course_compiler.storage import atomic_json
from test_v2 import page,PROFILE


def line(text,box,font='AAAAAA+Body'):
    return {'text':text,'position':box,'typography':{'fontName':font,'fontSize':11,'dominance':1}}


class LayoutTests(unittest.TestCase):
    def test_wrapped_paragraph_with_generous_leading_and_subset_fonts(self):
        a=line('and a domestic deal',[.066,.832,.929,.852])
        b=line('pipeline rather than pure cash.',[.066,.865,.803,.885],'BBBBBB+Body')
        self.assertTrue(paragraph_continuation(a,b))
        self.assertFalse(paragraph_continuation(a,b,[[.05,.86,.95,.86]]))
        for box in ([.56,.865,.95,.885],[.066,.90,.8,.92]):
            self.assertFalse(paragraph_continuation(a,{**b,'position':box}))

    def test_independent_short_sentences_and_font_changes_stay_separate(self):
        a=line('An independent point.',[.1,.3,.3,.32]);b=line('Another separate point with more text.',[.1,.332,.8,.352])
        self.assertFalse(paragraph_continuation(a,b))
        a['text']='A wrapped sentence';a['position'][2]=.85
        self.assertFalse(paragraph_continuation(a,{**b,'typography':{**b['typography'],'fontName':'Other'}}))

    def test_spanning_heading_columns_and_footer_read_in_order(self):
        regions=[line('title',[.05,.05,.95,.12]),line('left1',[.05,.2,.46,.3]),line('right1',[.56,.2,.95,.3]),line('left2',[.05,.4,.46,.5]),line('table',[.56,.35,.95,.6]),line('footer',[.05,.8,.95,.86])]
        self.assertEqual([r['text'] for r in geometric_order(regions)],['title','left1','left2','right1','table','footer'])

    def test_pdf_columns_table_rules_and_full_width_paragraph(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'layout.pdf';c=canvas.Canvas(str(source),pagesize=(1000,600))
            c.setFillColorRGB(.98,.98,.98);c.rect(0,0,1000,600,fill=1,stroke=0);c.setFillColorRGB(0,0,0)
            c.setFont('Helvetica-Bold',24);c.drawString(60,550,'A heading spanning the whole page')
            c.setFont('Helvetica',12)
            for y,left,right in [(460,'The first policy paragraph','LEVEL          TOTAL COMP'),(440,'continues on a second line.','Analyst         250-350'),(400,'A separate policy paragraph.','Associate       400-800')]:
                c.drawString(60,y,left);c.drawString(560,y,right)
            c.line(530,260,530,480)
            for y in (450,420,380):c.line(560,y,940,y)
            c.drawString(60,160,'Why the gap? The employer sells stability and a domestic deal')
            c.drawString(60,140,'pipeline rather than pure cash. All original wording stays intact.')
            c.save();p=extract_pdf(source,root/'site','fixture')[0]
            self.assertEqual(routing(p)[0],'vision');self.assertLess(p['vectorCount'],15)
            self.assertFalse(any('policy' in u['sourceText'] and 'Analyst' in u['sourceText'] for u in p['units']))
            bottom=[u for u in p['units'] if u['sourceText'].startswith('Why the gap?')]
            self.assertEqual(len(bottom),1);self.assertIn('deal pipeline',bottom[0]['sourceText']);self.assertIn('\n',bottom[0]['rawText'])
            self.assertTrue(bottom[0]['corrections'])

    def test_background_rectangle_alone_does_not_trigger_vision(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'plain.pdf';c=canvas.Canvas(str(source))
            c.rect(0,0,595.2756,841.8898,fill=0);c.setFont('Helvetica',12)
            c.drawString(50,700,'A sufficiently long ordinary paragraph that does not need a vision model.');c.save()
            p=extract_pdf(source,root/'site','fixture')[0];self.assertEqual(routing(p)[0],'native')

    def test_visual_result_replaces_interleaved_units_but_keeps_every_anchor(self):
        p=page('Left policy words Analyst 250 350');p['units'][0]['position']=[.1,.3,.9,.34]
        result={'blocks':[{'type':'paragraph','text':'Left policy words','bbox':[.1,.3,.45,.34],'readingOrder':0}],
                'tables':[{'bbox':[.55,.3,.9,.34],'rows':[['Analyst','250 350']],'readingOrder':1}]}
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            old=copy.deepcopy(p['units'][0]);commit_layout(p,result,Path(d))
            archived=next(u for u in p['units'] if u['id']==old['id'])
            self.assertTrue(archived['reviewOnly']);self.assertEqual(archived['rawText'],old['rawText'])
            self.assertEqual(len(archived['supersededByIds']),3)
            self.assertEqual(len([u for u in p['units'] if not u.get('reviewOnly')]),3)
            ids=[u['id'] for u in p['units']];commit_layout(p,result,Path(d));self.assertEqual(ids,[u['id'] for u in p['units']])

    def test_missing_number_is_not_hidden_by_distributed_coverage(self):
        p=page('Left policy words Analyst 250 351');p['units'][0]['position']=[.1,.3,.9,.34]
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            commit_layout(p,{'blocks':[{'text':'Left policy words','bbox':[.1,.3,.45,.34]}],'tables':[{'bbox':[.55,.3,.9,.34],'rows':[['Analyst','250 350']]}]},Path(d))
            old=next(u for u in p['units'] if '351' in u['sourceText']);self.assertFalse(old.get('reviewOnly'));self.assertTrue(old['uncertain'])

    def test_fallback_order_does_not_interleave_columns_or_table_cells(self):
        p=page('');p['units']=[]
        blocks=[{'type':'paragraph','text':text,'bbox':box} for text,box in [('title',[.05,.05,.95,.12]),('left1',[.05,.2,.46,.3]),('right1',[.56,.2,.95,.3]),('left2',[.05,.4,.46,.5]),('footer',[.05,.8,.95,.86])]]
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            commit_layout(p,{'blocks':blocks,'tables':[{'bbox':[.56,.35,.95,.6],'rows':[['a','b'],['c','d']]}]},Path(d))
            self.assertEqual([u['sourceText'] for u in p['units']],['title','left1','left2','right1','a','b','c','d','footer'])

    def test_visual_request_uses_positioned_lines_in_one_call(self):
        p=page('old interleaved text');p['textLines']=[line('left',[.1,.1,.4,.2]),line('right',[.6,.1,.9,.2])]
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            parser=DocumentParser(PROFILE,d)
            with patch.object(parser.model,'request',return_value={'blocks':[]}) as request:
                parser._parse(p,Path(d));payload=request.call_args.args[1]
                self.assertNotIn('nativeTextHint',payload);self.assertEqual(payload['nativeTextLines'][1]['bbox'],[.6,.1,.9,.2]);self.assertEqual(request.call_count,1)

    def test_cached_native_paragraph_upgrade_retranslates_whole_and_keeps_anchors(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'lecture.pdf';source.write_bytes(b'fixture')
            old=page('An employer sells a domestic deal');a=old['units'][0]
            a.update(position=[.1,.4,.9,.42],translatedText='old fragment',translationStatus='complete')
            b=copy.deepcopy(a);b.update(id=a['id']+'-second',sourceText='pipeline rather than pure cash.',rawText='pipeline rather than pure cash.',position=[.1,.433,.8,.453])
            old['units'].append(b);old.update(visualStatus='complete',transcriptionStatus='complete',validationMethod='native-text-plus-local-checks')
            fresh=page(a['sourceText']+' '+b['sourceText']);fresh['units'][0]['position']=[.1,.4,.9,.453]
            old['rawText']=fresh['rawText']
            fresh['layoutAnalysis']={'version':1,'complex':False,'reasons':[],'horizontalRules':[]}
            saved=root/'cache'/course_id([source])/(old['id']+'.json')
            atomic_json(saved,{'page':old,'stages':{'parse':'v3-adaptive-'+fingerprint(PROFILE)}})
            batches=[]
            class Translator:
                available=True;model='fixture'
                def request(self,system,data,**kwargs):
                    batches.append(data['units'])
                    return {'translations':[{'id':u['id'],'translatedText':'完整段落译文。'} for u in data['units']]}
            class Parser:
                def __init__(self,*args):pass
                def parse(self,*args):raise AssertionError('Native upgrade must not call vision')
            with patch('course_compiler.pipeline_v2.extract_files',side_effect=lambda *a:copy.deepcopy([{'id':'lecture-test','name':'lecture.pdf','pages':[fresh]}])),patch('course_compiler.pipeline_v2.make_model',return_value=Translator()),patch('course_compiler.pipeline_v2.DocumentParser',Parser):
                c=compile_course([source],root/'site',{'parse':PROFILE,'translation':PROFILE},root/'cache',workers=1,translation_context={'subject':'Finance','style':'Faithful'})
                units=c['files'][0]['pages'][0]['units'];active=[u for u in units if not u.get('reviewOnly')]
                self.assertEqual(len(active),1);self.assertEqual(active[0]['sourceText'],fresh['rawText'])
                self.assertEqual(len(batches),1);self.assertEqual(len(batches[0]),1)
                self.assertTrue({a['id'],b['id']}<={u['id'] for u in units});self.assertEqual(c['quality']['errors'],[])
                compile_course([source],root/'site',{'parse':PROFILE,'translation':PROFILE},root/'cache',workers=1,translation_context={'subject':'Finance','style':'Faithful'})
                self.assertEqual(len(batches),1)

    def test_previous_visual_cache_is_reused_without_a_paid_migration(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);source=root/'lecture.pdf';source.write_bytes(b'fixture')
            p=page();p.update(visualStatus='complete',transcriptionStatus='complete',validationMethod='single-pass-plus-local-checks',layoutAnalysis={'complex':True})
            p['units'][0].update(translatedText='已完成译文',translationStatus='complete')
            atomic_json(root/'cache'/course_id([source])/(p['id']+'.json'),{'page':p,'stages':{'parse':'v3-adaptive-'+fingerprint(PROFILE)}})
            class NoRequests:
                available=True;model='fixture'
                def __init__(self,*args):pass
                def parse(self,*args):raise AssertionError('Paid reparse during migration')
                def request(self,*args,**kwargs):raise AssertionError('Paid translation during migration')
            class Parser:
                def __init__(self,*args):pass
                def parse(self,*args):raise AssertionError('Paid reparse during migration')
            with patch('course_compiler.pipeline_v2.extract_files',return_value=[{'id':'lecture-test','name':'lecture.pdf','pages':[p]}]),patch('course_compiler.pipeline_v2.make_model',return_value=NoRequests()),patch('course_compiler.pipeline_v2.DocumentParser',Parser):
                c=compile_course([source],root/'site',{'parse':PROFILE,'translation':PROFILE},root/'cache',workers=1,translation_context={'subject':'Finance','style':'Faithful'})
                self.assertEqual(c['metrics']['resumedPages'],1);self.assertEqual(c['metrics']['documentCalls'],0)


if __name__=='__main__':unittest.main()
