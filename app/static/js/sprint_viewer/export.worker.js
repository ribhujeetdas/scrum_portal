import { buildWorkbookBytes } from "./export.js";

self.onmessage = (event) => {
  try {
    const bytes = buildWorkbookBytes(event.data);
    self.postMessage({ ok: true, bytes }, [bytes.buffer]);
  } catch (error) {
    self.postMessage({ ok: false, message: error?.message || "Workbook generation failed" });
  }
};
