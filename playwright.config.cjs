const {defineConfig} = require('@playwright/test');
const fs = require('node:fs');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
module.exports = defineConfig({
  testDir: './tests/pwa',
  testMatch: '**/*.spec.cjs',
  workers: 1,
  timeout: 30000,
  use: {baseURL: 'http://127.0.0.1:8765', launchOptions: {executablePath}},
  webServer: {command: 'python3 -m http.server 8765 --bind 127.0.0.1 --directory pwa', url: 'http://127.0.0.1:8765', reuseExistingServer: false},
});
