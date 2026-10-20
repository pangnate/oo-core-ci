# LUNA-CORE-BLD-02 构建回执

日期：2026-10-20  
状态：DONE（Windows 依赖开发 SDK 与本卡原生探针通过；不代表 X2T 全量构建）  
执行位置：GitHub Actions，Windows Server 2022  
分支：`codex/v8-probe-icu-path`  
提交：`641f746ea7d4f1f9f3d40aebc588e090c3dd6b60`

## 输入与 ABI

- Core：`ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`，tree SHA256 `ea6b4a04be6a1459caa1e9e23d3c59659a7c6cf65f39cb0222690602d2b77e34`
- build_tools：`a9f9895b172b09595abcafe85d56fab163f9ecb7`，tree SHA256 `fbbcde972ecb8b63efb202e3c7045e5d1fffa9c2b5e15d761fc7f5fe076a1d3d`
- ABI：x64、MSVC v142 14.29、动态 CRT `/MD`、Qt 5.15.2 `msvc2019_64`
- Qt archive SHA256：`e64a657c36383c90624d606866a926402c0ab595f6fd311fa5a20fa90227b608`
- V8 SDK key：`91ba9c93b3018185679b37223a2506c255361b670ca3f4a3bc9b8706c286b75a`；archive SHA256：`2f1a5749584de600bdbb75d2e26c87e0cd1c9dead4c5d9c8d5b1c51c5d095d4a`

## 远端运行

- [GitHub Actions run #16](https://github.com/pangnate/onlyoffice-x2t-ci/actions/runs/39363264087) 成功；job 日志显示依次完成锁定 Qt 解包、Core pristine source staging、HarfBuzz 准备、qmake 生成、nmake 编译/链接及原生探针执行。
- SDK manifest：key `369aafc1dbd962fe6ddd9ab55a9e2d326adf06c86f3bd4f916ace3b2cdbd7493`；压缩包 SHA256 `8f874e7fb035ccd145d8d1860349f5da6189c7c90a1b1aba3d52b3d618061ed0`；`probeStatus=passed`。
- 通过的探针：FreeType/HarfBuzz 字体整形、PNG 编码/解码、OpenJPEG JP2 编码/解码。
- [上传的 Actions artifact](https://github.com/pangnate/onlyoffice-x2t-ci/actions/runs/39363264087/artifacts/12238137438)：ID `12238137438`，上传大小 `518373222` bytes，GitHub artifact digest `sha256:c95257bd93f0e85e278b0f74b2042ba13c0e9ee827da81f1e185dff0e5fe206f`，保留至 2026-11-19。`dist/windows-feature-sdk.zip` 大小 `261238368` bytes。

## 边界

本卡证实锁定输入可在目标 Windows ABI 下构建并执行上述依赖探针。尚未构建/链接完整 X2T，也未发现并锁定完整 X2T 系统 DLL 闭包；这仍是后续构建卡的工作。本次验证不能作为产品端到端转换验收。
