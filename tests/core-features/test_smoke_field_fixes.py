"""Patch replay and native method checks; not a full X2T roundtrip."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATHS = ("core/OOXML/DocxFormat/Settings/Settings.cpp", "core/OOXML/PPTXFormat/Logic/TextSpacing.cpp", "core/OOXML/PPTXFormat/Logic/TextParagraphPr.cpp")
FIXES = ("020-word-preserve-protection-algorithm.patch", "021-slide-preserve-spacing-namespace.patch")

def replay(destination: Path, fixes: bool) -> None:
    for relative in PATHS:
        path=destination/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/relative).read_bytes())
    series=json.loads((ROOT/"patches/core/series.json").read_text(encoding="utf-8"))
    for entry in series["patches"]:
        if not fixes and Path(entry["path"]).name in FIXES: continue
        args=["git","-c","core.autocrlf=false","apply","--ignore-space-change"]
        args += ["--include="+p for p in PATHS]
        result=subprocess.run(args+[str(ROOT/entry["path"])],cwd=destination,capture_output=True,text=True)
        if result.returncode: raise AssertionError(entry["path"]+": "+result.stderr)

def method(text: str, signature: str) -> str:
    start=text.index(signature);brace=text.index("{",start);depth=1;end=brace+1
    while depth:
        if text[end]=="{":depth+=1
        elif text[end]=="}":depth-=1
        end+=1
    return text[start:end]+"\n"

MAIN = r"""
#include <iostream>
int check(bool condition){if(!condition){std::cerr<<"regression assertion failed\n";return 1;}return 0;}
template<class T>int protection(){
 for(int present=0;present<2;++present)for(int sid=0;sid<2;++sid)for(int provider=0;provider<2;++provider){
  T p;if(present)p.m_oAlgorithmName.set(L"SHA-256");if(sid)p.m_oCryptAlgorithmSid.set(L"12");if(provider)p.m_oCryptProviderType.set(L"rsaAES");
  p.m_sHashValue.set(L"hash-data");p.m_sSaltValue.set(L"salt-data");p.m_oSpinCount.set(L"1000");
  auto xml=p.toXML();auto first=xml.find(L"w:algorithmName=\"SHA-256\"");
  if(check((first!=std::wstring::npos)==bool(present)))return 1;
  if(present&&check(xml.find(L"w:algorithmName=",first+1)==std::wstring::npos))return 1;
  if(sid&&check(xml.find(L"w:cryptAlgorithmSid=\"12\"")!=std::wstring::npos))return 1;
  if(provider&&check(xml.find(L"w:cryptProviderType=\"rsaAES\"")!=std::wstring::npos))return 1;
  if(check(xml.find((sid||provider)?L"w:hash=\"hash-data\"":L"w:hashValue=\"hash-data\"")!=std::wstring::npos))return 1;
 }return 0;
}
XmlUtils::CXmlNode node(std::wstring prefix,bool pct,int value){
 XmlUtils::CXmlNode parent;parent.valid=true;parent.name=prefix+L"lnSpc";
 XmlUtils::CXmlNode child;child.valid=true;child.hasVal=true;child.name=prefix+(pct?L"spcPct":L"spcPts");child.val=std::to_wstring(value);parent.children.push_back(child);return parent;
}
int spacing(){
 for(auto prefix:{L"a:",L"draw:",L""})for(bool pct:{false,true})for(bool stream:{false,true}){
  TextSpacing value;auto n=node(prefix,pct,pct?75000:1800);
  if(stream){XmlUtils::CXmlLiteReader reader(n);value.fromXML(reader);}else value.fromXML(n);
  if(check(pct?(value.spcPct.is_init()&&*value.spcPct==75000&&!value.spcPts.is_init()):(value.spcPts.is_init()&&*value.spcPts==1800&&!value.spcPct.is_init())))return 1;
  NSBinPptxRW::CBinaryFileWriter writer;value.toPPTY(&writer);TextSpacing restored;
  // Deliberately prepopulate the opposite unit to exercise object reuse.
  if(pct)restored.spcPts=1;else restored.spcPct=1;
  NSBinPptxRW::CBinaryFileReader reader(writer.data);restored.m_name=L"a:lnSpc";restored.fromPPTY(&reader);
  if(check(pct?(restored.spcPct.is_init()&&*restored.spcPct==75000&&!restored.spcPts.is_init()):(restored.spcPts.is_init()&&*restored.spcPts==1800&&!restored.spcPct.is_init())))return 1;
  NSBinPptxRW::CXmlWriter xml;restored.toXmlWriter(&xml);
  if(check(xml.xml.find(pct?L"a:spcPct val=\"75000\"":L"a:spcPts val=\"1800\"")!=std::wstring::npos))return 1;
  auto opposite=node(prefix,!pct,!pct?75000:1800);
  if(stream){XmlUtils::CXmlLiteReader r(opposite);value.fromXML(r);}else value.fromXML(opposite);
  if(check(pct?(!value.spcPct.is_init()&&value.spcPts.is_init()):(!value.spcPts.is_init()&&value.spcPct.is_init())))return 1;
  XmlUtils::CXmlNode empty;empty.valid=true;empty.name=L"a:lnSpc";
  if(stream){XmlUtils::CXmlLiteReader r(empty);value.fromXML(r);}else value.fromXML(empty);
  if(check(!value.spcPct.is_init()&&!value.spcPts.is_init()))return 1;
 }
 for(int v:{0,1800,158400}){TextSpacing x;auto n=node(L"other:",false,v);x.fromXML(n);if(check(x.spcPts.is_init()&&*x.spcPts==v))return 1;}
 return 0;
}
int main(int argc,char**argv){return argc>1&&std::string(argv[1])=="word"?(protection<CDocProtect>()||protection<CWriteProtection>()):spacing();}
"""

def probe_source(stage: Path) -> str:
    settings=(stage/PATHS[0]).read_text(encoding="utf-8")
    spacing=(stage/PATHS[1]).read_text(encoding="utf-8")
    parts=[(ROOT/"tests/core-features/cpp/smoke_fields_support.h").read_text(encoding="utf-8")]
    for klass in ("CDocProtect","CWriteProtection"):parts.append(method(settings,"std::wstring "+klass+"::toXML() const"))
    for signature in ("void TextSpacing::fromXML(XmlUtils::CXmlLiteReader& oReader)","void TextSpacing::ReadAttributes(XmlUtils::CXmlLiteReader& oReader, nullable_int & val)","void TextSpacing::fromXML(XmlUtils::CXmlNode& node)","void TextSpacing::toXmlWriter(NSBinPptxRW::CXmlWriter* pWriter) const","void TextSpacing::toPPTY(NSBinPptxRW::CBinaryFileWriter* pWriter) const","void TextSpacing::fromPPTY(NSBinPptxRW::CBinaryFileReader* pReader)","void TextSpacing::Normalize()"):
        parts.append(method(spacing,signature))
    return "\n".join(parts)+MAIN

class SmokeFieldFixTests(unittest.TestCase):
    def test_active_patch_replay_keeps_earlier_protection_and_slide_patches(self):
        with tempfile.TemporaryDirectory() as temp:
            stage=Path(temp);replay(stage,True)
            settings=(stage/PATHS[0]).read_text(encoding="utf-8")
            self.assertIn('XmlMacroReadAttributeBase(oNode, L"w:algorithmName", m_oAlgorithmName);',settings)
            paragraph=(stage/PATHS[2]).read_text(encoding="utf-8")
            self.assertIn('localName',paragraph)
            self.assertIn('eaLnBrk',paragraph)
            self.assertIn('hangingPunct',paragraph)
            self.assertIn('latinLnBrk',paragraph)

    @unittest.skipUnless(shutil.which("g++"),"native method probe needs g++ (run under WSL on Windows)")
    def test_native_methods_reproduce_before_and_pass_after(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for fixed in (False,True):
                stage=root/str(fixed);stage.mkdir();replay(stage,fixed)
                source=stage/"probe.cpp";source.write_text(probe_source(stage),encoding="utf-8")
                binary=stage/"probe"
                compiled=subprocess.run(["g++","-std=c++11","-O0",str(source),"-o",str(binary)],capture_output=True,text=True)
                self.assertEqual(compiled.returncode,0,compiled.stderr)
                for case in ("word","slide"):
                    ran=subprocess.run([str(binary),case],capture_output=True,text=True)
                    self.assertEqual(ran.returncode==0,fixed,(fixed,case,ran.stderr))

if __name__=="__main__":unittest.main()
