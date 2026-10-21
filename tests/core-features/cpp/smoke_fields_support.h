// Test doubles for extracted production method bodies; not a full Core codec.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
using BYTE = unsigned char;
using LONG = int32_t;
struct nullable_int {
 bool set=false; int value=0;
 void reset(){set=false;} bool IsInit()const{return set;} bool is_init()const{return set;}
 nullable_int& operator=(int v){set=true;value=v;return *this;}
 nullable_int& operator=(const std::wstring& v){return *this=std::stoi(v);}
 int operator*()const{return value;} int get()const{return value;}
 int get_value_or(int v)const{return set?value:v;}
 void normalize(int low,int high){if(set)value=std::max(low,std::min(value,high));}
};
namespace XmlUtils {
inline std::wstring GetNameNoNS(const std::wstring& name){auto i=name.find(L':');return i==std::wstring::npos?name:name.substr(i+1);}
struct CXmlNode {
 std::wstring name,val; bool valid=false,hasVal=false; std::vector<CXmlNode> children;
 std::wstring GetName()const{return name;}
 bool GetAttributeIfExist(const std::wstring&,std::wstring& out){if(!valid||!hasVal)return false;out=val;return true;}
 CXmlNode ReadNode(const std::wstring& n){for(auto c:children)if(c.name==n)return c;return {};}
 CXmlNode ReadNodeNoNS(const std::wstring& n){for(auto c:children)if(GetNameNoNS(c.name)==n)return c;return {};}
};
struct CXmlLiteReader {
 CXmlNode node; int index=-1; bool attribute=false;
 CXmlLiteReader(CXmlNode n):node(n){}
 CXmlNode current()const{return index<0?node:node.children[index];}
 std::wstring GetName()const{return attribute?L"val":current().name;}
 std::wstring GetText()const{return current().val;}
 bool IsEmptyNode()const{return current().children.empty();}
 int GetDepth()const{return index<0?0:1;}
 bool ReadNextSiblingNode(int){attribute=false;return ++index<(int)node.children.size();}
 int GetAttributesCount()const{return current().hasVal?1:0;}
 bool MoveToFirstAttribute(){attribute=true;return current().hasVal;}
 bool MoveToNextAttribute(){return false;}
 void MoveToElement(){attribute=false;}
};
}
#define XmlMacroReadAttributeBase(node,name,value) { std::wstring sAttr; if(node.GetAttributeIfExist(name,sAttr))value=sAttr; }
#define WritingElement_ReadAttributes_Start(Reader) if(Reader.GetAttributesCount()<=0)return;if(!Reader.MoveToFirstAttribute())return;std::wstring wsName=Reader.GetName();while(!wsName.empty()){
#define WritingElement_ReadAttributes_ReadSingle(Reader,AttrName,Value) if(AttrName==wsName){Value=Reader.GetText();break;}
#define WritingElement_ReadAttributes_End(Reader) if(!Reader.MoveToNextAttribute())break;wsName=Reader.GetName();}Reader.MoveToElement();
#define _T(value) L##value
namespace NSBinPptxRW {
const BYTE g_nodeAttributeStart=250,g_nodeAttributeEnd=251;
struct CXmlWriter {
 std::wstring xml;
 void StartNode(const std::wstring& n){xml+=L"<"+n;}
 void EndAttributes(){xml+=L">";} void StartAttributes(){}
 void WriteAttribute(const std::wstring& n,int v){xml+=L" "+n+L"=\""+std::to_wstring(v)+L"\"";}
 void EndNode(const std::wstring& n){xml+=L"</"+n+L">";}
};
struct CBinaryFileWriter {
 std::vector<BYTE> data;
 void WriteBYTE(BYTE b){data.push_back(b);}
 void WriteInt2(int type,const nullable_int& n){if(n.set){WriteBYTE(type);for(int i=0;i<4;++i)WriteBYTE((uint32_t)n.value>>(8*i));}}
};
struct CBinaryFileReader {
 std::vector<BYTE> data;int pos=0;
 CBinaryFileReader(std::vector<BYTE> payload){int len=payload.size();for(int i=0;i<4;++i)data.push_back((uint32_t)len>>(8*i));data.insert(data.end(),payload.begin(),payload.end());}
 int GetPos()const{return pos;} LONG GetLong(){uint32_t v=0;for(int i=0;i<4;++i)v|=(uint32_t)data.at(pos++)<<(8*i);return (int32_t)v;}
 int GetRecordSize(){return GetLong();} void Skip(int n){pos+=n;} BYTE GetUChar_TypeNode(){return data.at(pos++);}void Seek(int p){pos=p;}
};
}
struct TextSpacing {
 nullable_int spcPct,spcPts;std::wstring m_name;
 void fromXML(XmlUtils::CXmlLiteReader&);void fromXML(XmlUtils::CXmlNode&);
 void ReadAttributes(XmlUtils::CXmlLiteReader&,nullable_int&);
 void toXmlWriter(NSBinPptxRW::CXmlWriter*)const;void toPPTY(NSBinPptxRW::CBinaryFileWriter*)const;
 void fromPPTY(NSBinPptxRW::CBinaryFileReader*);void Normalize();int GetVal()const;
};
struct Field {
 bool initialized=false;std::wstring value;
 bool IsInit()const{return initialized;}const Field* operator->()const{return this;}
 std::wstring ToString()const{return value;}
 std::wstring ToAttribute(const std::wstring& name)const{return initialized?name+L"=\""+value+L"\" ":L"";}
 void set(const std::wstring& v){value=v;initialized=true;}
};
#define ComplexTypes_WriteAttribute(start,value) if(value.IsInit()){sResult+=start+value->ToString()+L"\" ";}
struct ProtectionFields {
 Field m_oAlgorithmName,m_oCryptProviderType,m_oCryptAlgorithmSid,m_oEdit,m_oFormatting,m_oEnforcment,m_oRecommended;
 Field m_oAlgIdExt,m_oAlgIdExtSource,m_oCryptAlgorithmClass,m_oCryptAlgorithmType,m_oCryptProvider,m_oCryptProviderTypeExt,m_oCryptProviderTypeExtSource,m_oSpinCount,m_sHashValue,m_sSaltValue;
};
struct CDocProtect:ProtectionFields{std::wstring toXML()const;};
struct CWriteProtection:ProtectionFields{std::wstring toXML()const;};
