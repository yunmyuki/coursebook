"""Generate original public demo material, with fixed human-written translations.

No user documents, API credentials, network requests, or model-generated claims.
"""
import json
import sys
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler.pipeline_v2 import compile_course
from course_compiler.pipeline import quality,build_sections
from course_compiler.export import export_site
from course_compiler.storage import atomic_json

CONTENT=[
 [('Part 1: Learning with evidence','第一章：用证据学习'),
  ('A question is the beginning of understanding.','一个问题，是理解的起点。'),
  ('Read the source before asking for an explanation.','先阅读原文，再寻求解释。'),
  ('Connect every claim to a specific passage.','把每一项主张关联到具体的原文段落。'),
  ('1. Read the original material.','1. 阅读原始材料。'),
  ('2. Compare the translation.','2. 对照译文。'),
  ('3. Ask a focused question.','3. 提出一个明确的问题。'),
  ('4. Record your own understanding.','4. 记录自己的理解。')],
 [('Part 2: Practice and feedback','第二章：练习与反馈'),
  ('Practice turns an idea into a usable skill.','练习将一个想法转化为可运用的技能。'),
  ('Try to explain a concept in your own words.','尝试用自己的话解释一个概念。'),
  ('Compare your answer with the original source.','将你的回答与原始资料对照。'),
  ('Notice what is missing, then try again.','发现遗漏的内容，然后再试一次。')],
 [('Part 3: Reflect and connect','第三章：反思与联系'),
  ('A useful note connects ideas rather than copies them.','有用的笔记会联系不同想法，而非仅仅抄写它们。'),
  ('What changed in your understanding today?','今天，你的理解发生了什么变化？'),
  ('What would you like to investigate next?','接下来，你想进一步探究什么？')]
]

def main():
    output=ROOT/'tmp/release-demo';output.mkdir(parents=True,exist_ok=True)
    source=output/'Learning with evidence.pdf';writer=PdfWriter()
    for rows in CONTENT:
        page=writer.add_blank_page(width=760,height=540)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        commands=[]
        for i,(text,_) in enumerate(rows):
            text=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append(f'BT /F1 {26 if i==0 else 17} Tf 52 {480-i*48} Td ({text}) Tj ET')
        stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    writer.write(source)
    profile={'provider':'openai','engine':'vision','baseUrl':'https://example.invalid/v1','model':'demo-fixture','apiKey':''}
    site=output/'site'
    course=compile_course([source],site,{r:profile for r in ('parse','translation','explanation')},output/'cache',ai=False,title='Learning with evidence')
    translations=dict(row for rows in CONTENT for row in rows)
    for f in course['files']:
        for page in f['pages']:
            for u in page['units']:
                u.update(translatedText=translations[u['sourceText']],translationStatus='complete',translationMethod='human-authored-demo')
            page.update(visualStatus='complete',transcriptionStatus='complete',validationMethod='human-authored-fixture')
    course['subtitle']='学习方法 · 自制演示课程';course['translationContext']={'subject':'学习方法','style':'清楚、准确的教学表达。','status':'human-authored-demo'}
    course['provenance']['demo']='Original public sample with fixed human translations; not a model-quality benchmark.'
    build_sections(course['files']);course['quality']=quality(course)
    atomic_json(site/'course.json',course);atomic_json(site/'quality-report.json',course['quality'])
    dest=ROOT/'release'/__import__('course_compiler').__version__/'CourseCompiler-Demo.zip';dest.parent.mkdir(parents=True,exist_ok=True)
    export_site(course,site,dest)
    print(json.dumps({'id':course['id'],'pages':3,'zip':str(dest),'units':sum(len(p['units']) for f in course['files'] for p in f['pages'])}),flush=True)

if __name__=='__main__':main()
