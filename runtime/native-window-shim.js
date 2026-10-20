// Loaded only by DoctRenderer's V8 environment, after SDKJS native.js.
// The content-control title hover event is a browser UI notification. Native
// PDF rendering has no window event listeners, but SDKJS still constructs it.
if (typeof CustomEvent !== "function") {
  var CustomEvent = function (type, options) {
    this.type = type;
    this.detail = options && options.detail;
    this.bubbles = !!(options && options.bubbles);
    this.cancelable = !!(options && options.cancelable);
  };
}
if (typeof window.dispatchEvent !== "function") {
  window.dispatchEvent = function () { return true; };
}
