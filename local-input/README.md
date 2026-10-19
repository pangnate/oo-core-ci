此目录不提交本地运行库。将 [`runtime-sources.example.json`](runtime-sources.example.json) 复制为 `runtime-sources.json`，填写本机已有的三个平台运行时 `bin` 目录。实际配置文件已加入 `.gitignore`，不会提交机器专属路径。

配置完成后，`scripts/download.py` 会自动读取它并打包三个平台的运行库；也可以在命令行用 `--linux-amd64-libs`、`--linux-arm64-libs`、`--windows-amd64-dlls` 单独覆盖对应路径。

脚本只打包 `*.so*` / `*.dll` 到 `vendor/runtime/`，不会把可执行文件、字体或其他应用资源放进链接 runtime。
