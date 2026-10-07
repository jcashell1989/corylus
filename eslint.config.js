module.exports = [{
  ignores: ["static/vendor/**", "node_modules/**"]
}, {
  files: ["static/flow*.js", "tests/test_flow_*.js"],
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: "script",
    globals: Object.fromEntries([
      "window", "document", "navigator", "location", "history", "localStorage",
      "fetch", "URL", "URLSearchParams", "ResizeObserver", "requestAnimationFrame",
      "cancelAnimationFrame", "setInterval", "clearInterval", "setTimeout",
      "clearTimeout", "console", "module", "require", "globalThis",
      "AbortController", "performance", "Event", "Node", "HTMLElement"
    ].map(name => [name, "readonly"]))
  },
  rules: {
    "no-undef": "error",
    "no-unused-vars": ["error", {"argsIgnorePattern": "^_", "caughtErrorsIgnorePattern": "^_"}],
    "no-unreachable": "error",
    "no-dupe-keys": "error",
    "no-constant-condition": "error",
    "no-global-assign": "error",
    "no-unsafe-finally": "error",
    "eqeqeq": "error"
  }
}];
