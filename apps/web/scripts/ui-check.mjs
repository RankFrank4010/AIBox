import { chromium } from 'playwright-core';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
  deviceScaleFactor: 1,
  locale: 'zh-CN',
});
const page = await context.newPage();
const consoleErrors = [];
const pageErrors = [];
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', (error) => pageErrors.push(String(error)));

const results = [];
let latestJob = '';
let sensitive = [];
try {
  const [history, system] = await Promise.all([
    fetch(`${base}/api/transcriptions?limit=1`).then((response) => response.json()),
    fetch(`${base}/api/system`).then((response) => response.json()),
  ]);
  latestJob = history.items?.[0]?.id ?? '';
  sensitive = [
    [system.platform?.hostname, 'AIBox-Demo-PC'],
    [system.storage?.data_dir, 'C:\\AIBox'],
    [system.storage?.models_dir, 'C:\\AIBox\\models\\whisper'],
    ['frankrank', 'aibox'],
  ].filter(([from]) => Boolean(from));
} catch {
  // The API may be offline; the page checks below will report it.
}

async function sanitizeSensitive(targetPage) {
  await targetPage.evaluate((pairs) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      let value = node.nodeValue ?? '';
      for (const [from, to] of pairs) {
        if (value.includes(from)) value = value.split(from).join(to);
      }
      node.nodeValue = value;
    }
  }, sensitive);
}

const routes = [
  ['/', '.hero-card'],
  ['/models', '.model-card'],
  ['/community', '.community-summary'],
  ['/transcribe', '.transcribe-layout'],
  ...(latestJob ? [[`/transcribe?job=${latestJob}`, '.result-panel']] : []),
  ['/tts', '.tts-layout'],
  ['/chat', '.chat-layout'],
  ['/training', '.training-layout'],
  ['/translation', '.translation-layout'],
  ['/images', '.images-layout'],
  ['/videos', '.videos-layout'],
  ['/separations', '.separations-layout'],
  ['/system', '.accelerator-grid'],
  ['/services', '.service-grid'],
  ['/roadmap', '.roadmap-timeline'],
  ['/settings', '.settings-layout'],
];

for (const [route, selector] of routes) {
  await page.goto(`${base}${route}`, { waitUntil: 'networkidle' });
  await page.waitForSelector(selector, { timeout: 20000 });
  await page.waitForTimeout(900);
  await sanitizeSensitive(page);
  const info = await page.evaluate(() => {
    const body = document.body;
    const wide = [...document.querySelectorAll('*')]
      .filter((el) => {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (el.closest('.app-aurora')) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.right > window.innerWidth + 2;
      })
      .slice(0, 8)
      .map((el) => ({
        tag: el.tagName,
        cls: String(el.className).slice(0, 80),
        right: Math.round(el.getBoundingClientRect().right),
      }));
    const icon = document.querySelector('.nav-icon svg');
    return {
      title: document.title,
      h1: document.querySelector('h1')?.textContent?.replace(/\s+/g, ' ').trim(),
      width: window.innerWidth,
      scrollWidth: body.scrollWidth,
      docHeight: document.documentElement.scrollHeight,
      horizontalOverflow: body.scrollWidth > window.innerWidth + 2,
      wide,
      panels: document.querySelectorAll('.panel').length,
      models: document.querySelectorAll('.model-card').length,
      navItems: document.querySelectorAll('.nav-item').length,
      navIconSize: icon ? [Math.round(icon.getBoundingClientRect().width), Math.round(icon.getBoundingClientRect().height)] : null,
      buttons: document.querySelectorAll('button').length,
      textSample: body.innerText.slice(0, 260).replace(/\s+/g, ' '),
    };
  });
  await page.screenshot({
    path: path.join(
      outDir,
      `${
        route === '/'
          ? 'overview'
          : route.includes('?job=')
            ? 'transcribe-result'
            : route
                .replace(/^\//, '')
                .replace(/[/?=&]/g, '-')
                .replace(/-+$/g, '')
      }.png`,
    ),
    fullPage: true,
  });
  results.push({ route, ...info });
  console.log(JSON.stringify({ route, ...info }, null, 2));
}

// Mobile responsive checks
const mobile = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 1,
  locale: 'zh-CN',
  isMobile: true,
});
const mobilePage = await mobile.newPage();
const mobileResults = [];
for (const [route, selector] of [
  ['/', '.hero-card'],
  ['/models', '.model-card'],
  ['/community', '.community-summary'],
  ['/transcribe', '.transcribe-layout'],
  ['/tts', '.tts-layout'],
  ['/chat', '.chat-layout'],
  ['/training', '.training-layout'],
  ['/translation', '.translation-layout'],
  ['/images', '.images-layout'],
  ['/videos', '.videos-layout'],
  ['/separations', '.separations-layout'],
  ['/services', '.service-grid'],
  ['/settings', '.settings-layout'],
]) {
  await mobilePage.goto(`${base}${route}`, { waitUntil: 'networkidle' });
  await mobilePage.waitForSelector(selector, { timeout: 20000 });
  await mobilePage.waitForTimeout(600);
  await sanitizeSensitive(mobilePage);
  const info = await mobilePage.evaluate(() => {
    const nav = document.querySelector('.mobile-nav');
    const rect = nav?.getBoundingClientRect();
    return {
      width: window.innerWidth,
      scrollWidth: document.body.scrollWidth,
      horizontalOverflow: document.body.scrollWidth > window.innerWidth + 2,
      mobileNav: rect
        ? { display: getComputedStyle(nav).display, bottom: Math.round(rect.bottom), height: Math.round(rect.height) }
        : null,
      sidebar: getComputedStyle(document.querySelector('.sidebar')).display,
      topbarHeight: Math.round(document.querySelector('.topbar').getBoundingClientRect().height),
      h1: document.querySelector('h1')?.textContent?.replace(/\s+/g, ' ').trim(),
    };
  });
  await mobilePage.screenshot({
    path: path.join(outDir, `mobile-${route === '/' ? 'overview' : route.slice(1)}.png`),
    fullPage: true,
  });
  mobileResults.push({ route, ...info });
  console.log(JSON.stringify({ mobile: route, ...info }, null, 2));
}

console.log(
  JSON.stringify(
    {
      consoleErrors,
      pageErrors,
      results: results.map((item) => ({
        route: item.route,
        h1: item.h1,
        overflow: item.horizontalOverflow,
        panels: item.panels,
        models: item.models,
        navItems: item.navItems,
        navIconSize: item.navIconSize,
        docHeight: item.docHeight,
      })),
      mobileResults,
    },
    null,
    2,
  ),
);

await browser.close();
