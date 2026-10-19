# Core 严格图片策略 V1（待构建验收的源码候选）

2026-10-19。消费CORE-02合同，不改写POC已锁定的合同/profile。此文描述13→14→15候选接口，尚无C++编译、ABI加载或实际转换通过结论。

源码候选继续登记在历史文件名`patches/core/series-word-candidate.json`，默认`series.json`不变。013独立于Word补丁，014依赖013，015依赖014；正式启用须重编受影响库和X2T并生成同补丁集的功能profile，不能把新增符号与旧DLL混装。

## graphics合同（013）

新增`ConversionPolicyV1 { uint32_t size, version, flags; }`，version=1，flags位0表示严格图片，未知位拒绝。新增`ConversionResultV1 { uint32_t size, version, code, commandOffset, commandType; int32_t rendererStatus; }`。调用方初始化size/version；结果布局不匹配时返回失败且不写未知结构。合法结果布局遇非法policy时code=4。

新增非虚导出`ConvertBufferToRendererV1`，沿用命令111和现有资源解析。严格图片遇任何非S_OK（包括S_FALSE）、空解析结果、解析/绘制异常即停止，code=1；保留首错和字节偏移/命令号/renderer状态，不记录图片路径或内容。普通异常、空输入和检测到的非法/截断命令code=2。既有函数入口不启用严格图片，旧图片容错保持。

底层reader增加基于现有边界字段的读取/跳转检查，不新增成员或虚函数；之前无定义的越界输入现在抛出范围异常，由V1入口转换为code=2。此为基础边界防护，不声称已通过所有高级命令的恶意输入/资源消耗审计；其真实异常、截断、长度及旧语义回归均待编译执行。

## PdfFile合同（014）

新增非虚`OnlineWordToPdfV1`、`OnlineWordToPdfFromBinaryV1`和`CommandsToPdfFromBinaryV1`，显式传policy/result，不在`CConvertFromBinParams`、IRenderer或IMetafileToRenderter中添加字段/虚函数。严格文件入口只在完整转换成功后保存到本次唯一临时候选，再发布到目标；失败清理本次候选，不删已有目标。命令入口只生成内存PDF，调用者仍必须检查HRESULT后才能保存。

code=3表示保存/发布失败，code=4表示策略布局/version/flags错误。既有入口保留图片容错，但共用包装不再忽略实际失败返回。严格调用使用V1 graphics入口；base64读取/解码和所有异常均需透传，不能因读取失败继续保存。

## X2T合同（015）

任务XML字段`m_sImageFailurePolicyV1`：缺省、`legacy`、`0`为旧容错；`strict`、`1`启用V1严格图片；其余值（含空字段）及同一次解析内重复字段均拒绝为`AVS_FILEUTILS_ERROR_CONVERT_PARAMS`，不沿用布尔解析把非法值转false。参数从既有TaskQueue XML进入InputParams，不新增HTTP/MQ/数据库协议。

该字段保存在InputParams内部并随清理释放；InputParams不属于graphics/PdfFile的公开稳定ABI结构，本轮仍要求X2T整体重编。DOCX/XLSX/PPTX及其编辑器BIN/打包输入经现有`doct_bin2pdf`、原始PDF命令BIN经`bin2pdf`选择V1文件入口，支持PDF/PDF-A目标；根分派对其它转换方向显式返回参数错误，避免在未接线的路径静默忽略strict。继续以`S_OK`且V1结果code=0作为成功，失败映射`AVS_FILEUTILS_ERROR_CONVERT`。签名仅在转换成功后运行；签名本身仍使用原有结果/输出语义，不在本批新增签名事务机制。

这些合同均为候选源码边界；13/14/15在真实组件编译/运行前保持PARTIAL，16/19补完整DLL/X2T实链，22～24补新SDKJS功能与视觉验收。
