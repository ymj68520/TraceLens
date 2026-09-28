const path = require('node:path');

module.exports = {
  // Keep the npm-managed Chrome binary inside this project instead of using
  // the user-global Puppeteer cache.
  cacheDirectory: path.join(__dirname, 'node_modules', '.cache', 'puppeteer'),
};
