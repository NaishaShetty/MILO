// setup.ts
//
// Vitest global setup: extends `expect` with `@testing-library/jest-dom`
// matchers (`toBeInTheDocument`, etc.) for every test file, per
// `vite.config.ts`'s `test.setupFiles`.
import "@testing-library/jest-dom/vitest";
