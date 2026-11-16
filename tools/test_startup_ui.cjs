/* Real acquisition form rendering and submission, with synthetic data and a mocked request. */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname,'..');
async function run() {
  const source = fs.readFileSync(path.join(root,'app/static/app.js'),'utf8');
  const functions = source.slice(source.indexOf('function renderAcquisitionEvidence('),source.indexOf('async function openLeadEmail('));
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:850}});
    await page.setContent('<div id="root" style="max-width:700px;padding:24px;margin:auto"></div>');
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'app/static/style.css'),'utf8')});
    await page.addScriptTag({content:`
      const esc = v => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
      const icon = () => ''; const $ = (s,r=document) => r.querySelector(s); const $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
      const modal={current:{kind:'lead',id:'fixture'}};
      async function post(url,data){window.saved={url,data};return {ok:true};}
      function toast(){} async function openLead(){window.refreshed=true;}
      ${functions}
      const d={metadata:{startup_acquisition:{status:'Research required'},startup_review:{price_source:'Founder says "hello" <safe>'}}};
      document.querySelector('#root').innerHTML=renderAcquisitionEvidence(d);bindAcquisitionEvidence(document.querySelector('#root'),d,'fixture');
    `});
    assert.equal(await page.locator('form').count(),1);
    assert.equal(await page.locator('[data-acquisition="deal_type"] option').count(),2);
    await page.getByText('Record or update acquisition evidence',{exact:true}).click();
    await page.locator('[data-acquisition="asking_price_inr"]').fill('5000000');
    assert.equal(await page.locator('[data-acquisition="price_source"]').inputValue(),'Founder says "hello" <safe>');
    await page.locator('[data-acquisition="deal_type"]').selectOption('full_company_acquisition');
    await page.locator('[data-acquisition="checked_at"]').fill('2026-11-16');
    await page.getByRole('button',{name:'Save acquisition evidence'}).click();
    await page.waitForFunction(()=>window.saved && window.refreshed);
    const saved=await page.evaluate(()=>window.saved);
    assert.equal(saved.url,'/api/leads/fixture/acquisition-evidence');
    assert.equal(saved.data.asking_price_inr,'5000000');
    assert.equal(saved.data.deal_type,'full_company_acquisition');
    assert(await page.getByRole('button',{name:'Save acquisition evidence'}).isEnabled());
    const out=path.join(root,'logs','startup-ui');fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),'Mobile form must not overflow');
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    console.log('Startup form passed: escaped source text, full-company-only options, evidence submission, refresh and mobile layout. Synthetic data only.');
  } finally { await browser.close(); }
}
run().catch(error=>{console.error(error);process.exit(1);});
