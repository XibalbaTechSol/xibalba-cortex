import { chromium } from 'playwright';

async function checkViewport(name, viewport) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport });
  await page.goto('http://127.0.0.1:5174/', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Graph' }).click();
  await page.waitForSelector('canvas', { timeout: 10000 });
  await page.waitForTimeout(600);
  const canvasInfo = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const ctx = canvas.getContext('2d');
    // WebGL canvases cannot be read via 2D context, use screenshot pixel sampling instead.
    return { width: rect.width, height: rect.height };
  });
  await page.screenshot({ path: `/tmp/xibalba-3d-${name}.png`, fullPage: true });
  const nonBlank = await page.evaluate(async () => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return false;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 200 || rect.height < 240) return false;
    const bitmap = await createImageBitmap(canvas);
    const sampler = new OffscreenCanvas(bitmap.width, bitmap.height);
    const ctx = sampler.getContext('2d');
    if (!ctx) return false;
    ctx.drawImage(bitmap, 0, 0);
    const data = ctx.getImageData(0, 0, sampler.width, sampler.height).data;
    let varied = 0;
    for (let i = 0; i < data.length; i += 160) {
      const r = data[i], g = data[i + 1], b = data[i + 2];
      if (!(r < 25 && g < 35 && b < 55) && !(r > 245 && g > 245 && b > 245)) varied += 1;
      if (varied > 80) return true;
    }
    return false;
  });
  await page.locator('canvas').click({ position: { x: Math.floor((canvasInfo?.width ?? 400) / 2), y: Math.floor((canvasInfo?.height ?? 400) / 2) } }).catch(() => {});
  await browser.close();
  console.log(JSON.stringify({ name, canvasInfo, nonBlank }));
  if (!canvasInfo || !nonBlank) process.exitCode = 1;
}

await checkViewport('desktop', { width: 1440, height: 950 });
await checkViewport('mobile', { width: 390, height: 844 });
