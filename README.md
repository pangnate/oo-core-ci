# ONLYOFFICE X2T Core-only 构建项目

这个仓库用于**只编译 X2T 及其必要静态格式库**，产出 Linux amd64、Linux arm64、Windows amd64 三个平台的 `x2t`，不构建 ONLYOFFICE Server / SDKJS / Web Apps / 完整 Core runtime。当前已同步 10.0 源码和三平台 runtime；新基线尚待重新编译验证。

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
  --core-ref ed63e94de814ff1d4ea28cddfaba6939bc9df9ed \
  --build-tools-ref a9f9895b172b09595abcafe85d56fab163f9ecb7 \
  --linux-amd64-libs ./native-bin/linux-amd64/bin \
  --linux-arm64-libs ./native-bin/linux-arm64/bin \
  --windows-amd64-dlls 'D:\ONLYOFFICE\onlyoffice-x2t-ci\native-bin\windows\bin'
```

- core  ed63e94de814ff1d4ea28cddfaba6939bc9df9ed
- build_tools  a9f9895b172b09595abcafe85d56fab163f9ecb7

脚本会：

1. 下载并展开 `ONLYOFFICE/core` 到 `core/`。
2. 下载并展开 `ONLYOFFICE/build_tools` 到 `build_tools/`。
3. 根据 `vendor/detected-deps.json` 下载与选定 Core/build_tools 基线匹配的 Boost、ICU、Brotli、Linux Qt、Ubuntu 16 sysroot 和 ONLYOFFICE portable Python3。当前锁定输入为 Boost 1.58.0、ICU 74.2、Brotli `a47d7475063eb223c87632eed806c0070e70da29`、Linux Qt 5.9.9。
4. 将你本地的 Linux `*.so*` 打成 vendor runtime 包。
5. 将 Windows `*.dll` 打成 vendor runtime 包。
6. 自动给 `X2tSLN.pri` 补 `CryptoPPLib` 依赖，并给 Linux x2t 增加 `rpath-link`。

源码快照保存在 `core/` 和 `build_tools/`；构建所需的大文件保存在 `vendor/` 并由 Git LFS 管理。CI 从仓库/LFS 获取这些固定输入，不执行 `scripts/download.py` 的在线 bootstrap 下载。Linux workflow 仍通过 apt 安装 runner 上的构建工具。

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

## 当前构建状态与 GitHub Actions 流程

旧基线的三平台编译曾通过；当前 10.0 基线尚待重新运行 CI。workflow 可通过 `workflow_dispatch` 选择 `all`、`linux` 或 `windows`，各平台分别上传带 SHA256 文件的构建产物。

### Linux

Ubuntu 24.04 x64 host：

1. 从仓库 LFS 恢复第三方 archive。
2. `scripts/prepare.py` 展开 Qt 5.9.9、Ubuntu 16 sysroot、第三方源码及预编译 Linux runtime 库。
3. 使用固定版本的 `build_tools` 分别配置 `linux_64` 和 `linux_arm64` 构建环境。
4. 通过 ONLYOFFICE 构建模块为目标架构编译 Boost 和 ICU。
5. 使用 `X2tSLN.pro` 编译 X2T 静态依赖闭包；amd64 原生构建，arm64 使用官方交叉工具链和 sysroot。
6. 使用 `file`、`readelf` 检查架构；amd64 额外使用 `ldd` 检查动态依赖。

### Windows

`windows-2022` runner：

1. 使用 VS2022 Host + v142 (14.29) toolset。
2. 使用 Qt 5.15.2 `msvc2019_64` qmake 和 v142 编译工具集。
3. 展开 Boost / ICU / Brotli 源码并编译 Boost、ICU。
4. 从 Windows runtime DLL 生成缺少的 import libraries。
5. 编译 X2T 静态依赖闭包并链接 `x2t.exe`。
6. 使用 `dumpbin` 检查 x64 PE 架构和 DLL dependencies。

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

CI 对缺少 import library 的 DLL 使用 `dumpbin /exports` 生成 `.def`，再用 `lib.exe` 生成 import library；该流程已通过当前基线的 Windows 编译验证。如果未来 DLL 存在必须标记为 `DATA` 的导出、ordinal-only 导出或其他特殊 PE 导出，自动生成可能无法覆盖，届时应提供该 DLL 对应的原始 `.lib`。这不会影响 Linux 路线。

## 编译验证与功能验证的边界

旧基线三平台编译已通过；升级至 10.0 后，需要重新验证 Core/build_tools、第三方依赖和预编译 runtime 能否完成链接。当前 workflow 的自动检查覆盖产物架构和动态依赖；它没有执行文档转换 fixture 或 `distribute` round-trip。因此，功能改动仍需通过实际转换输入/输出验证，不能仅凭编译成功判断格式行为正确。

## 10.0 本地输入同步（2026-10-17）

```powershell
python scripts/sync_local_inputs.py --core D:\workspace\only9-master\core --linux-amd64 D:\workspace\only9-merge\docker-tools\amd64\bin --linux-arm64 D:\workspace\only9-merge\docker-tools\arm64\bin --windows-amd64 D:\docservice\idp-all\idp-office\native\runtime\win-x64\bin
python scripts/verify_vendor.py --platform all
```

Core 来自干净的 `v10.0.0.169-2-ged63e94de8` 工作区；保留本仓库公司名，重新应用 CryptoPP 和 Linux rpath-link 补丁。build_tools 沿用现有固定提交，尚未验证与新 Core 的构建兼容性。Windows 输入元数据版本为 `10.0.0.169`；Linux 使用指定 docker-tools 的两种架构 bin。

同步脚本仅将构建需要的 SO/DLL 打入 vendor runtime，保持现有 CI 输入布局；不将来源中的 x2t、字体缓存或其他应用资源打进链接 SDK。生成的可执行文件需部署至对应版本的完整运行环境。来源、Core 树摘要及 runtime SHA256 记录在 `ci/baseline.json` 和 `vendor/checksums.json`。
