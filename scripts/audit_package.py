"""Static portability/encoding scan; assertions are limited to enumerated files."""
import argparse
import ast
import json
from pathlib import Path
import re


def scan(root, forbidden=()):
    root=Path(root).resolve()
    violations=[]
    files=[]
    text_io=0
    binary_io=0
    for path in sorted(root.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or '.venv' in path.parts or '.git' in path.parts:
            continue
        name=path.relative_to(root).as_posix()
        text=path.read_text(encoding='utf-8-sig')
        files.append(name)
        for token in forbidden:
            if token.casefold() in text.casefold():
                violations.append(f'{name}: forbidden personal token')
        absolute_pattern = r'(?i)(?<![a-z0-9])[a-z]:[\\/]|/(?:' + '|'.join(['Users','home']) + r')/[^/\s]+'
        if re.search(absolute_pattern,text):
            violations.append(f'{name}: machine-specific absolute path')
        if path.suffix!='.py':
            continue
        for node in ast.walk(ast.parse(text,filename=name)):
            if not isinstance(node,ast.Call):
                continue
            function=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
            if function not in {'read_text','write_text','open','fdopen'}:
                continue
            kwargs={kw.arg:kw.value for kw in node.keywords}
            mode=kwargs.get('mode')
            position=1 if isinstance(node.func,ast.Name) or function=='fdopen' else 0
            if mode is None and function in {'open','fdopen'} and len(node.args)>position:
                mode=node.args[position]
            if isinstance(mode,ast.Constant) and isinstance(mode.value,str) and 'b' in mode.value:
                binary_io+=1
                continue
            text_io+=1
            encoding=kwargs.get('encoding')
            if not isinstance(encoding,ast.Constant) or encoding.value not in {'utf-8','utf-8-sig'}:
                violations.append(f'{name}:{node.lineno}: text I/O requires explicit UTF-8')
    return {'status':'PASS' if not violations else 'FAIL','files':files,'file_count':len(files),
            'text_io_calls_explicit_utf8':text_io,'binary_io_calls':binary_io,'violations':violations}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--forbidden',action='append',default=[])
    args=parser.parse_args()
    result=scan(args.root,args.forbidden)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 2)
