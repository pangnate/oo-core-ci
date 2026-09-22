此目录不提交本地运行库。直接把目录路径传给 `scripts/download.py`：

- `--linux-amd64-libs`
- `--linux-arm64-libs`
- `--windows-amd64-dlls`

脚本只打包 `*.so*` / `*.dll` 到 `vendor/runtime/`。
