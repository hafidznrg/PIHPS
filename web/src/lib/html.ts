// Template HTML kecil dengan escaping otomatis, dipakai di build (Astro set:html) dan di
// peramban (innerHTML). `html` meng-escape setiap nilai kecuali yang sudah `Raw`.

export class Raw {
  constructor(readonly value: string) {}
  toString(): string {
    return this.value;
  }
}

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escape(v: unknown): string {
  return String(v).replace(/[&<>"']/g, (c) => ESC[c] ?? c);
}

function part(v: unknown): string {
  if (v == null || v === false) return "";
  if (v instanceof Raw) return v.value;
  if (Array.isArray(v)) return v.map(part).join("");
  return escape(v);
}

export function html(strings: TemplateStringsArray, ...values: unknown[]): Raw {
  let out = strings[0] ?? "";
  values.forEach((v, i) => {
    out += part(v) + (strings[i + 1] ?? "");
  });
  return new Raw(out);
}

export const raw = (s: string): Raw => new Raw(s);
