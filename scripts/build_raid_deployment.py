#!/usr/bin/env python3
"""Build the selected RAID release against verified unchanged 6C objects.

All changed C++ units are compiled fresh, including baked process identity.
This leaves the existing build and running runtime untouched. A build ledger
records the fixed base, new source commit, link inputs and output hashes.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parent
BASE = Path('/root/tracelens-releases/6c-readonly-20260928-dxdZa9')
BUILD = BASE/'cpp-build'
UNITS = [
    'src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp',
    'src/network/HTTPServer/routes/TaskCRUDRoutes.cpp',
    'src/network/HTTPServer/TaskManagerAnalysis.cpp',
    'src/network/HTTPServer/RaidTaskAdmission.cpp',
    'src/network/HTTPServer/routes/TaskBatchRoutes.cpp',
    'src/network/HTTPServer/HTTPserver.cpp',
]

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''): h.update(b)
    return h.hexdigest()

def main():
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
    if subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True).strip():
        raise RuntimeError('release source must be clean')
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=SOURCE).decode().split('\0')
    tree=hashlib.sha256()
    for name in sorted(n for n in tracked if n):
        p=SOURCE/name
        if p.is_file() and not p.is_symlink(): tree.update(name.encode()+b'\0'+sha(p).encode()+b'\n')
    tree_sha=tree.hexdigest(); release_id='6c-'+commit[:16]
    work=ROOT/'cpp-overlay'; work.mkdir(mode=0o700)
    gen=work/'generated/tracelens'; gen.mkdir(parents=True)
    header=(SOURCE/'include/tracelens/build_identity.h.in').read_text()
    for key,value in {'TRACELENS_RELEASE_ID':release_id,'TRACELENS_SOURCE_COMMIT':commit,'TRACELENS_SOURCE_SHA256':tree_sha}.items():
        header=header.replace('@'+key+'@',value)
    (gen/'build_identity.h').write_text(header)
    cmake=BUILD/'CMakeFiles/forensic_analyzer.dir'
    flags={}
    for line in (cmake/'flags.make').read_text().splitlines():
        if ' = ' in line:
            key,value=line.split(' = ',1); flags[key]=shlex.split(value)
    link=shlex.split((cmake/'link.txt').read_text())
    # Reused production objects are permitted only for byte-identical source.
    for entry in link:
        if entry.startswith('CMakeFiles/forensic_analyzer.dir/') and entry.endswith('.o'):
            relative=entry[len('CMakeFiles/forensic_analyzer.dir/'):-2]
            if relative in UNITS: continue
            current=SOURCE/relative; old=BASE/'source'/relative
            if current.is_file() and old.is_file() and sha(current)!=sha(old):
                raise RuntimeError('unselected C++ drift: '+relative)
    for path in (SOURCE/'src').rglob('*.h'):
        relative=path.relative_to(SOURCE)
        old=BASE/'source'/relative
        if old.is_file() and sha(path)!=sha(old): raise RuntimeError('existing header drift: '+str(relative))
    # Fresh sources use the new tree first, then the fixed baseline includes.
    include=['-I'+str(work/'generated')]
    for flag in flags['CXX_INCLUDES']:
        updated=flag.replace(str(BASE/'source'),str(SOURCE))
        # Some pinned SDK include directories are materialized outside Git.
        if updated.startswith('-I') and not Path(updated[2:]).is_dir(): updated=flag
        include.append(updated)
    compile_flags=[f for f in flags['CXX_FLAGS'] if not f.startswith('-O')]+['-O1','-include','utility']
    def compile_unit(item):
        index,name=item; obj=work/f'unit-{index}.o'
        subprocess.run([link[0],*flags['CXX_DEFINES'],*include,*compile_flags,'-c',str(SOURCE/name),'-o',str(obj)],check=True)
        return name,obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        objects=list(pool.map(compile_unit,enumerate(UNITS)))
    for name,obj in objects:
        original='CMakeFiles/forensic_analyzer.dir/'+name+'.o'
        if name.endswith('RaidTaskAdmission.cpp'): link.append(str(obj))
        else:
            if link.count(original)!=1: raise RuntimeError('base link layout mismatch')
            link[link.index(original)]=str(obj)
    binary=work/'forensic_analyzer'; link[link.index('-o')+1]=str(binary)
    material={}
    for entry in link:
        p=Path(entry)
        if not p.is_absolute(): p=BUILD/p
        if p.is_file(): material[str(p)]=sha(p)
    subprocess.run(link,cwd=BUILD,check=True)
    result={'release_id':release_id,'source_commit':commit,'source_tree_sha256':tree_sha,
        'base_commit':'29ac4513406ec3d6d0526c5a9de2d6fbeeabef25','fresh_units':UNITS,
        'compiler':link[0],'fresh_optimization':'O1','link_material_sha256':material,
        'binary':str(binary),'binary_sha256':sha(binary),'old_runtime_modified':False}
    (ROOT/'native-build.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('release_id','source_commit','binary','binary_sha256')}))

if __name__=='__main__': main()
