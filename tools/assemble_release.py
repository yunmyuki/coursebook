"""Reassemble verified release ZIP bytes from existing assets, without recompression.

No binary modification: every source and final archive must match its SHA256.
Used when an already uploaded Lite archive shares most files with an Office asset.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def records(path):
    with zipfile.ZipFile(path) as archive:
        starts=[i.header_offset for i in sorted(archive.infolist(),key=lambda i:i.header_offset)]
        assert starts and starts[0]==0
        starts.extend([archive.start_dir,path.stat().st_size])
    with path.open('rb') as stream:
        for start,end in zip(starts,starts[1:]):
            stream.seek(start);yield start,stream.read(end-start)


def create(bases,targets,directory):
    directory.mkdir(parents=True,exist_ok=True)
    manifest={'sources':[], 'targets':[]};index={}
    for path in bases:
        number=len(manifest['sources'])
        manifest['sources'].append({'file':path.name,'sha256':digest(path),'bytes':path.stat().st_size})
        for offset,data in records(path):index[hashlib.sha256(data).hexdigest()]=[number,offset,len(data)]
    patch=directory/'assembly-patch.bin';number=len(manifest['sources'])
    with patch.open('wb') as stream:
        for path in targets:
            pieces=[]
            for _,data in records(path):
                key=hashlib.sha256(data).hexdigest()
                if key not in index:
                    index[key]=[number,stream.tell(),len(data)];stream.write(data)
                pieces.append(index[key])
            manifest['targets'].append({'file':path.name,'bytes':path.stat().st_size,'sha256':digest(path),'pieces':pieces})
    manifest['sources'].append({'file':patch.name,'sha256':digest(patch),'bytes':patch.stat().st_size})
    (directory/'assembly-manifest.json').write_text(json.dumps(manifest,separators=(',',':')),'utf-8')
    print(json.dumps({'patchBytes':patch.stat().st_size,'manifestBytes':(directory/'assembly-manifest.json').stat().st_size}))


def safe_name(name):
    if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or name in ('.','..'):
        raise ValueError('Invalid archive filename')
    return name


def assemble(manifest_path,sources,dest):
    manifest=json.loads(manifest_path.read_text('utf-8'));dest.mkdir(parents=True,exist_ok=True)
    inputs=[]
    for source in manifest['sources']:
        path=sources/safe_name(source['file'])
        if path.is_symlink() or path.stat().st_size!=source['bytes'] or digest(path)!=source['sha256']:
            raise ValueError('Source hash mismatch: '+path.name)
        inputs.append(path)
    for target in manifest['targets']:
        path=dest/safe_name(target['file'])
        if path.exists():raise ValueError('Output already exists: '+path.name)
        with path.open('wb') as output:
            for number,offset,size in target['pieces']:
                if not (isinstance(number,int) and 0<=number<len(inputs) and isinstance(offset,int) and isinstance(size,int) and offset>=0 and size>=0 and offset+size<=inputs[number].stat().st_size):
                    raise ValueError('Invalid source span')
                with inputs[number].open('rb') as stream:
                    stream.seek(offset);remaining=size
                    while remaining:
                        data=stream.read(min(remaining,1024*1024))
                        if not data:raise ValueError('Truncated source')
                        output.write(data);remaining-=len(data)
        if path.stat().st_size!=target['bytes'] or digest(path)!=target['sha256']:raise ValueError('Output hash mismatch: '+path.name)
        with zipfile.ZipFile(path) as archive:
            if archive.testzip():raise ValueError('Invalid output ZIP')
        print('Verified exact archive: '+path.name,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='command',required=True)
    make=commands.add_parser('create');make.add_argument('--base',action='append',type=Path,required=True);make.add_argument('--target',action='append',type=Path,required=True);make.add_argument('--output',type=Path,required=True)
    build=commands.add_parser('assemble');build.add_argument('--manifest',type=Path,required=True);build.add_argument('--sources',type=Path,required=True);build.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='create':create(args.base,args.target,args.output)
    else:assemble(args.manifest,args.sources,args.output)
