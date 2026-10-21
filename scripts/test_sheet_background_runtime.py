#!/usr/bin/env python3
"""Exercise worksheet Picture29 media and Native PDF with a supplied runtime.

Requires Pillow; --sdkjs-root additionally requires PyMuPDF. Does not alter the
supplied runtime, run browser commands or claim SDKJS History action coverage.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, posixpath, shutil, subprocess, sys
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image
from smoke_x2t_runtime import sha256
ROOT=Path(__file__).resolve().parents[1]
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('',S);ET.register_namespace('r',R)

def png(color, size=(64,48)):
    image=Image.new('RGBA',size,color);buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()
def pixels(data):
    try:
        image=Image.open(io.BytesIO(data)).convert('RGBA')
        return {'size':list(image.size),'rgbaSha256':hashlib.sha256(image.tobytes()).hexdigest()}
    except Exception:return None
def package(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n:z.read(n) for n in z.namelist()}
def write(path,parts):
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in parts.items():
            if name.endswith(('.xml','.rels')):ET.fromstring(data)
            z.writestr(name,data)
def serialize(node):return ET.tostring(node,encoding='utf-8',xml_declaration=True)
def resolve(part,target):return posixpath.normpath(posixpath.join(posixpath.dirname(part),target))
def sheets(parts):
    rels={x.get('Id'):resolve('xl/workbook.xml',x.get('Target')) for x in ET.fromstring(parts['xl/_rels/workbook.xml.rels'])}
    return [(s.get('name'),rels[s.get('{'+R+'}id')]) for s in ET.fromstring(parts['xl/workbook.xml']).findall('{'+S+'}sheets/{'+S+'}sheet')]
def snapshot(path):
    parts=package(path);result=[]
    for name,part in sheets(parts):
        root=ET.fromstring(parts[part]);picture=root.find('{'+S+'}picture');view=root.find('{'+S+'}sheetViews/{'+S+'}sheetView')
        item={'name':name,'picture':picture is not None,'grid':view.get('showGridLines','1') if view is not None else '1'}
        if picture is not None:
            rid=picture.get('{'+R+'}id');rp=posixpath.dirname(part)+'/_rels/'+posixpath.basename(part)+'.rels'
            rels={r.get('Id'):r for r in ET.fromstring(parts[rp])} if rp in parts else {}
            rel=rels.get(rid);item['relationshipExists']=rel is not None
            if rel is not None:
                target=resolve(part,rel.get('Target'));item.update(target=target,relativeTarget=not rel.get('Target','').startswith(('/','http:','https:','file:')),relationshipType=rel.get('Type'),mediaExists=target in parts)
                if target in parts:
                    ct=ET.fromstring(parts['[Content_Types].xml']);extension=posixpath.splitext(target)[1][1:]
                    defaults={x.get('Extension'):x.get('ContentType') for x in ct if x.tag.endswith('}Default')}
                    overrides={x.get('PartName'):x.get('ContentType') for x in ct if x.tag.endswith('}Override')}
                    item.update(mediaSha256=hashlib.sha256(parts[target]).hexdigest(),image=pixels(parts[target]),mediaContentType=overrides.get('/'+target,defaults.get(extension)))
        result.append(item)
    styles=ET.fromstring(parts['xl/styles.xml']);fills=styles.find('{'+S+'}fills');xfs=styles.find('{'+S+'}cellXfs')
    for item,(_,part) in zip(result,sheets(parts)):
        root=ET.fromstring(parts[part]);cell=root.find('.//{'+S+'}c[@r="A1"]');idx=int(cell.get('s','0')) if cell is not None else 0
        fillId=int(xfs[idx].get('fillId','0'));fill=fills[fillId];pattern=fill.find('{'+S+'}patternFill')
        item['A1fillRaw']=ET.tostring(fill,encoding='unicode')
        foreground=pattern.find('{'+S+'}fgColor') if pattern is not None else None
        item['A1fill']={'patternType':pattern.get('patternType','none') if pattern is not None else 'none','foreground':dict(foreground.attrib) if foreground is not None else {}}
    names=ET.fromstring(parts['xl/workbook.xml']).find('{'+S+'}definedNames')
    return {'sheets':result,'definedNames':[{**n.attrib,'text':n.text} for n in names] if names is not None else []}
def picture(parts,sheet,target,media=None):
    part=f'xl/worksheets/sheet{sheet}.xml';root=ET.fromstring(parts[part]);old=root.find('{'+S+'}picture')
    if old is not None:root.remove(old)
    relpath=f'xl/worksheets/_rels/sheet{sheet}.xml.rels'
    if target is None:
        parts.pop(relpath,None)
    else:
        ET.SubElement(root,'{'+S+'}picture',{'{'+R+'}id':'rIdBackground'})
        rels=ET.Element('{'+P+'}Relationships');ET.SubElement(rels,'{'+P+'}Relationship',{'Id':'rIdBackground','Type':R+'/image','Target':target});parts[relpath]=serialize(rels)
        if media is not None:parts[resolve(part,target)]=media
    parts[part]=serialize(root)
def single_print(parts):
    wb=ET.fromstring(parts['xl/workbook.xml']);ss=wb.find('{'+S+'}sheets')
    for s in list(ss)[1:]:ss.remove(s)
    old=wb.find('{'+S+'}definedNames')
    if old is not None:wb.remove(old)
    names=ET.SubElement(wb,'{'+S+'}definedNames')
    ET.SubElement(names,'{'+S+'}definedName',{'name':'_xlnm.Print_Area','localSheetId':'0'}).text="'SharedBackground'!$C$3:$P$80"
    ET.SubElement(names,'{'+S+'}definedName',{'name':'_xlnm.Print_Titles','localSheetId':'0'}).text="'SharedBackground'!$3:$4"
    parts['xl/workbook.xml']=serialize(wb)
    root=ET.fromstring(parts['xl/worksheets/sheet1.xml']);root.find('{'+S+'}sheetViews/{'+S+'}sheetView').set('showGridLines','0')
    for tag in ('pageMargins','pageSetup'):
        old=root.find('{'+S+'}'+tag)
        if old is not None:root.remove(old)
    pic=root.find('{'+S+'}picture');index=list(root).index(pic) if pic is not None else len(root)
    margins=ET.Element('{'+S+'}pageMargins',dict(left='0.25',right='0.25',top='0.25',bottom='0.25',header='0',footer='0'));root.insert(index,margins)
    setup=ET.Element('{'+S+'}pageSetup',dict(paperSize='9',orientation='portrait',scale='100'));root.insert(index+1,setup)
    parts['xl/worksheets/sheet1.xml']=serialize(root)
    return parts

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--runtime',type=Path,required=True);ap.add_argument('--work-root',type=Path,required=True);ap.add_argument('--sdkjs-root',type=Path);args=ap.parse_args()
    runtime=args.runtime.resolve();work=args.work_root.resolve();work.mkdir(parents=True,exist_ok=False)
    exe=runtime/'x2t.exe';fonts=runtime/'fonts/font_selection.bin'
    originals={p.name:sha256(p) for p in [exe,*runtime.glob('*.dll')]}
    report={'runtime':str(runtime),'x2tSha256':originals['x2t.exe'],'files':originals,'cases':[],'pdf':[],'notCovered':['browser SetPicture200 add/replace/delete/undo/redo','production print entry','page-by-page visual approval']}
    def invoke(command,label):
        result=subprocess.run(command,cwd=Path(command[0]).parent,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
        return {'label':label,'exitCode':result.returncode,'output':(result.stdout+result.stderr)[-2000:]}
    base=package(ROOT/'tests/core-features/fixtures/sheet-core-features.xlsx');magenta=png((230,20,170,255));cyan=png((10,170,210,255));alpha=png((230,20,170,128));tile=png((230,20,170,255),(1,1))
    cases=[]
    for name in ('shared','independent-rid','relative-alias','remove-one','remove-all','alpha','tile-1x1','prefix-alias','missing-media','missing-rel','corrupt-image'):
        parts=dict(base);picture(parts,1,'../media/known.png',magenta);picture(parts,2,'../media/known.png')
        if name=='independent-rid':picture(parts,2,'../media/other.png',cyan)
        elif name=='relative-alias':picture(parts,2,'../media/./known.png')
        elif name=='remove-one':picture(parts,1,None)
        elif name=='remove-all':picture(parts,1,None);picture(parts,2,None)
        elif name=='alpha':parts['xl/media/known.png']=alpha
        elif name=='tile-1x1':parts['xl/media/known.png']=tile
        elif name=='prefix-alias':parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'xmlns:r=',b'xmlns:rel=').replace(b'r:id=',b'rel:id=')
        elif name=='missing-media':parts.pop('xl/media/known.png')
        elif name=='missing-rel':parts.pop('xl/worksheets/_rels/sheet1.xml.rels')
        elif name=='corrupt-image':parts['xl/media/known.png']=b'not a PNG image'
        folder=work/name;folder.mkdir();source=folder/'source.xlsx';write(source,parts);expected=snapshot(source);negative=name in ('missing-media','missing-rel','corrupt-image')
        case={'name':name,'negative':negative,'input':str(source),'expected':expected,'generations':[]};current=source
        for generation in (1,2):
            binary=folder/f'Editor-{generation}.bin';restored=folder/f'restored-{generation}.xlsx'
            commands=[invoke([str(exe),str(current),str(binary),str(fonts)],'xlsx-to-bin')]
            if commands[-1]['exitCode']==0 and binary.exists():commands.append(invoke([str(exe),str(binary),str(restored),str(fonts)],'bin-to-xlsx'))
            result={'generation':generation,'commands':commands}
            if len(commands)==2 and all(r['exitCode']==0 for r in commands) and restored.exists():
                actual=snapshot(restored);checks=[]
                checks.append({'check':'sheet-count-and-order','passed':[x['name'] for x in actual['sheets']]==[x['name'] for x in expected['sheets']]})
                for want,got in zip(expected['sheets'],actual['sheets']):
                    for key in ('picture','grid','A1fill'):checks.append({'check':want['name']+':'+key,'passed':want.get(key)==got.get(key)})
                    if want.get('picture') and not negative:
                        for key in ('relationshipExists','mediaExists','relativeTarget'):checks.append({'check':want['name']+':'+key,'passed':got.get(key) is True})
                        checks.append({'check':want['name']+':image-relationship-type','passed':got.get('relationshipType')==R+'/image'})
                        checks.append({'check':want['name']+':image-content-type','passed':(got.get('mediaContentType') or '').startswith('image/')})
                        checks.append({'check':want['name']+':decoded-image','passed':got.get('image')==want.get('image') and got.get('image') is not None})
                        checks.append({'check':want['name']+':media-bytes','passed':got.get('mediaSha256')==want.get('mediaSha256')})
                # Print names can be quote-normalized; preserve scopes and ranges semantically.
                canon=lambda n:(n.get('name'),n.get('localSheetId'),(n.get('text') or '').replace("'",''))
                checks.append({'check':'print-area-and-titles','passed':sorted(map(canon,actual['definedNames']))==sorted(map(canon,expected['definedNames']))})
                result.update(actual=actual,checks=checks,passed=all(c['passed'] for c in checks),restored=str(restored),sha256=sha256(restored));current=restored
            else:result.update(passed=False)
            case['generations'].append(result)
            if not restored.exists():break
        report['cases'].append(case);cases.append((name,source,negative));print(name,[g['passed'] for g in case['generations']],flush=True)
    if args.sdkjs_root:
        import pymupdf as fitz
        sdkjs=args.sdkjs_root.resolve();isolated=work/'pdf-runtime';isolated.mkdir()
        for p in [exe,*runtime.glob('*.dll'),runtime/'native-window-shim.js']:shutil.copyfile(p,isolated/p.name)
        shutil.copytree(runtime/'fonts',isolated/'fonts');shutil.copyfile(runtime/'fonts/AllFonts.js',isolated/'AllFonts.js')
        configured=invoke([sys.executable,str(ROOT/'scripts/configure_native_runtime.py'),'--runtime-bin',str(isolated),'--sdkjs-root',str(sdkjs)],'configure-isolated-native')
        if configured['exitCode']:raise RuntimeError(configured)
        report['sdkjs']={'root':str(sdkjs),'files':{n:sha256(sdkjs/n) for n in ['common/Native/native.js','cell/sdk-all.js','cell/sdk-all-min.js']},'config':str(isolated/'DoctRenderer.config')}
        for name,source,negative in cases:
            if name not in ('shared','remove-all','alpha','tile-1x1','missing-media','missing-rel','corrupt-image'):continue
            folder=work/name;single=folder/'print.xlsx';write(single,single_print(package(source)));pdf=folder/'background.pdf'
            task=ET.Element('TaskQueueDataConvert')
            for key,value in {'m_sFileFrom':str(single),'m_sFileTo':str(pdf),'m_sAllFontsPath':str(isolated/'fonts/AllFonts.js'),'m_sFontDir':str(isolated/'fonts'),'m_sOverrideSdkJsPath':str(sdkjs),'m_bDontSaveAdditional':'true','m_sImageFailurePolicyV1':'strict'}.items():ET.SubElement(task,key).text=value
            param=folder/'pdf.xml';param.write_bytes(serialize(task));result=invoke([str(isolated/'x2t.exe'),str(param)],'xlsx-to-pdf');result.update(name=name,negative=negative,pdf=str(pdf),successfulPDF=pdf.exists() and pdf.stat().st_size>0)
            if result['successfulPDF']:
                doc=fitz.open(pdf);pages=[]
                for index,page in enumerate(doc):
                    pix=page.get_pixmap(matrix=fitz.Matrix(.5,.5),alpha=False);image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    pixel_values=image.get_flattened_data() if hasattr(image,'get_flattened_data') else image.getdata()
                    count=sum(1 for r,g,b in pixel_values if r>g+35 and b>g+25)
                    pages.append({'page':index+1,'magentaPixels':count,'pdfImageObjects':len(page.get_images()),'rasterSha256':hashlib.sha256(pix.samples).hexdigest()})
                    if index<2:pix.save(str(folder/f'pdf-page-{index+1}.png'))
                result.update(pages=pages,pageCount=len(pages),backgroundOnEveryPage=bool(pages) and all(p['magentaPixels']>0 for p in pages))
            result['checks']={'nativeProcessSucceeded':result['exitCode']==0,'backgroundOnEveryPage':result.get('backgroundOnEveryPage') if name!='remove-all' and not negative else None,'missingOrCorruptRejected':(result['exitCode']!=0 and not result['successfulPDF']) if negative else None}
            report['pdf'].append(result);print('PDF',name,result['exitCode'],result.get('pageCount'),result.get('backgroundOnEveryPage'),flush=True)
    if report['pdf']:
        control=next(x for x in report['pdf'] if x['name']=='remove-all')
        control_hashes=[p['rasterSha256'] for p in control.get('pages',[])]
        for item in report['pdf']:
            item['rasterEqualsNoBackgroundControl']=bool(control_hashes) and [p['rasterSha256'] for p in item.get('pages',[])]==control_hashes
    report['runtimeUnchanged']=originals=={p.name:sha256(p) for p in [exe,*runtime.glob('*.dll')]};assert report['runtimeUnchanged']
    report['summary']={'positiveCases':sum(not c['negative'] for c in report['cases']),'positiveCaseFailures':[c['name'] for c in report['cases'] if not c['negative'] and not all(g['passed'] for g in c['generations'])],'negativeCases':sum(c['negative'] for c in report['cases'])}
    receipt=work/'receipt.json';receipt.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps({'receipt':str(receipt),**report['summary']},indent=2))
if __name__=='__main__':main()
