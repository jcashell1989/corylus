// Component linting while the reviewed td viewer baseline is absent from main.
module.exports = [{
  files: ["static/runner_board*.js", "tests/test_runner_board.js"],
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: "script",
    globals: Object.fromEntries([
      "window", "document", "fetch", "URL", "setInterval", "clearInterval",
      "module", "require", "globalThis", "AbortController", "setTimeout", "clearTimeout"
    ].map(name => [name, "readonly"]))
  },
  rules: {
    "no-undef": "error",
    "no-unused-vars": ["error", {argsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_"}],
    "no-unreachable": "error",
    "no-dupe-keys": "error",
    "no-constant-condition": "error",
    "no-global-assign": "error",
    "no-unsafe-finally": "error",
    "eqeqeq": "error"
  }
}];
