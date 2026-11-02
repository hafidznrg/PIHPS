// Path yang sadar `base` (situs GitHub Pages berada di /PIHPS/).
export const BASE = import.meta.env.BASE_URL.endsWith("/")
  ? import.meta.env.BASE_URL
  : `${import.meta.env.BASE_URL}/`;

export const href = (path = ""): string => `${BASE}${path.replace(/^\//, "")}`;
export const dataUrl = (path: string): string => href(`data/${path.replace(/^\//, "")}`);
export const wilayahHref = (kode: string): string => (kode === "nasional" ? href() : href(`wilayah/${kode}/`));
