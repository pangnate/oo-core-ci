# Native SDKJS integration for PDF export

The Windows X2T artifact contains Core binaries and a Native event shim. PDF
export also needs a matching SDKJS Native build. Run the packaged
`configure_native_runtime.py` after placing the runtime at its final location:

```powershell
python configure_native_runtime.py --runtime-bin . --sdkjs-root D:\path\to\built\sdkjs
```

The script checks the SDKJS entry files and writes `DoctRenderer.config` with
paths to that build. It loads `native.js`, then `native-window-shim.js`, before
the other Native scripts. The shim supplies the browser-only `CustomEvent` and
`window.dispatchEvent` APIs used by Word's content-control title hover
notification; Native PDF rendering has no listener for that notification.

The SDKJS build remains a product input. The Core artifact does not contain
its browser and Native bundles, so moving a configured runtime may require
running the script again. Use `--replace` to update an
existing configuration and `--dictionaries` if hyphenation data is provided.
