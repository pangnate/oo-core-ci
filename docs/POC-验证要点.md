# POC 验证要点

第一次 GitHub Actions 的目的不是证明 `distribute` 已实现，而是先证明 **X2T core-only 构建闭包**成立。

按失败位置判断：

1. `Build only Boost and ICU` 失败：第三方 source/sysroot/toolchain 准备问题。
2. `Build X2T` 找不到静态库：检查 `X2tSLN.pri` 项目闭包和 CryptoPPLib patch。
3. Linux 最终链接找不到 `.so`：检查你提供的同版本 runtime，以及 `core/build/lib/<platform>`。
4. Windows 找不到 `xxx.lib`：自动 DLL→LIB 未覆盖该 DLL 的导出形式；把该 DLL 对应的原始 import `.lib` 放进 Windows runtime 包即可。
5. 架构验证成功后，再提交 `distribute` C++ 修改验证功能。

## 需要保存的失败日志

- Linux：完整 qmake command、最终 x2t link command、`file/readelf/ldd`。
- Windows：最终 `link.exe` command、缺失 symbol 名称、对应 DLL 的 `dumpbin /exports`。

这些日志足够继续把 POC 收口到稳定构建。
