// Build twice against real Core sources. Compare output; enable shared-address
// assertions only for the patched tree. Compile this file in a second TU with
// STATIC_STORAGE_OTHER_TU to exercise the extern definitions.
#include "OOXML/PPTXFormat/Namespaces.h"
#include "OOXML/Binary/XlsbFormat/FileTypes_SpreadsheetBin.h"
#include <cassert>
#include <iostream>

#ifdef STATIC_STORAGE_OTHER_TU
const void* otherNamespaces() { return &PPTX::g_Namespaces; }
const void* otherWorkbookType() { return &OOX::SpreadsheetBin::FileTypes::WorkbookBin; }
#else
const void* otherNamespaces();
const void* otherWorkbookType();
int main() {
#ifdef CHECK_SHARED_STATIC_STORAGE
    assert(otherNamespaces() == &PPTX::g_Namespaces);
    assert(otherWorkbookType() == &OOX::SpreadsheetBin::FileTypes::WorkbookBin);
#endif
    const auto& n = PPTX::g_Namespaces;
    const PPTX::Namespace* namespaces[] = {
        &n.a, &n.b, &n.cdr, &n.cp, &n.cup, &n.dc, &n.dchrt, &n.dcmitype,
        &n.dcterms, &n.ddgrm, &n.dgm, &n.dlckcnv, &n.dpct, &n.ds, &n.m,
        &n.o, &n.p, &n.pic, &n.pvml, &n.r, &n.s, &n.sl, &n.v, &n.ve,
        &n.vp, &n.vt, &n.w, &n.w10, &n.wne, &n.wp, &n.x, &n.xdr,
        &n.xmlns, &n.xsd, &n.xsi, &n.p14, &n.p15
    };
    for (const auto* entry : namespaces)
        std::wcout << entry->m_strName << L'|' << entry->m_strLink << L'\n';
    using namespace OOX::SpreadsheetBin::FileTypes;
    const OOX::FileType* types[] = {
        &WorkbookBin, &SharedStringsBin, &StylesBin, &WorksheetBin, &ChartsheetsBin,
        &TableBin, &QueryTableBin, &ConnectionsBin, &CommentsBin, &SlicerCacheBin,
        &SlicerBin, &ExternalLinksBin, &PivotTableBin, &PivotCacheDefinitionBin,
        &PivotCacheRecordsBin, &MetadataBin
    };
    for (const auto* entry : types)
        std::wcout << entry->DefaultDirectory().GetPath() << L'|'
                   << entry->DefaultFileName().GetPath() << L'|'
                   << entry->OverrideType() << L'|' << entry->RelationType() << L'|'
                   << entry->EnumerateType() << L'|' << entry->Enumerated() << L'|'
                   << entry->EnumeratedGlobal() << L'\n';
}
#endif
