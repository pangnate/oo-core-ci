# ONLYOFFICE X2T Core-only 构建项目

这个仓库原用于**只编译 X2T 及其必要静态格式库**，不构建 ONLYOFFICE Server / SDKJS / Web Apps / 完整 Core runtime。当前已同步 Core 10 源码。`native-bin/windows/bin`是9.4.0.129；vendor Windows runtime来自另一目录，PE版本标记10.0.0.169但同步来源注明metadata-only-reconciliation，必须先完成真实加载/转换验证，不能只凭metadata视为匹配。本轮Windows POC将先验收该候选，必要时再构建完整DLL闭包。

Word、Sheet、Slide的Core功能改造已有[46张Luna执行卡及2个汇总项](./Core三端功能改造_Luna开发任务卡_2026-10-19.md)，唯一领取/状态入口为[执行总表](./Core三端功能改造_执行总表_2026-10-19.md)。当前按用户本地Windows环境完成Core产物POC，不等待Linux或产品新SDKJS；后续新JS集成、Linux发布分阶段保留。任务补齐Windows开发构建、SDK/V8、匹配Core 10的完整基线DLL、缓存、指标与单平台容量，已知大卡已拆子卡。逐卡执行已开始，CORE-00完成。

本文所有构建命令从仓库根目录执行。Windows/Linux 构建缓存、按 CPU 核数并行和性能采样的当前实现见[构建流程优化方案](./构建流程优化方案_2026-10-20.md)。

## 你需要准备

你已经有的同版本运行库：

- Linux amd64：包含 `graphics/kernel/PdfFile/doctrenderer/...` 的 `*.so*` 目录。
- Linux arm64：对应的 `*.so*` 目录。
- Windows amd64：对应的 `*.dll` 目录。项目会用 `dumpbin + lib.exe` 尝试自动生成链接所需的 import `.lib`。

**这些运行库必须和你选择的 Core 基线一致。**

## 第一步：本地下载全部源码/第三方包

先复制 `local-input/runtime-sources.example.json` 为 `local-input/runtime-sources.json`，填写本机三个平台 runtime 的 `bin` 目录。脚本会自动提取共享库；目录配置不会提交到仓库。

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
3. 根据 `vendor/detected-deps.json` 下载与选定 Core/build_tools 基线匹配的 Boost、ICU、Brotli、Linux Qt、Ubuntu 16 sysroot 和 ONLYOFFICE portable Python3。当前锁定输入为 Boost 1.72.0、ICU 74.2、Brotli `a47d7475063eb223c87632eed806c0070e70da29`、Linux Qt 5.9.9。
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

Windows 和 Linux 两个架构均已接入精确输入的 Core 产物复用、sccache 对象缓存、按实际 CPU 核数并行，以及耗时/CPU/内存/磁盘诊断。Core 缓存仅在验证成功后保存，命中后仍执行本轮验证。手工入口的 `rebuild_core` 可绕过整包复用来检查编译阶段；对象缓存仍启用。此轮改动尚未推送和运行新流水线，性能收益以之后的 Actions 指标为准。

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

## V8 Windows SDK：首次构建后固定复用

V8保留现有静态链接方式，不另建仓库或改成V8 DLL。独立workflow `Build pinned V8 Windows SDK`只手动触发，使用 `config/v8-windows.lock.json` 的完整规范化SHA256作为Release tag及精确cache key。普通Core源码、patch或文档变化不会重编V8。

在GitHub Actions中选择该workflow的 **Run workflow**：

- `operation=promote`：填写已成功构建V8的 `source_run_id`，下载该run的 `v8-windows-x64-sdk` artifact，验证来源仓库、workflow、成功状态、原提交的完整输入锁以及SDK内容。旧版artifact可以直接发布，不需要为了接入Release再编一次。
- `operation=build`：仅在该锁对应的Release不存在时冷构建V8；已有Release时直接恢复和运行探针。
- `operation=reuse`（默认）：只恢复、校验和运行已有SDK探针；缺包明确失败，绝不回退源码构建。

run `39254838375` 已完成 1700/1700 个 V8 monolith 构建步骤，但独立 probe 因缺少 `v8/include` 搜索路径而失败，没有可供 `promote` 使用的成功 artifact。当前脚本已补齐该路径；首次发布仍需手动运行 `operation=build` 并通过完整的 probe、归档校验和发布验证。本地无需编译。

首次发布前会从SDK ZIP重新解包、验证头文件与静态库、重新编译链接C++探针并执行JavaScript `1 + 2`。发布包含ZIP、SHA256和 `sdk-release.json`；先创建draft，附件完整后发布，并再次下载核对。已有同名tag不会覆盖，不使用 `latest`、`--clobber` 或宽泛cache restore-key。Release是固定来源，Actions artifact仅用于首次迁移和短期下载，cache仅加速下载。

后续Windows功能workflow可在Python 3.11+环境中直接使用恢复action：

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'
- name: Prepare isolated patched source
  shell: pwsh
  run: python scripts/stage_core_source.py --destination vendor/work/feature-build
