const path=require('node:path');
let playwright;
try { playwright=require('playwright'); }
catch { playwright=require(path.join(process.env.USERPROFILE||process.env.HOME,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
module.exports={chromium:playwright.chromium,chromePath:process.env.CHROME_PATH||(process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined)};
