#!/usr/bin/env python3
"""Reproduce Word, protection, and slide spacing differences with a supplied X2T runtime."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from smoke_x2t_runtime import run, sha256
ROOT=Path(__file__).resolve().parents[1]
WORD='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
DRAW='http://schemas.openxmlformats.org/drawingml/2006/main'

def rewrite(source: Path,destination: Path,parts: dict[str,bytes]) -> None:
    with zipfile.ZipFile(source) as original,zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as output:
        for item in original.infolist():output.writestr(item,parts.pop(item.filename,original.read(item.filename)))
        for name,data in parts.items():output.writestr(name,data)
    with zipfile.ZipFile(destination) as package:
        assert package.testzip() is None
        for name in package.namelist():
            if name.endswith(('.xml','.rels')):ET.fromstring(package.read(name))

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    args=parser.parse_args();runtime=args.runtime.resolve();exe=runtime/'x2t.exe';fonts=runtime/'fonts/font_selection.bin'
    if not exe.is_file() or not fonts.is_file():raise SystemExit('Supplied runtime must contain x2t.exe and fonts/font_selection.bin')
    work=args.work_root.resolve();work.mkdir(parents=True,exist_ok=False)
    files=[exe,*sorted(runtime.glob('*.dll'))];hashes={p.name:sha256(p) for p in files}
    producer=runtime/'core-producer.json'
    report={'runtime':str(runtime),'x2tSha256':hashes['x2t.exe'],'runtimeFiles':hashes,'producer':json.loads(producer.read_text(encoding='utf-8')) if producer.exists() else None,'tests':[],'scope':'Real DOCX/PPTX -> BIN -> OOXML; no PDF, VML, SDKJS or visual acceptance'}
    def roundtrip(label: str,source: Path,suffix: str) -> Path:
        binary=source.parent/'Editor.bin';restored=source.parent/('restored'+suffix)
        conversions=[run(label+':ooxml-to-bin',[str(exe),str(source),str(binary),str(fonts)]),run(label+':bin-to-ooxml',[str(exe),str(binary),str(restored),str(fonts)])]
        report['tests'].append({'case':label,'source':str(source),'sourceSha256':sha256(source),'restored':str(restored),'restoredSha256':sha256(restored),'conversions':conversions})
        with zipfile.ZipFile(restored) as z:assert z.testzip() is None
        return restored
    word=ROOT/'tests/core-features/fixtures/word-core-features.docx'
    for label,algorithm,sid,provider in [('algorithm-only',True,False,False),('algorithm-sid',True,True,False),('algorithm-provider',True,False,True),('algorithm-both',True,True,True),('sid-only-control',False,True,False)]:
        folder=work/('word-'+label);folder.mkdir();source=folder/'source.docx'
        attrs={'edit':'readOnly','enforcement':'1','hashValue':'YWJj','saltValue':'ZGVm','spinCount':'1000'}
        if algorithm:attrs['algorithmName']='SHA-256'
        if sid:attrs['cryptAlgorithmSid']='12'
        if provider:attrs['cryptProviderType']='rsaAES'
        settings=('<?xml version="1.0" encoding="UTF-8"?><w:settings xmlns:w="'+WORD+'"><w:documentProtection '+ ' '.join('w:'+k+'="'+v+'"' for k,v in attrs.items())+'/></w:settings>').encode()
        with zipfile.ZipFile(word) as z:ct=z.read('[Content_Types].xml').decode()
        ct=ct.replace('</Types>','<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>')
        rels=b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/></Relationships>'
        rewrite(word,source,{'word/settings.xml':settings,'word/_rels/document.xml.rels':rels,'[Content_Types].xml':ct.encode()})
        restored=roundtrip('word-'+label,source,'.docx')
        with zipfile.ZipFile(restored) as z:node=ET.fromstring(z.read('word/settings.xml')).find('{'+WORD+'}documentProtection')
        actual={k.split('}')[-1]:v for k,v in node.attrib.items()} if node is not None else {}
        report['tests'][-1].update(expectedAlgorithmName='SHA-256' if algorithm else None,actualProtection=actual,passed=actual.get('algorithmName')==('SHA-256' if algorithm else None))
    for label,layout,expected in [
        ('combine-with-id',{'id':'1','combine':'1','combineBrackets':'square'},{'id':'1','combine':'1','combineBrackets':'square'}),
        ('combine-false-with-id',{'id':'23','combine':'0','combineBrackets':'square'},{'id':'23','combine':'0','combineBrackets':'square'}),
        ('combine-without-id',{'combine':'1','combineBrackets':'round'},{'combine':'1','combineBrackets':'round'}),
        ('vertical-compress-only',{'vertCompress':'1'},{'vertCompress':'1'}),
    ]:
        folder=work/('word-'+label);folder.mkdir();source=folder/'source.docx'
        with zipfile.ZipFile(word) as z:xml=z.read('word/document.xml').decode()
        attributes=' '.join('w:'+key+'="'+value+'"' for key,value in layout.items())
        xml,count=re.subn(r'<w:r><w:t>',lambda _: '<w:r><w:rPr><w:eastAsianLayout '+attributes+'/></w:rPr><w:t>',xml,count=1)
        assert count==1
        rewrite(word,source,{'word/document.xml':xml.encode()})
        restored=roundtrip('word-'+label,source,'.docx')
        with zipfile.ZipFile(restored) as z:
            root=ET.fromstring(z.read('word/document.xml'))
            node=root.find('.//{'+WORD+'}eastAsianLayout')
        actual={k.split('}')[-1]:v for k,v in node.attrib.items()} if node is not None else {}
        report['tests'][-1].update(expectedEastAsianLayout=expected,actualEastAsianLayout=actual,passed=actual==expected)
    pptx=ROOT/'tests/core-features/fixtures/slide-core-features.pptx'
    for prefix in ('a','draw'):
        for unit,value in [('spcPct',75000),('spcPts',1800)]:
            label=f'slide-{prefix}-{unit}';folder=work/label;folder.mkdir();source=folder/'source.pptx';marker='X2T-SPACING-'+label
            with zipfile.ZipFile(pptx) as z:xml=z.read('ppt/slides/slide1.xml').decode()
            declaration='' if prefix=='a' else ' xmlns:draw="'+DRAW+'"'
            paragraph='<a:p><a:pPr><a:lnSpc'+declaration+'><'+prefix+':'+unit+' val="'+str(value)+'"/></a:lnSpc></a:pPr><a:r><a:t>'+marker+'</a:t></a:r></a:p>'
            xml,count=re.subn(r'<a:p>.*?</a:p>',lambda _:paragraph,xml,count=1,flags=re.S);assert count==1
            rewrite(pptx,source,{'ppt/slides/slide1.xml':xml.encode()})
            restored=roundtrip(label,source,'.pptx');actual=[]
            with zipfile.ZipFile(restored) as z:
                tree=ET.fromstring(z.read('ppt/slides/slide1.xml'))
                for p in tree.iter('{'+DRAW+'}p'):
                    if marker not in ''.join(p.itertext()):continue
                    for child in p.findall('{'+DRAW+'}pPr/{'+DRAW+'}lnSpc/*'):actual.append({'unit':child.tag.split('}')[-1],'value':child.get('val')})
            report['tests'][-1].update(expectedSpacing={'unit':unit,'value':str(value)},actualSpacing=actual,passed=actual==[{'unit':unit,'value':str(value)}])
    report['runtimeUnchanged']=hashes=={p.name:sha256(p) for p in files}
    assert report['runtimeUnchanged']
    report['summary']={'cases':len(report['tests']),'passed':sum(x['passed'] for x in report['tests']),'differences':[x['case'] for x in report['tests'] if not x['passed']]}
    receipt=work/'receipt.json';receipt.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'receipt':str(receipt),**report['summary'],'results':[{k:x.get(k) for k in ('case','passed','actualProtection','actualSpacing')} for x in report['tests']]},indent=2,ensure_ascii=False))
if __name__=='__main__':main()