- name: Restore V8 development dependency
  id: v8
  uses: ./.github/actions/restore-v8-windows-sdk
  with:
    token: ${{ github.token }}
    destination: ${{ runner.temp }}/v8-sdk
    staging-root: vendor/work/feature-build
```

普通消费者只需要 `contents: read`；首次导入artifact需要 `actions: read`，发布job需要 `contents: write`。action输出 `sdk-root`、`include-root`、`library-path`、`archive-sha256` 和 `sdk-key`。可选的 `staging-root` 只接受 `stage_core_source.py`生成且Core来源匹配的隔离目录，按现有qmake布局放置头文件与 `v8_monolith.lib`，记录 `.v8-sdk-input.json`；不写官方 `core/` 输入树。未提供该参数时只恢复独立SDK目录。

SDK下载命中cache后仍验证所有hash、V8/depot_tools提交、GN参数、ABI和解包后的头文件。改变V8/工具链/GN配置会生成新tag；若二进制配方改变而这些字段未变，必须同步递增锁中的 `sdkId`（例如追加 `-r2`），不能覆盖旧包。现有X2T-only workflow不需要V8 SDK，保持原有入口；完整Core功能编译仍由后续BLD卡实现和实测，不因SDK恢复入口就绪而视为通过。

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

CI 对缺少 import library 的 DLL 使用 `dumpbin /exports` 生成 `.def`，再用 `lib.exe` 生成 import library；该流程曾在旧基线上通过 Windows 编译验证，10.0 基线仍待重跑。如果未来 DLL 存在必须标记为 `DATA` 的导出、ordinal-only 导出或其他特殊 PE 导出，自动生成可能无法覆盖，届时应提供该 DLL 对应的原始 `.lib`。这不会影响 Linux 路线。

## 编译验证与功能验证的边界

旧基线三平台编译已通过；升级至 10.0 后，需要重新验证 Core/build_tools、第三方依赖和预编译 runtime 能否完成链接。当前 workflow 的自动检查覆盖产物架构和动态依赖；它没有执行文档转换 fixture 或 `distribute` round-trip。因此，功能改动仍需通过实际转换输入/输出验证，不能仅凭编译成功判断格式行为正确。

## 从官方同步 Core 并提取本地 runtime

旧版runtime提取流程仅用于历史归档。当前 `scripts/download.py --force-source` 会重置 Core 来源目录，并把构建补丁/overlay写回输入树；在隔离源任务 `LUNA-CORE-BLD-01-FIX02`完成前，不要用它准备本轮功能构建。`native-bin/windows/bin` 已核实为9.4.0.129，不能作为Core 10 runtime来源。实际运行库路径须以本机忽略配置为准，逐DLL记录来源与版本，并由Windows基线任务做真实加载/转换验收；`verify_vendor.py`只核验文件/hash，不核验Core版本或ABI。

按当前用户要求，功能代码只维护在 `patches/core/*.patch`，不提交已打功能补丁的 `core/` 快照。`core/`是官方来源输入；构建/测试在隔离staging先应用CI构建修正，再按顺序重放功能patch，最后应用明确的品牌overlay。上游同步保留固定来源并检查patch冲突，功能代码不靠整文件overlay替换官方文件。

当前 `download.py` 和workflow仍有在输入树应用/构建快照的旧行为，须由任务 `LUNA-CORE-BLD-01-FIX02` 改成隔离源流程；这不代表脚本已完成改造。改造前不要在用户当前源码执行上述force-source命令来测试功能patch，也不要通过重置Core清理历史构建/品牌或用户改动。

runtime同步只打包动态库，不会把来源中的 `x2t`、字体缓存或其他应用资源混进链接依赖。`native-bin/windows/bin`里的9.4 DLL不能用于Core 10；当前vendor归档来自单独的10.0.0.169目录且逐文件匹配，但标记为metadata-only-reconciliation，须先做实际加载/转换验证，失败时重建匹配DLL闭包。生成的 `x2t` 也要部署到对应版本的完整运行环境。Core官方commit、项目patch列表和runtime SHA256记录在 `ci/baseline.json` 与 `vendor/checksums.json`；这些hash证明输入字节固定，不单独证明来源/ABI匹配。


## Core 重编译版本约定

- 每一轮修改 Core 源码、C++ 补丁或其它需要重编译 Core 的输入，必须在同一轮修改中递增 `config/branding.json` 的四段版本。
- 常规修复递增第四段 build 号，例如 `1.0.0.0` → `1.0.0.1`；发布策略要求提升前三段时另行调整，但不得复用旧版本号发布修改后的 Core。
- 同一轮失败重试不重复递增；新一轮 Core 修改再次递增。三端的同一轮源码使用同一版本，EXE、自有 DLL 和运行包命名均从该配置读取。
- 只有测试、诊断或文档变化且不需要重编译 Core 时，不为其单独提升 Core 版本，也不自动触发流水线。
- 本轮 Word 保护属性、Slide 行距及 Core 纹理裁剪修复的目标版本为 `1.0.0.1`，此前 `1.0.0.0` 运行包不包含这些修复。
