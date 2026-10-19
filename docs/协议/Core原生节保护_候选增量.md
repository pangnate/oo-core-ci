# CORE-08 原生节保护候选增量

2026-10-19。纯源码候选，未编译运行；不修改已锁定POC协议/profile。对应`016-word-protection-source-omissions.patch`。

确定遗漏：CSectionProperty的XML DOM/流式和toXML均支持`w:formProt`，但固定Core的section BIN writer/reader完全没有对应字段。此字段不能冒充段落Bidi或文档级enforcement，也不能复用Permission身份字段。

在`c_oSerProp_secPrType`父容器下登记项目私有`formProt=200`；基线该容器仅占0～15，所有官方编号保留。编码沿用section记录的tag Byte + payload长度Long + Bool一字节；缺省不写，false写0，true写1，读端拒绝长度非1或值非0/1。支持正文末节、段落节属性及sectPrChange共享读写路径。它与pPr.Kinsoku200、Sheet History200属于不同父命名空间，不冲突。

升级时须重新扫描该父容器，冲突显式阻断，不静默改号。此候选只证明新C++两端存在通道；旧SDKJS/旧reader可能跳过并丢失该字段，未获得支持回执前不得宣传混合版本无损或扩大可写范围。CORE-25及后续产品制品合同须列明该能力，完整Native保存/历史回放仍待后续验收。

同一补丁填充CDocProtect的空DOM读取函数，复用现成模型/Settings标签/原生hash-salt-algorithm字段，不新增密码算法或身份策略。DOM同时读取现有别名，规范名优先；有冲突的别名组合不作为已证明跨parser一致的合法样例，原流式parser对冲突的历史顺序行为不在本卡扩大修改。
