import copy,io,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from test_v2 import page,PROFILE
from test_layout import line
from course_compiler.visual_quality import check_layout,cached_page_issues
from course_compiler.visual_input import prepare_image
from course_compiler.model import Model
from course_compiler.reparse import reparse_page
from course_compiler.storage import Store,atomic_json
from course_compiler.pipeline import build_sections,quality


def columns():
    p=page();p['textLines']=[]
    pairs=[('What does core investment banking actually sell,','and who pays for it?'),('What does the job pay at each level,','and what does it cost in hours?'),('How is AI changing the work,','the hiring and the career ladder?')]
    for x,pair in zip((.05,.36,.67),pairs):
        p['textLines'] += [line(pair[0],[x,.73,x+.25,.75]),line(pair[1],[x,.764,x+.20,.784])]
    p['layoutAnalysis']={'horizontalRules':[],'complex':True}
    return p,pairs


class VisualQualityTests(unittest.TestCase):
    def test_row_interleaving_rebuilt_from_three_complete_source_regions(self):
        p,pairs=columns();result={'blocks':[{'type':'paragraph','text':' '.join(pair[row] for pair in pairs),'bbox':[.05,y,.92,y+.02]} for row,y in enumerate((.73,.764))]}
        fixed=check_layout(p,result)
        self.assertEqual([b['text'] for b in fixed['blocks']],[' '.join(pair) for pair in pairs])
        self.assertEqual(fixed['localQuality']['issues'],[]);self.assertEqual(len(fixed['localQuality']['repairs']),1)
        self.assertEqual(len(result['blocks']),2)
        p['units']=[{**p['units'][0],'sourceText':b['text'],'position':b['bbox']} for b in result['blocks']]
        self.assertTrue(cached_page_issues(p))

    def test_missing_word_or_sign_is_not_silently_reconstructed(self):
        p,pairs=columns();text=' '.join(part for pair in pairs for part in pair).replace('banking ','')
        fixed=check_layout(p,{'blocks':[{'type':'paragraph','text':text,'bbox':[.05,.73,.92,.784]}]})
        self.assertTrue(fixed['localQuality']['issues']);self.assertTrue(fixed['blocks'][0]['uncertain'])
        self.assertEqual(fixed['blocks'][0]['text'],text)

    def test_chart_labels_and_tables_do_not_become_prose(self):
        p,pairs=columns();b={'type':'paragraph','text':' '.join(part for pair in pairs for part in pair),'bbox':[.05,.73,.92,.784],'contentOrigin':'figure-transcription'}
        self.assertFalse(check_layout(p,{'blocks':[b]})['localQuality']['issues'])
        b.pop('contentOrigin');self.assertFalse(check_layout(p,{'blocks':[b],'figures':[{'bbox':b['bbox']} ]})['localQuality']['issues'])

    def test_missing_chart_labels_recovered_from_native_layer_without_interpretation(self):
        p=page();p['textLines']=[line('2022',[.2,.6,.28,.63]),line('587',[.2,.3,.27,.33]),line('Separate body',[.1,.85,.8,.9])]
        result={'blocks':[],'figures':[{'kind':'chart','bbox':[.1,.2,.8,.7]}]}
        fixed=check_layout(p,result)
        self.assertEqual([b['text'] for b in fixed['blocks']],['2022','587'])
        self.assertTrue(all(b['contentOrigin']=='figure-transcription' for b in fixed['blocks']))
        again=check_layout(p,fixed);self.assertEqual(len(again['blocks']),2)

    def test_image_falls_back_for_probe_without_source(self):
        self.assertEqual(prepare_image({'image':'probe.jpg'},Path('tmp')).name,'probe.jpg')

    def test_high_detail_is_sent_in_api_payload(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);image=root/'sample.png';Image.new('RGB',(80,80)).save(image)
            model=Model(provider='openai',api_key='fixture',base_url='https://example.invalid',model='fixture',cache=root/'cache');model.image_detail='high'
            response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"ok":true}'}}]}).encode())
            with patch('urllib.request.urlopen',return_value=response) as send:
                model.request('test','fixture',image=image)
                body=json.loads(send.call_args.args[0].data);self.assertEqual(body['messages'][-1]['content'][-1]['image_url']['detail'],'high')

    def test_high_resolution_is_bounded_and_cached(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            root=Path(d);(root/'sources').mkdir();(root/'assets').mkdir();source=root/'sources/lecture-test.pdf'
            c=canvas.Canvas(str(source),pagesize=(1000,600));c.setFont('Helvetica',8);c.drawString(60,60,'Small source text for high detail rendering');c.save()
            p=page();p.update(width=1000,height=600,textLines=[line('Small source text',[.1,.2,.8,.3])]);p['textLines'][0]['typography']['fontSize']=8
            output=prepare_image(p,root);stamp=output.stat().st_mtime_ns
            with Image.open(output) as im:self.assertLessEqual(max(im.size),2800);self.assertGreater(im.width,1700)
            self.assertEqual(prepare_image(p,root),output);self.assertEqual(output.stat().st_mtime_ns,stamp)

    def test_failed_reparse_does_not_replace_course(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);cid='course-0123456789abcdef';site=store.course_path(cid);site.mkdir(parents=True)
            p=page();course={'id':cid,'files':[{'id':'lecture-test','pages':[p]}]};atomic_json(site/'course.json',course);before=(site/'course.json').read_bytes()
            with patch.object(store,'profiles',return_value={r:PROFILE for r in ('parse','translation','explanation')}),patch('course_compiler.reparse.DocumentParser') as parser:
                parser.return_value.parse.side_effect=ValueError('fixture failure')
                with self.assertRaisesRegex(ValueError,'fixture failure'):reparse_page(store,cid,p['id'])
            self.assertEqual((site/'course.json').read_bytes(),before)

    def test_successful_reparse_preserves_anchors_and_creates_backup(self):
        with tempfile.TemporaryDirectory(dir='tmp') as d:
            store=Store(d);cid='course-0123456789abcdef';site=store.course_path(cid);site.mkdir(parents=True)
            p=page();old_id=p['units'][0]['id']
            course={'id':cid,'files':[{'id':'lecture-test','name':'lecture.pdf','order':1,'pages':[p]}],'explanations':[]}
            build_sections(course['files']);atomic_json(site/'course.json',course);before=(site/'course.json').read_bytes()
            parsed={'blocks':[{'type':'paragraph','text':p['rawText'],'bbox':[.1,.1,.9,.3]}]}
            class Translator:
                model='fixture'
                def request(self,s,data,**kwargs):return {'translations':[{'id':u['id'],'translatedText':'完整译文'} for u in data['units']]}
            with patch.object(store,'profiles',return_value={r:PROFILE for r in ('parse','translation','explanation')}),patch('course_compiler.reparse.DocumentParser') as parser,patch('course_compiler.reparse.make_model',return_value=Translator()):
                parser.return_value.parse.return_value=parsed;r=reparse_page(store,cid,p['id'])
            updated=json.loads((site/'course.json').read_text('utf-8'));units=updated['files'][0]['pages'][0]['units']
            self.assertEqual((Path(r['backup'])/'course.json').read_bytes(),before)
            self.assertIn(old_id,[u['id'] for u in units]);self.assertEqual(updated['quality']['errors'],[])
            self.assertTrue(all(u['translationStatus']=='complete' for u in units if not u.get('reviewOnly')))


if __name__=='__main__':unittest.main()
