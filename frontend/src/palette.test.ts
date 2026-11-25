// palette.test.ts -- MILO's UI is warm: no blue or purple anywhere. Scans every CSS, TS and
// TSX file under src/ for a colour (hex, rgb[a], hsl[a]) whose hue is 195-315 degrees.
// Near-greys (saturation <= 8%) and near-black/near-white are ignored: their hue is noise.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

// Vitest runs from frontend/ (jsdom gives import.meta.url an http: scheme).
const SRC = join(process.cwd(), "src");
const MIN_HUE = 195;
const MAX_HUE = 315;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(css|tsx?)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** Hue in degrees, saturation and lightness in 0..1 (HSL). */
function hsl(r: number, g: number, b: number): [number, number, number] {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = max === rn ? ((gn - bn) / d) % 6 : max === gn ? (bn - rn) / d + 2 : (rn - gn) / d + 4;
  h *= 60;
  return [h < 0 ? h + 360 : h, s, l];
}

function coolColours(text: string): string[] {
  const found: string[] = [];
  const isCool = (r: number, g: number, b: number) => {
    const [h, s, l] = hsl(r, g, b);
    return s > 0.08 && l > 0.06 && l < 0.97 && h >= MIN_HUE && h <= MAX_HUE;
  };
  for (const m of text.matchAll(/#([0-9a-fA-F]{3,8})\b/g)) {
    let hex = m[1];
    if (hex.length === 3 || hex.length === 4) hex = [...hex.slice(0, 3)].map((c) => c + c).join("");
    else if (hex.length === 6 || hex.length === 8) hex = hex.slice(0, 6);
    else continue;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    if (isCool(r, g, b)) found.push(m[0]);
  }
  for (const m of text.matchAll(/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/g)) {
    if (isCool(Number(m[1]), Number(m[2]), Number(m[3]))) found.push(m[0]);
  }
  for (const m of text.matchAll(/hsla?\(\s*(-?\d+(?:\.\d+)?)(?:deg)?[\s,]+(\d+(?:\.\d+)?)%/g)) {
    const h = ((Number(m[1]) % 360) + 360) % 360;
    if (Number(m[2]) > 8 && h >= MIN_HUE && h <= MAX_HUE) found.push(m[0]);
  }
  return found;
}

describe("warm palette", () => {
  it("recognises blue and purple, and lets warm colours through", () => {
    expect(coolColours("color: #38bdf8; background: rgba(151, 97, 255, 0.25); fill: hsl(260deg, 80%, 50%)")).toHaveLength(3);
    expect(coolColours("color: #ff8a2b; background: #2a1810; border: rgba(255, 138, 43, 0.4); x: #808080")).toEqual([]);
  });

  it("has no colour with a hue between 195 and 315 degrees in any CSS, TS or TSX file", () => {
    const offenders = files(SRC).flatMap((path) =>
      readFileSync(path, "utf8")
        .split("\n")
        .flatMap((line, i) => coolColours(line).map((c) => `${relative(SRC, path)}:${i + 1} ${c}`)),
    );
    expect(offenders).toEqual([]);
  });
});
