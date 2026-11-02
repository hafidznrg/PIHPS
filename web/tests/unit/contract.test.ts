// Kontrak lintas bahasa: data serving yang dipakai situs harus lolos JSON Schema yang sama
// dengan yang dipakai pipeline Python (src/pihps/serving_schemas). Data: public/data/serving.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";

const schemaDir = join(__dirname, "..", "..", "..", "src", "pihps", "serving_schemas");
const dataDir = join(process.env.PIHPS_DATA_DIR ?? join(__dirname, "..", "..", "public", "data"), "serving");
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validators = Object.fromEntries(
  ["meta", "wilayah", "peta", "tren"].map((k) => [
    k,
    ajv.compile(JSON.parse(readFileSync(join(schemaDir, `${k}.schema.json`), "utf8"))),
  ]),
);
const read = (p: string) => JSON.parse(readFileSync(join(dataDir, p), "utf8"));

describe.skipIf(!existsSync(dataDir))("kontrak serving", () => {
  it("meta.json valid", () => {
    expect(validators["meta"]!(read("meta.json")), JSON.stringify(validators["meta"]!.errors)).toBe(true);
  });
  for (const kind of ["wilayah", "peta", "tren"]) {
    it(`${kind}/*.json valid`, () => {
      const files = readdirSync(join(dataDir, kind));
      expect(files.length).toBeGreaterThan(0);
      for (const f of files) {
        const ok = validators[kind]!(read(`${kind}/${f}`));
        expect(ok, `${kind}/${f}: ${JSON.stringify(validators[kind]!.errors?.slice(0, 3))}`).toBe(true);
      }
    });
  }
  it("setiap wilayah di meta punya file", () => {
    const meta = read("meta.json") as { wilayah: { kode: string }[] };
    for (const w of meta.wilayah) expect(existsSync(join(dataDir, "wilayah", `${w.kode}.json`)), w.kode).toBe(true);
  });
});
