import { chromium } from 'playwright-core';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir } from 'node:fs/promises';

const base = process.env.AIBOX_URL ?? 'http://127.0.0.1:8765';
const edge =
  process.env.EDGE_PATH ??
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, '../../..');
const outDir = path.join(rootDir, 'screenshots');
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ['--disable-gpu', '--hide-scrollbars'],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: 'zh-CN',
});
const page = await context.newPage();
const errors = [];
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text());
});
page.on('pageerror', (error) => errors.push(String(error)));

await page.goto(`${base}/transcribe`, { waitUntil: 'networkidle' });
await page.waitForSelector('.transcribe-layout');

const modelValue = await page.locator('.config-panel select').first().inputValue();
const modelOptions = await page.locator('.config-panel select').first().locator('option').allTextContents();
console.log('model select', { modelValue, modelOptions });

await page.setInputFiles(
  'input[type=file]',
  path.join(rootDir, 'examples', 'audio', 'chinese-test.wav'),
);
await page.waitForSelector('.selected-file');
await page.waitForTimeout(800);
const selected = await page.locator('.selected-file-copy').innerText();
console.log('selected file', selected);
await page.screenshot({ path: path.join(outDir, 'transcribe-upload.png'), fullPage: true });

await page.locator('.start-transcribe').click();
await page.waitForSelector('.processing-panel, .result-panel', { timeout: 30000 });
console.log('task started');
await page.waitForSelector('.result-panel', { timeout: 180000 });
await page.waitForTimeout(1200);

const result = await page.evaluate(() => ({
  filename: document.querySelector('.result-title h2')?.textContent,
  meta: document.querySelector('.result-meta-strip')?.textContent?.replace(/\s+/g, ' ').trim(),
  segments: [...document.querySelectorAll('.segment-row .segment-text')].map((el) => el.textContent),
  segmentCount: document.querySelectorAll('.segment-row').length,
  exportChips: [...document.querySelectorAll('.export-chip')].map((el) => el.textContent),
  audioPlayer: Boolean(document.querySelector('.result-panel .audio-player')),
  resultHeight: Math.round(document.querySelector('.result-panel').getBoundingClientRect().height),
  text: document.querySelector('.transcript-full')?.textContent?.slice(0, 120) ?? null,
}));
console.log('result', JSON.stringify(result, null, 2));
await page.screenshot({ path: path.join(outDir, 'transcribe-result.png'), fullPage: true });

// Verify theme toggle and navigation.
await page.locator('.topbar .icon-button').click();
await page.waitForTimeout(300);
const theme = await page.evaluate(() => ({
  data: document.documentElement.dataset.theme,
  background: getComputedStyle(document.body).backgroundColor,
}));
console.log('theme after toggle', theme);

await page.locator('.side-nav .nav-item').filter({ hasText: '模型库' }).click();
await page.waitForSelector('.model-card');
await page.waitForTimeout(500);
const installed = await page.evaluate(() => ({
  installedCount: document.querySelectorAll('.installed-flag').length,
  defaultChips: [...document.querySelectorAll('.default-chip')].map((el) => el.textContent?.trim()),
  downloadButtons: [...document.querySelectorAll('.model-card button')]
    .map((el) => el.textContent?.trim())
    .filter(Boolean)
    .slice(0, 12),
  modelCards: document.querySelectorAll('.model-card').length,
}));
console.log('models page', JSON.stringify(installed, null, 2));

// Verify settings save round-trip (no-op save) and theme persistence.
await page.locator('.side-nav .nav-item').filter({ hasText: '设置' }).click();
await page.waitForSelector('.settings-layout');
await page.waitForTimeout(500);
const settingsInfo = await page.evaluate(() => ({
  selects: document.querySelectorAll('.settings-page select').length,
  themeCards: document.querySelectorAll('.theme-card').length,
  saveButtonDisabled: document.querySelector('.page-actions button')?.hasAttribute('disabled'),
  dataDir: document.querySelector('.settings-paths strong')?.textContent,
}));
console.log('settings', settingsInfo);

console.log('errors', errors);
await browser.close();
