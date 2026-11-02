import { describe, expect, it } from "vitest";
import { bulanPendek, persen, rupiah, selisihHari, tanggalPanjang, tanggalPendek } from "../../src/lib/format";
import { escape, html, raw } from "../../src/lib/html";

describe("format", () => {
  it("rupiah memakai titik ribuan tanpa desimal", () => {
    expect(rupiah(16450)).toBe("Rp16.450");
    expect(rupiah(1650000)).toBe("Rp1.650.000");
    expect(rupiah(null)).toBe("–");
  });

  it("persen bertanda dengan minus tipografis dan koma desimal", () => {
    expect(persen(3.14)).toBe("+3,1%");
    expect(persen(-0.44)).toBe("−0,4%");
    expect(persen(0.01)).toBe("0,0%");
    expect(persen(-12.5, { tanda: false })).toBe("12,5%");
    expect(persen(undefined)).toBe("–");
  });

  it("tanggal ISO dibaca sebagai tanggal kalender, bukan digeser zona waktu", () => {
    expect(tanggalPanjang("2026-10-30")).toBe("Jumat, 30 Oktober 2026");
    expect(tanggalPendek("2026-01-01")).toBe("1 Jan 2026");
    expect(bulanPendek("2017-06")).toBe("Jun 2017");
    expect(selisihHari("2026-10-23", "2026-10-30")).toBe(7);
  });
});

describe("html", () => {
  it("meng-escape nilai, kecuali Raw dan array Raw", () => {
    const nama = '<img src=x onerror="alert(1)">';
    expect(html`<p>${nama}</p>`.value).toBe("<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</p>");
    expect(html`<ul>${[raw("<li>a</li>"), raw("<li>b</li>")]}</ul>`.value).toBe("<ul><li>a</li><li>b</li></ul>");
    expect(html`${null}${false}${0}`.value).toBe("0");
    expect(escape("a&b'")).toBe("a&amp;b&#39;");
  });
});
