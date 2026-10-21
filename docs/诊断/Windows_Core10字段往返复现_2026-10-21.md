# Windows Core 10 字段往返复现

## 实际运行包

用户指定：`C:/Users/pangnate/Desktop/office测试文件/x2t-windows-amd64 (1)/core10-windows-1.0.0-build-0`。

`x2t.exe` 为 57,221,120 bytes，SHA256 `b10b8c925e57916822eb23818d314b1cc2fe9bbf02555c9562e5028b15911f08`。本次没有替换 EXE/DLL，也没有将本地 020/021 补丁伪装成已在此运行包生效。

使用 `scripts/repro_core_smoke_fields.py` 创建有效的 DOCX/PPTX 对照文档：DOCX settings part 同时登记 content type 与 relationship；PPTX 使用已存在的有效文本形状，替换其中一个段落。输入和输出包均检查 ZIP CRC，输入 XML 检查可解析。每个用例执行 OOXML → Editor.bin → OOXML，18 次转换均 exit 0。

| 用例 | 真实输出 | 判定 |
| --- | --- | --- |
| algorithmName 单独存在 | SHA-256 保留 | 通过 |
| algorithmName + cryptAlgorithmSid | algorithmName 丢失 | 差异复现 |
| algorithmName + cryptProviderType | algorithmName 丢失 | 差异复现 |
| algorithmName + 两项 crypt 属性 | algorithmName 丢失 | 差异复现 |
| 仅 cryptAlgorithmSid，无 algorithmName | 不凭空生成 algorithmName | 对照通过 |
| a:spcPct=75000 | spcPct=75000 | 通过 |
| a:spcPts=1800 | spcPts=1800 | 通过 |
| draw:spcPct=75000，URI 与 a 相同 | spcPts=0 | 差异复现 |
| draw:spcPts=1800，URI 与 a 相同 | spcPts=0 | 差异复现 |

Word 混合属性仍保留 edit/enforcement、SID/provider 及归一化后的 cryptSpinCount/hash/salt；不能将它描述为整段保护信息丢失。

Slide 差异确认为命名空间前缀依赖，不能描述为所有百分比/磅值行距均失败。更换合法前缀不应改变行距语义。

## 本地修复及验证边界

- 020：文档保护与写保护的 XML 输出将 algorithmName 独立于 crypt* 分支写出，保留现有 hash/salt/spinCount 的归一化逻辑。
- 021：行距子节点按 local name 读取，覆盖 DOM 与流式入口；段落流式读取对三个 spacing 容器采用 local name；重读 XML/BIN 时清除旧单位。
- 原生方法级用例提取实际修改后的 C++ 方法体，使用 XML/BIN 测试替身，修复前两个案例组均失败，修复后通过。不是完整 X2T/真实 XML 库往返证明。
- 补丁按当前活动序列重放，保留 016 的保护 DOM 字段及 017 的段落布尔字段。官方 pristine core 未改。
- 本次指定运行包已经实证复现旧问题；携带 020/021 的新二进制仍需执行同一复现脚本确认修复。没有触发或监控流水线。

复现命令：

```powershell
python scripts/repro_core_smoke_fields.py --runtime 'C:/Users/pangnate/Desktop/office测试文件/x2t-windows-amd64 (1)/core10-windows-1.0.0-build-0' --work-root vendor/work/smoke-fields-runtime-20261021
```

工作目录必须为新目录，脚本不会清理已有结果。完整收据：`vendor/work/smoke-fields-runtime-20261021/receipt.json`，含输入/输出 SHA256、加载模块路径、命令、退出码和最终字段。全部 EXE/DLL 前后哈希一致。此项没有重跑 2,048 项字段矩阵，也未覆盖 VML、严格图片错误链、PDF 打印/视觉或 SDKJS。
