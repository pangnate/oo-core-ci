# X2T 构建验证记录

## 当前状态

旧基线的三平台 X2T 编译验证均已通过；当前 10.0 基线尚待重新编译验证。构建使用仓库固定的 ONLYOFFICE Core/build_tools 基线、vendor 第三方输入和对应架构的预编译 runtime。

当前源码快照对应官方 `ONLYOFFICE/core@ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`；三平台 runtime 从本地运行环境 `bin` 目录提取并以归档 SHA256 固定。旧基线结果不作为新基线编译通过的依据。

## CI 覆盖范围

- Linux：检查 `x2t` 存在、ELF 架构正确；amd64 使用 `ldd` 确认动态依赖没有 `not found`，arm64 检查 `NEEDED` 条目。
- Windows：使用 `dumpbin` 检查 PE x64 架构和 DLL 依赖列表。
- 三个平台：分别打包可执行文件并生成 SHA256 校验文件。

编译及上述检查通过，证明当前构建输入能够生成并链接目标架构的 X2T。workflow 当前没有运行实际文档转换，也没有验证 `distribute` round-trip；这些属于功能测试，需在对应功能改动时单独执行。

## 失败时的定位

1. `scripts/verify_vendor.py` 失败：检查 LFS 文件是否已恢复、`vendor/checksums.json` 和归档名是否匹配 `vendor/detected-deps.json`。
2. 第三方库构建失败：检查当前 Core/build_tools 基线检测出的 Boost、ICU 版本及目标平台工具链/sysroot。
3. X2T 静态库或 CryptoPP 链接失败：检查 `core/X2tConverter/build/Qt/X2tSLN.pri` 的依赖闭包和 `scripts/patch_x2t_sln.py` 补丁。
4. Linux 链接找不到 `.so`：检查对应架构 runtime 内容、`core/build/lib/<platform>` 目录和链接器报错中的直接/间接依赖。
5. Windows 找不到 `.lib` 或符号：检查 `dumpbin /exports` 输出、生成的 import library；必要时将该 DLL 对应的原始 `.lib` 放入匹配基线的 runtime 输入。
6. 架构/依赖检查失败：保留完整的最终链接命令及 `file`、`readelf`、`ldd` 或 `dumpbin` 输出后再定位。

## 后续功能验证

对 `OOXML/Binary`、`BinDocument` 等静态格式层的改动，编译通过后还要使用真实样例执行转换，并检查输出内容。若验证 `distribute`，建议准备含 `<w:jc w:val="distribute"/>` 的 DOCX，执行 DOCX → Editor.bin → DOCX 往返，并确认结果没有退化为 `both`。该功能验证与当前三平台编译验证分开记录。
