// .eslintrc.cjs
//
// Minimal ESLint config for the Phase 3.7 frontend: TypeScript +
// React Hooks correctness rules only. Deliberately small, matching
// this repository's backend `ruff` configuration philosophy
// ("boring", no opinionated style churn) -- see pyproject.toml's
// [tool.ruff] comment.
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["react-refresh"],
  ignorePatterns: ["dist", "node_modules"],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
  },
};
