const root = process.env.AWO_PLAYWRIGHT || "/home/dsneedy/Desktop/AWO/node_modules/playwright";
const { chromium } = await import(`${root}/index.mjs`);

const url = process.argv[2];
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ userAgent: "Mozilla/5.0" });
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(800);
  const text = await page.evaluate(() => document.body.innerText);
  const links = await page.evaluate(() =>
    Array.from(document.querySelectorAll("a[href^='http']")).map((a) => a.href).slice(0, 400));
  process.stdout.write(JSON.stringify({ text, links }));
} finally {
  await browser.close();
}
