const jsonString = JSON.stringify(window.__INITIAL_STATE__, function(key, val) {
  // 1. 检查 key 是否是 'dep'
  if (key === 'dep') {
    // 如果是，返回占位符字符串，并停止遍历这个对象
    return '<迭代陷阱>';
  }

  // 2. （可选）处理函数，忽略它们
  if (typeof val === 'function') {
    return undefined;
  }

  // 3. 对于所有其他情况，正常返回值，让 JSON.stringify 继续遍历
  return val;
});

console.log(jsonString);