# Core 三端文件与运行时合同

适用基线：ONLYOFFICE Core `ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`，source tree SHA-256 `ea6b4a04be6a1459caa1e9e23d3c59659a7c6cf65f39cb0222690602d2b77e34`。机器可读定义见同目录 `core-feature-contract.json`；profile 结构见 `feature-profile.schema.json`。

本文件区分当前源码事实与后续拟实施协议。这里只冻结格式、兼容性和 ABI 边界，不代表这些字段已由 Core 实现，也不代表产品功能验收通过。所有 Core 功能改动必须以 `patches/core/*.patch` 维护并在隔离 staging 上重放。

## 文件编码

### Word

段落对齐沿用 `pPr` 的现有 `Jc=5`、Byte 值：0 right、1 left、2 center、3 both。Distribute 单独使用 4，未写值仍表示继承/默认；当前 Core writer 会把 `jcDistribute` 与 `thaiDistribute` 折叠成 both，因此不能声称已保真。未知枚举在新严格转换入口报不支持，禁止静默归并。

段落布尔属性 `kinsoku`、`wordWrap`、`overflowPunct`、`topLinePunct`、`autoSpaceDE`、`autoSpaceDN` 使用预留的 `pPr` tag 200–205，Byte 长度和 0/1 payload。缺省表示继承；显式 false 必须编码 0 并在读回后保留。字符缩进 `leftChars`、`rightChars`、`firstLineChars`、`hangingChars` 使用 tag 206–209，父节点为现有 `Ind=1` Variable 容器，值为 Long，单位是百分之一字符。零值保留；可与 twip 属性共存，读取/写入不得互相覆盖。

现有 `afterLines=48`、`beforeLines=49` 和 run `w:w=CompressText=44` 保持原标签与单位，不新增重复编码。区域保护沿用 Permission 0–5 字段和段落流 PermStart/PermEnd 标记：保留原生 OOXML 范围、属性是否存在及值。写出属性名必须为标准大小写 `w:displacedByCustomXml`；读取同时接受标准拼法和历史错误拼法 `w:displacedbyCustomXml`。身份、Space 动态权限和允许/拒绝状态不是文件字段，不写进文档。

以上私有 Word tag 200–209 只在相应父容器下分配。升级官方基线时必须扫描本地保留段与上游定义；有冲突则停止升级并重新分配，不能改动任何既有官方编号。

### Slide

段落对齐依现有 PPTY 数值：ctr=0、dist=1、just=2、justLow=3、l=4、r=5、thaiDist=6。行距保留 pct/pts 类型及原始整数，分别编码 0/1；每个值只能有一种单位，输入同时包含两者时拒绝或按明确错误返回，不得静默 Normalize 丢值。方向按原 token 保留：`horz`、`vert`、`vert270`、`eaVert`，以及 Core 已有的 `mongolianVert`、`wordArtVert`、`wordArtVertRtl`。`eaVert` 表示东亚直立排布，不是将汉字按英文字符逐个旋转。

### Sheet 图片与打印

工作表图片继续用 Picture=29 和相对 worksheet media relationship。共享媒体允许，但每张表必须独立解析 relationship。SDKJS History 的 Picture action type 200 属 SDKJS 行为；Core 只消费保存后的既有图片数据，不自行实现该 History action。Picture 二进制编解码通过不能作为打印支持证据。Native SDKJS 分页和 CPdfPrinter 的 `drawForPrint` 路径都必须验证每页背景绘制、裁剪、缩放、透明度、共享媒体和缺失图片行为。

## 严格图片错误与 ABI

所有既有导出入口默认沿用旧容错，不改变老调用方的返回语义。严格模式仅由明确选择的 X2T 转换任务 opt-in。链路为 X2T task/params → CPdfFile 新增版本化严格入口 → OnlineOfficeBinToPdf 严格转换 → MetafileToRenderer 图片命令 111 → IRenderer `DrawImageFromFile` → CPdfFile/最终 X2T 退出状态。必须识别 renderer 返回值不是 `S_OK` 的情况（包含 `S_FALSE`）、异常、输出写入或最终化失败；遇到首错即停止，不留下成功候选文件，向 X2T 映射为既有转换错误类。

错误码 V1：0 成功，1 图片命令失败（缺失/解码失败/renderer 非 S_OK），2 命令流损坏或异常，3 PDF 写入/最终化失败，4 策略版本或结构尺寸错误。严格 API 只能新增固定宽度 POD policy/result，含 `size` 和 `version`，并增加 V1 非虚入口。不得改变 `CConvertFromBinParams` 布局、`IRenderer` 或 `IMetafileToRenderter` 虚表、既有导出方法签名。版本/尺寸不符必须失败关闭。

## SDKJS、Native 与 WASM 制品

产品输入锁是 `D:/docservice/idp-all/idp-office/engine/manifests/source-lock.json` 当前登记的 SDKJS 10.0.0 commit `3a94485abd83b1683cf4e64aec229d46b89778bd`。Core 消费产品构建制品，不在本仓库复制或分叉 SDKJS。每组验收回执需要记录 source-lock SHA、Browser SDKJS 输出 SHA、Native SDKJS 输出 SHA、Changes/History codec SHA、DoctRenderer.config SHA、字体清单/包 SHA、WASM/loader SHA（或明确“不需要”的理由）、目标 Core patch-set 与 DLL SHA、build profile ID。

浏览器 WASM 由产品 SDKJS 构建负责。若 Core 改动改变 C++ bridge 签名、共享结构或 ABI，必须同步生成新的 bridge/WASM/loader 并随回执锁定；纯文件 codec patch 若未触及桥接，须由构建差异证据证明不需要新 WASM。

## 八种版本组合

`old/new` 分别指旧/本次目标 Core、Browser SDKJS、Native SDKJS。完整许可矩阵以 JSON 合同为准：7 种非全新组合均不得宣称完整新功能路径。旧 Core 对 200–209 这类新 Word tag 不可往返保真，升级前不能让新 Browser SDKJS 持久化这些内容。只有三端全新组合可申请完整功能验收；矩阵中的许可位只表示可以进入验收，不代表功能已经通过。新 Core 配旧 Browser/Native 的组合仅做旧文档回归，除非另有已验证的窄兼容 profile。

## 验证层级和退出条件

`source` profile 只做源文件/合同/固定语料静态验证；`dev` profile 要求匹配构建工具、依赖 SDK 和本次编译产物；`runtime` profile 要求指定 Core DLL/X2T、SDKJS/Native/WASM 回执及真实转换/打印。profile 采用 SHA-256 锁输入，schema 在 `feature-profile.schema.json`。runner 不得以静态检查结果代替 C++ 构建、DLL 加载、Office 文档往返、PDF 导出或打印验证。
