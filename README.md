# ONLYOFFICE X2T Core-only CI 验证项目

这个仓库用于验证：**只编译 X2T 及其必要静态格式库**，产出 Linux amd64、Linux arm64、Windows amd64 三个平台的 `x2t`，不构建 ONLYOFFICE Server / SDKJS / Web Apps / 完整 Core runtime。

## 你需要准备

你已经有的同版本运行库：

- Linux amd64：包含 `graphics/kernel/PdfFile/doctrenderer/...` 的 `*.so*` 目录。
- Linux arm64：对应的 `*.so*` 目录。
- Windows amd64：对应的 `*.dll` 目录。项目会用 `dumpbin + lib.exe` 尝试自动生成链接所需的 import `.lib`。

**这些运行库必须和你选择的 Core 基线一致。**

## 第一步：本地下载全部源码/第三方包

Python 3：

```bash
python scripts/download.py \
  --core-ref <你当前 ONLYOFFICE core 的 tag/commit> \
  --build-tools-ref <与该版本匹配的 build_tools tag/commit> \
  --linux-amd64-libs /path/to/linux-amd64/FileConverter-bin \
  --linux-arm64-libs /path/to/linux-arm64/FileConverter-bin \
  --windows-amd64-dlls 'D:\path\to\windows\FileConverter\bin'
```

```bash
python scripts/download.py \
  --core-ref 3250a848ee4ef20c2fb8c38dc86350ec579124b8 \
  --build-tools-ref a9f9895b172b09595abcafe85d56fab163f9ecb7 \
  --linux-amd64-libs ./native-bin/linux-amd64/bin \
  --linux-arm64-libs ./native-bin/linux-arm64/bin \
  --windows-amd64-dlls 'D:\ONLYOFFICE\onlyoffice-x2t-ci\native-bin\windows\bin'
```

- core  3250a848ee4ef20c2fb8c38dc86350ec579124b8
- build_tools  a9f9895b172b09595abcafe85d56fab163f9ecb7

脚本会：

1. 下载并展开 `ONLYOFFICE/core` 到 `core/`。
2. 下载并展开 `ONLYOFFICE/build_tools` 到 `build_tools/`。
3. 下载 Boost 1.72、ICU 74.2、Brotli 固定 commit、Linux Qt 5.9.9、Ubuntu16 amd64/arm64 sysroot、ONLYOFFICE portable Python3。
4. 将你本地的 Linux `*.so*` 打成 vendor runtime 包。
5. 将 Windows `*.dll` 打成 vendor runtime 包。
6. 自动给 `X2tSLN.pri` 补 `CryptoPPLib` 依赖，并给 Linux x2t 增加 `rpath-link`。

所有需要 GitHub Actions 使用的大文件都放在 `vendor/`，由 Git LFS 管理；CI 不再从第三方网站下载。

## 第二步：在 Windows 本地准备 Qt 5.15.2

在 Windows PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_windows_qt.ps1
```

这一步只执行一次，生成：

```text
vendor/archives/qt_5.15.2_msvc2019_64.7z
```

## 第三步：确认 vendor 完整

```bash
python scripts/verify_vendor.py --platform all
```

## 第四步：推送 GitHub

Git LFS 必须启用：

```bash
git lfs install
git init
git add .
git commit -m "x2t core-only build poc"
git branch -M main
git remote add origin https://github.com/pangnate/onlyoffice-x2t-ci.git
git push -u origin main
```

> 如果你的 GitHub LFS 配额不足，把 `vendor/archives` / `vendor/runtime` 放到自己的制品库，然后把 workflow 的获取方式改成下载制品即可；项目本身的构建逻辑不变。

## GitHub Actions 实际做什么

### Linux

Ubuntu 24.04 x64 host：

1. 从仓库 LFS 恢复第三方 archive。
2. 离线展开 Qt 5.9.9 和 Ubuntu16 sysroot。
3. 离线展开 Boost / ICU / Brotli 源码。
4. 用 ONLYOFFICE 原构建模块只编 Boost + ICU。
5. 用 `X2tSLN.pro` 编译 X2T 静态依赖闭包。
6. 原生生成 `linux_64/x2t`。
7. 通过官方 aarch64 cross toolchain/sysroot 生成 `linux_arm64/x2t`。
8. `file/readelf/ldd` 验证产物。

### Windows

`windows-2022` runner：

1. 使用 VS2022 Host + v142 (14.29) toolset。
2. 使用 Qt 5.15.2 `msvc2019_64` qmake。
3. 离线展开 Boost / ICU / Brotli 源码。
4. 从你的 Windows runtime DLL 自动生成 `graphics.lib/kernel.lib/...` import libraries。
5. 编译 X2T 静态依赖闭包并链接 `x2t.exe`。
6. `dumpbin` 验证 x64 PE 和 DLL dependencies。

## 重点边界

本项目适合改动：

```text
OOXML/Binary
BinDocument
Docx/PPTX/XLS/ODF/RTF 等 X2T 静态格式层
X2tConverter
```

如果你修改：

```text
graphics
kernel
PdfFile
doctrenderer
UnicodeConverter
```

那么现有 runtime `.so/.dll` 就不再能视为固定 Build SDK，需要同步重编对应动态库。

## Windows DLL -> import LIB 的说明

CI 使用 `dumpbin /exports` 生成 `.def`，再用 `lib.exe` 生成 import library。这对普通导出函数是可行的，也是本 POC 要验证的一部分。如果某个 ONLYOFFICE DLL 存在必须标记为 `DATA` 的导出、ordinal-only 导出或其他特殊 PE 导出，链接可能在该 DLL 上失败；届时该 DLL 需要提供原始 `.lib`，或者把这一项动态库纳入 Windows bootstrap 编译。这不会影响 Linux 路线。

## 第一次 POC 推荐

先不要应用 `distribute` 修改，先让三平台把原始同版本 X2T 编过一次。三平台成功后，再修改：

```text
core/OOXML/Binary/Document/BinWriter/BinaryWriterD.cpp
core/OOXML/Binary/Document/BinReader/BinaryReaderD.cpp
core/OOXML/Binary/Document/BinWriter/BinReaderWriterDefines.h
```

这样如果失败，可以明确区分“构建系统问题”和“功能补丁问题”。
