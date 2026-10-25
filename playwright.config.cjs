const {defineConfig} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const subpath = process.env.PWA_TEST_SUBPATH ? '/EggIncVirtualShip/' : '/';
let siteRoot = 'pwa';
if (process.env.PWA_TEST_SUBPATH) {
  siteRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'egginc-pages-'));
  fs.symlinkSync(path.join(__dirname, 'pwa'), path.join(siteRoot, 'EggIncVirtualShip'), 'dir');
  process.on('exit', () => fs.rmSync(siteRoot, {recursive: true, force: true}));
}
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
module.exports = defineConfig({
  testDir: './tests/pwa',
  testMatch: '**/*.spec.cjs',
  workers: 1,
  timeout: 30000,
  use: {baseURL: 'http://127.0.0.1:8765' + subpath, launchOptions: {executablePath}},
  webServer: {command: 'python3 -m http.server 8765 --bind 127.0.0.1 --directory ' +
    "'" + siteRoot.replaceAll("'", "'\\''") + "'",
    url: 'http://127.0.0.1:8765' + subpath, reuseExistingServer: false},
});
