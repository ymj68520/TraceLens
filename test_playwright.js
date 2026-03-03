const { chromium } = require('playwright');
(async () => {
  try {
    const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
    console.log('Connected!');
    await browser.close();
  } catch (e) {
    console.error('Error:', e.message);
  }
})();
