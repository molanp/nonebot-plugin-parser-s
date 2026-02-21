// 创建一个序列化函数，可以传入任何对象
function serializeObject(obj) {
  // 定义浏览器内置的常见属性和方法
  const browserBuiltIns = new Set([
    // Window 对象属性
    "window",
    "document",
    "location",
    "history",
    "navigator",
    "screen",
    "frames",
    "self",
    "top",
    "parent",
    "opener",
    "frameElement",
    "external",
    "length",
    "closed",
    "name",
    "status",
    "defaultStatus",
    "toolbar",
    "menubar",
    "scrollbars",
    "resizable",
    "personalbar",
    "locationbar",
    "statusbar",
    "innerWidth",
    "innerHeight",
    "outerWidth",
    "outerHeight",
    "devicePixelRatio",
    "pageXOffset",
    "pageYOffset",
    "scrollX",
    "scrollY",

    // Window 对象方法
    "alert",
    "confirm",
    "prompt",
    "print",
    "stop",
    "focus",
    "blur",
    "close",
    "open",
    "openDialog",
    "showModalDialog",
    "clearInterval",
    "clearTimeout",
    "setInterval",
    "setTimeout",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "postMessage",
    "blur",
    "captureEvents",
    "releaseEvents",
    "getComputedStyle",
    "matchMedia",
    "moveBy",
    "moveTo",
    "resizeBy",
    "resizeTo",
    "scroll",
    "scrollBy",
    "scrollTo",
    "find",
    "getSelection",
    "removeEventListener",
    "addEventListener",
    "dispatchEvent",
    "attachEvent",
    "detachEvent",
    "scrollByLines",
    "scrollByPages",
    "sizeToContent",
    "updateCommands",

    // DOM 相关
    "Image",
    "Audio",
    "Option",
    "XMLHttpRequest",
    "WebSocket",
    "Worker",
    "SharedWorker",
    "MutationObserver",
    "IntersectionObserver",
    "ResizeObserver",
    "Promise",
    "fetch",
    "indexedDB",
    "webkitStorageInfo",
    "localStorage",
    "sessionStorage",
    "crypto",
    "cryptoKey",
    "atob",
    "btoa",
    "TextDecoder",
    "TextEncoder",
    "URL",
    "URLSearchParams",
    "AbortController",
    "Event",
    "CustomEvent",
    "KeyboardEvent",
    "MouseEvent",
    "FormData",
    "Headers",
    "Request",
    "Response",
    "BroadcastChannel",
    "MessageChannel",
    "MessagePort",
    "Notification",
    "Performance",
    "PerformanceNavigation",
    "PerformanceTiming",
    "Screen",
    "Storage",
    "FileReader",
    "Blob",
    "File",
    "DataTransfer",
    "CanvasRenderingContext2D",
    "WebGLRenderingContext",

    // 构造函数和全局对象
    "Array",
    "Object",
    "Function",
    "Number",
    "Boolean",
    "String",
    "Symbol",
    "Date",
    "RegExp",
    "Error",
    "EvalError",
    "RangeError",
    "ReferenceError",
    "SyntaxError",
    "TypeError",
    "URIError",
    "ArrayBuffer",
    "Int8Array",
    "Uint8Array",
    "Int16Array",
    "Uint16Array",
    "Int32Array",
    "Uint32Array",
    "Float32Array",
    "Float64Array",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Proxy",
    "Reflect",
    "BigInt",
    "BigInt64Array",
    "BigUint64Array",
    "Intl",
    "JSON",

    // 控制台
    "console",

    // 其他
    "isNaN",
    "isFinite",
    "parseInt",
    "parseFloat",
    "encodeURIComponent",
    "decodeURIComponent",
    "encodeURI",
    "decodeURI",
    "escape",
    "unescape",
    "eval",
    "uneval",
    "arguments",
    "undefined",
    "NaN",
    "Infinity",
  ]);

  const result = {};

  try {
    // 如果是 window 对象，特别处理，只包含非内置属性
    if (obj === window) {
      for (let prop in obj) {
        // 检查是否是用户自定义的属性（不在内置列表中）
        if (obj.hasOwnProperty(prop) && !browserBuiltIns.has(prop)) {
          try {
            const propValue = obj[prop];

            // 跳过函数和可能引起安全错误的对象
            if (typeof propValue === "function") {
              continue;
            }

            // 检查是否是可能导致跨域错误的对象
            if (propValue != null && typeof propValue === "object") {
              try {
                // 尝试访问一些可能暴露跨域信息的属性
                String(propValue); // 尝试转换为字符串
                JSON.stringify(propValue); // 尝试序列化
              } catch (e) {
                // 如果序列化失败，跳过这个属性
                continue;
              }
            }

            // 添加到结果中
            result[prop] = propValue;
          } catch (e) {
            // 记录访问失败的属性
            console.log(`Skipping property ${prop}: ${e.message}`);
          }
        }
      }
    } else {
      // 对于非 window 对象，直接复制所有可访问的属性
      for (let prop in obj) {
        try {
          if (obj.hasOwnProperty(prop)) {
            const propValue = obj[prop];
            
            // 跳过函数
            if (typeof propValue === "function") {
              continue;
            }
            
            result[prop] = propValue;
          }
        } catch (e) {
          console.log(`Skipping property ${prop}: ${e.message}`);
        }
      }
    }
  } catch (e) {
    console.error("Error accessing object properties:", e);
  }

  // 手动构建 JSON 字符串以避免安全错误
  let jsonStr = "{\n";
  const entries = Object.entries(result);

  for (let i = 0; i < entries.length; i++) {
    const [key, value] = entries[i];

    try {
      // 安全地处理值
      let serializedValue;

      if (value === null) {
        serializedValue = "null";
      } else if (typeof value === "string") {
        serializedValue = JSON.stringify(value);
      } else if (typeof value === "number" || typeof value === "boolean") {
        serializedValue = String(value);
      } else if (typeof value === "object") {
        // 对对象再次进行安全序列化
        try {
          JSON.stringify(value); // 测试是否可以序列化
          serializedValue = JSON.stringify(value);
        } catch (e) {
          serializedValue = '"[Object: cannot serialize]"';
        }
      } else {
        serializedValue = '"[Type: unsupported]"';
      }

      jsonStr += `  ${JSON.stringify(key)}: ${serializedValue}`;

      if (i < entries.length - 1) {
        jsonStr += ",\n";
      }
    } catch (e) {
      jsonStr += `  ${JSON.stringify(key)}: "[SerializationError: ${e.message}]"`;

      if (i < entries.length - 1) {
        jsonStr += ",\n";
      }
    }
  }

  jsonStr += "\n}";

  console.log(jsonStr);
  return jsonStr;
}

// 现在您可以使用这个函数来序列化任何对象
// 例如：
// serializeObject(window);           // 序列化 window 对象
// serializeObject(yourCustomObject); // 序列化自定义对象