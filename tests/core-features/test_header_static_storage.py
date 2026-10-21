"""Apply the real patches; compare table values and native multi-TU storage."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENC = "core/UnicodeConverter/UnicodeConverter_Encodings.h"
SHAPES = "core/OdfFile/DataTypes/custom_shape_types_convert.h"
XML = ["core/OOXML/Binary/Presentation/XmlWriter.h",
       "core/MsBinaryFile/PptFile/Drawing/XmlStringWriter.h"]
PATCHES = ["023-reduce-header-static-initialization.patch",
           "024-share-shape-and-color-tables.patch",
           "025-share-presentation-namespaces-and-xlsb-types.patch"]


class HeaderStaticStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name)
        for name in PATCHES:
            patch = ROOT / "patches/core" / name
            for relative in re.findall(r"^--- a/(.+)$", patch.read_text(encoding="utf-8"), re.M):
                target = self.tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply",
                            "--ignore-space-change", str(patch)], cwd=self.tree,
                           check=True, capture_output=True)

    def text(self, relative):
        return (self.tree / relative).read_text(encoding="utf-8")

    def test_encoding_values_and_consumers(self):
        before = (ROOT / ENC).read_text(encoding="utf-8")
        after = self.text(ENC)
        pattern = r'm\[\d+\]\s*=\s*"[^"]+";'
        self.assertEqual(re.findall(pattern, before), re.findall(pattern, after))
        self.assertIn("inline const std::map<int, std::string>& GetEncodingsICU()", after)
        self.assertNotIn("static const std::map<int, std::string> mapEncodingsICU", after)
        for source in self.tree.rglob("*.cpp"):
            self.assertNotIn("NSUnicodeConverter::mapEncodingsICU", source.read_text(encoding="utf-8"))

    def test_xml_tokens_preserve_every_value_without_constructors(self):
        for relative in XML:
            original = (ROOT / relative).read_text(encoding="utf-8")
            pairs = re.findall(r'static std::wstring\s+(g_bstr_\w+)\s*=\s*(L"(?:[^"\\]|\\.)*");', original)
            actual = re.findall(r'static const wchar_t (g_bstr_\w+)\[\] = (L"(?:[^"\\]|\\.)*");', self.text(relative))
            self.assertEqual(actual, pairs)
            self.assertGreater(len(actual), 8)
            self.assertNotRegex(self.text(relative), r"static std::wstring\s+g_bstr_")

    def test_path_and_color_only_defined_at_use_site(self):
        for stem, name in [("core/OOXML/DocxFormat/ContentTypes", "c_oContentTypeFileName"),
                           ("core/MsBinaryFile/XlsFile/Converter/xlsx_drawing_context", "standart_color")]:
            self.assertNotIn(name, self.text(stem + ".h"))
            self.assertIn(name, self.text(stem + ".cpp"))
        color = r'const std::wstring standart_color\[56\] = \{.*?\};'
        original = re.search(color, (ROOT / "core/MsBinaryFile/XlsFile/Converter/xlsx_drawing_context.h").read_text(encoding="utf-8"), re.S).group()
        self.assertIn("static " + original, self.text("core/MsBinaryFile/XlsFile/Converter/xlsx_drawing_context.cpp"))

    def test_namespace_and_all_xlsb_descriptors_have_single_definitions(self):
        header = "core/OOXML/PPTXFormat/Namespaces.h"
        source = "core/OOXML/PPTXFormat/Namespaces.cpp"
        self.assertIn("extern Namespaces g_Namespaces;", self.text(header))
        self.assertEqual(self.text(source).count("Namespaces g_Namespaces;"), 1)
        self.assertEqual(self.text(source).replace("    Namespaces g_Namespaces;\n", ""),
                         (ROOT / source).read_text(encoding="utf-8"))
        relative = "core/OOXML/Binary/XlsbFormat/FileTypes_SpreadsheetBin.h"
        before = (ROOT / relative).read_text(encoding="utf-8")
        declarations = re.findall(r"extern const FileType (\w+);", self.text(relative))
        definitions = re.findall(r"const FileType (\w+)\s*(\(.*?\);)", before, re.S)
        self.assertEqual(declarations, [name for name, _ in definitions])
        self.assertEqual(len(declarations), 16)
        source = self.text("core/OOXML/XlsxFormat/FileTypes_Spreadsheet.cpp")
        for name, initializer in definitions:
            self.assertRegex(source, r"const FileType " + name + r"\s*" + re.escape(initializer))

    @unittest.skipUnless(shutil.which("g++"), "native g++ required; also run this case in WSL")
    def test_native_encoding_equality_shared_address_and_cold_include(self):
        header = (self.tree / ENC).as_posix()
        source = self.tree / "main.cpp"
        source.write_text('''#include <cassert>
#include <thread>
#include <vector>
#include "''' + header + '''"
const void* other();
int main(){
 const auto expected=NSUnicodeConverter::create_mapEncodingsICU();
 std::vector<const void*> addresses(16);
 std::vector<std::thread> workers;
 for(int i=0;i<16;++i)workers.emplace_back([&,i]{
  const auto& value=NSUnicodeConverter::GetEncodingsICU();
  assert(value==expected);addresses[i]=&value;
 });
 for(auto& worker:workers)worker.join();
 const auto& value=NSUnicodeConverter::GetEncodingsICU();
 for(auto address:addresses)assert(address==&value);
 assert(other()==&value);
 assert(value.count(-1)==0 && value.count(999999)==0);
 assert(value.at(65001)=="UTF-8" && value.at(936)=="GBK");
 assert(value.at(1252)=="windows-1252" && value.at(54936)=="GB18030");
}
''', encoding="utf-8")
        other = self.tree / "other.cpp"
        other.write_text('#include "' + header + '"\nconst void* other(){return &NSUnicodeConverter::GetEncodingsICU();}\n', encoding="utf-8")
        exe = self.tree / "encoding-test"
        subprocess.run(["g++", "-std=c++11", "-O2", "-pthread", str(source), str(other), "-o", str(exe)], check=True, capture_output=True)
        subprocess.run([str(exe)], check=True)
        cold = self.tree / "cold.cpp"
        cold.write_text('#include "' + header + '"\nint cold(){return 42;}\n', encoding="utf-8")
        obj = self.tree / "cold.o"
        subprocess.run(["g++", "-std=c++11", "-O2", "-c", str(cold), "-o", str(obj)], check=True, capture_output=True)
        symbols = subprocess.run(["nm", "-C", str(obj)], check=True, capture_output=True, text=True).stdout
        self.assertNotIn("mapEncodingsICU", symbols)
        self.assertNotIn("GetEncodingsICU", symbols)
        self.assertNotIn("_GLOBAL__sub_I", symbols)

    @unittest.skipUnless(shutil.which("g++"), "native g++ required; also run this case in WSL")
    def test_native_shape_tables_all_fields_equal_across_translation_units(self):
        original = (ROOT / SHAPES).read_text(encoding="utf-8")
        definitions = re.findall(r"const _shape_converter _OO_OOX_\w+\[\d+\].*?\n\};",
                                 self.text("core/OdfFile/Reader/Format/draw_shapes.cpp"), re.S)
        self.assertEqual(len(definitions), 2)
        body = '''#include <iostream>
void dump(){for(const auto* group:{_OO_OOX_custom_shapes,_OO_OOX_wordart}){
 int count=(group==_OO_OOX_custom_shapes)?205:53;
 for(int i=0;i<count;++i)std::wcout<<group[i].odf_reader<<L'|'<<group[i].oox<<L'|'<<group[i].count_values<<L'|'<<group[i].min<<L'|'<<group[i].max<<L'\\n';}}
'''
        old = self.tree / "old.cpp"
        old.write_text(original + "\n" + body + "int main(){dump();}\n", encoding="utf-8")
        new = self.tree / "new.cpp"
        header = (self.tree / SHAPES).as_posix()
        new.write_text('#include "' + header + '"\n#include <cassert>\n' + "\n".join(definitions) + "\n" + body + '''
const void* otherShapes();
int main(){static_assert(sizeof(_OO_OOX_custom_shapes)/sizeof(_shape_converter)==205,"shape count");
static_assert(sizeof(_OO_OOX_wordart)/sizeof(_shape_converter)==53,"wordart count");
assert(otherShapes()==_OO_OOX_custom_shapes);dump();}
''', encoding="utf-8")
        other = self.tree / "shapes-other.cpp"
        other.write_text('#include "' + header + '"\nconst void* otherShapes(){return _OO_OOX_custom_shapes;}\n', encoding="utf-8")
        outputs = []
        for source, extra in [(old, []), (new, [str(other)])]:
            exe = source.with_suffix("")
            compiled = subprocess.run(["g++", "-std=c++11", "-O2", str(source), *extra, "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            outputs.append(subprocess.run([str(exe)], check=True, capture_output=True).stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(len(outputs[1].splitlines()), 258)


if __name__ == "__main__":
    unittest.main()
