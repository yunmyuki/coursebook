import argparse
import json
from pathlib import Path
from .model import Model
from .pipeline import compile_course
from .export import export_site


def main():
    parser=argparse.ArgumentParser(description='Compile lecture files into an offline bilingual course.')
    sub=parser.add_subparsers(dest='command',required=True)
    compile_cmd=sub.add_parser('compile')
    compile_cmd.add_argument('inputs',nargs='+')
    compile_cmd.add_argument('--output',default='dist')
    compile_cmd.add_argument('--workers',type=int,default=4)
    compile_cmd.add_argument('--extract-only',action='store_true')
    compile_cmd.add_argument('--skip-audit',action='store_true')
    compile_cmd.add_argument('--no-explanations',action='store_true')
    compile_cmd.add_argument('--model')
    compile_cmd.add_argument('--provider',choices=['openai','anthropic','siliconflow'])
    compile_cmd.add_argument('--zip',dest='zip_path')
    compile_cmd.add_argument('--legacy',action='store_true',help='Use the previous two-pass pipeline')
    compile_cmd.add_argument('--parse-mode',choices=['adaptive','vision'],default='adaptive')
    serve=sub.add_parser('serve')
    serve.add_argument('--port',type=int,default=8765)
    export=sub.add_parser('export')
    export.add_argument('--output',default='dist')
    export.add_argument('--zip',dest='zip_path',default='Course-Compiler.zip')
    args=parser.parse_args()
    if args.command=='serve':
        from .app_server import make_server
        server=make_server(args.port)
        print(f'Course Compiler: http://127.0.0.1:{server.server_port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
    elif args.command=='export':
        course=json.loads((Path(args.output)/'course.json').read_text('utf-8'))
        export_site(course,args.output,args.zip_path)
    else:
        paths=[]
        for item in args.inputs:
            p=Path(item)
            paths.extend(x for x in p.iterdir() if x.suffix.lower() in ('.pdf','.ppt','.pptx')) if p.is_dir() else paths.append(p)
        if not paths:
            parser.error('No lecture files found.')
        def progress(stage,current,total,message):
            print(json.dumps({'stage':stage,'current':current,'total':total,'message':message},ensure_ascii=False),flush=True)
        if args.legacy:
            course=compile_course(paths,args.output,model=Model(provider=args.provider,model=args.model),workers=args.workers,ai=not args.extract_only,audit=not args.skip_audit,explanations=not args.no_explanations,progress=progress)
        else:
            from .pipeline_v2 import compile_course as compile_v2
            from .storage import Store
            store=Store();profiles=store.profiles()
            for p in profiles.values():
                if args.model:p['model']=args.model
                if args.provider:p['provider']=args.provider
            course=compile_v2(paths,args.output,profiles,store.root/'cache',workers=args.workers,ai=not args.extract_only,explanations=not args.no_explanations,parse_mode=args.parse_mode,progress=progress,request_limit=store.settings().get('requestLimit',1000))
        export_site(course,args.output,args.zip_path)
        print(json.dumps(course['quality'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
