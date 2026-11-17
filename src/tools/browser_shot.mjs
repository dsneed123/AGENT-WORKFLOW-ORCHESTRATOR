const root = process.env.AWO_PLAYWRIGHT || "/home/dsneedy/Desktop/AWO/node_modules/playwright";
const { chromium } = await import(`${root}/index.mjs`);

const [url, out] = process.argv.slice(2);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.screenshot({ path: out, fullPage: true });
} finally {
  await browser.close();
}
