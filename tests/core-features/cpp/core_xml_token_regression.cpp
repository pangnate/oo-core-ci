// Link against the real XmlWriter.cpp and StringBuilder.cpp, before and after 023.
#include "OOXML/Binary/Presentation/XmlWriter.h"
#include "MsBinaryFile/PptFile/Drawing/XmlStringWriter.h"
#include <cassert>
#include <iostream>

struct Item {
    void toXmlWriter(NSBinPptxRW::CXmlWriter* writer) const {
        writer->WriteNodeBegin(L"i");
        writer->WriteBool(true);
        writer->WriteNodeEnd(L"i");
    }
};

int main() {
    NSBinPptxRW::CXmlWriter writer;
    writer.WriteNodeBegin(L"r", true);
    writer.WriteAttribute(L"k", L"v");
    writer.WriteAttribute(L"on", true);
    writer.EndAttributes();
    writer.WriteArray(L"items", std::vector<Item>(2));
    writer.WriteNodeBegin(L"off");
    writer.WriteBool(false);
    writer.WriteNodeEnd(L"off");
    writer.WriteNodeBegin(L"empty", true);
    writer.WriteNodeEnd(L"empty", true);
    writer.WriteNodeEnd(L"r");
    const std::wstring expected = L"<r k=\"v\" on=\"1\"><items><i>1</i><i>1</i></items><off>0</off><empty/></r>";
    assert(writer.GetXmlString() == expected);
    NSStringUtils::CStringBuilder tokens;
    tokens.WriteString(PPT::g_bstr_nodeopen);
    tokens.WriteString(PPT::g_bstr_boolean_true);
    tokens.WriteString(PPT::g_bstr_nodeclose);
    tokens.WriteString(PPT::g_bstr_nodeopen_slash);
    tokens.WriteString(PPT::g_bstr_boolean_false);
    tokens.WriteString(PPT::g_bstr_nodeclose_slash);
    assert(tokens.GetData() == L"<true></false/>");
    std::wcout << writer.GetXmlString() << L'\n' << tokens.GetData() << L'\n';
}
