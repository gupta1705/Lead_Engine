/* Offline Clipping contact evidence fixture. No API, account, DB, or external network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const playwrightModule = process.env.PLAYWRIGHT_MODULE || (() => {
  try { return require.resolve('playwright'); }
  catch { return path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'); }
})();
const { chromium } = require(playwrightModule);
const root = path.resolve(__dirname, '..');

async function run() {
  const source = fs.readFileSync(path.join(root, 'app/static/app.js'), 'utf8');
  const rendering = source.slice(source.indexOf('function renderContactProvenance('), source.indexOf('function bindRecipientSelection('));
  const executablePath = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].filter(Boolean).find(p => fs.existsSync(p));
  const browser = await chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1000,height:900}});
    const network = [], errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => { network.push(route.request().url()); return route.abort(); });
    await page.setContent('<main id="root" style="max-width:430px;padding:24px;margin:auto"></main>');
    await page.addStyleTag({content:fs.readFileSync(path.join(root, 'app/static/style.css'), 'utf8')});
    await page.addScriptTag({content:`
      const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
      const fmtDate = iso => new Date(iso).toLocaleString('en-GB');
      const icon = () => ''; const avatar = () => '<span class="avatar">FP</span>';
      const safeUrl = u => /^https?:\\/\\//i.test(String(u || '')) ? String(u) : '';
      const state = {segment:{slug:'lcx-clipping'}};
      ${rendering}
      window.fixture = {
        id:'fixture', selected_recipient_id:'public', outreach:{status:'drafted'},
        apollo_contact_matching:{enabled:false},
        metadata:{clipping_apollo:{person_id:'fixture-person',checked_at:'2026-11-16T10:00:00Z',
          match:{business_name:'Fixture & Partners',domain:'example.test',source_url:'https://example.test/about',
            reason:'Company domain and current employer match the show.'}}},
        contacts:[
          {id:'public',full_name:'Fixture Show',email:'hello@example.test',source:'podcast_rss',email_status:'unverified',
            usable:true,can_select_recipient:true,kind:'shared',drafts_use:true},
          {id:'apollo',full_name:'Alex Example',role_title:'Executive Producer',email:'alex@example.test',
            source:'apollo',verifier:'apollo',email_status:'valid',email_verified_at:'2026-11-16T10:00:00Z',
            apollo_person_id:'fixture-person',usable:true,can_select_recipient:true}
        ],explain:{contact_routes:{routes:[],tried:[]}}
      };
      window.draw = () => document.querySelector('#root').innerHTML = renderContacts(window.fixture);
      draw();
    `});
    assert.equal(await page.getByText('Apollo-verified work email', {exact:false}).count(),1);
    assert(await page.evaluate(() => fixture.contacts.every(c => !Object.hasOwn(c,'notes'))), 'API-shaped fixture must not expose raw notes');
    assert.match(await page.locator('.contact-verified').textContent(), /Checked.*2026/);
    assert.equal(await page.getByText('Matched business: Fixture & Partners (example.test)',{exact:true}).count(),1);
    assert.equal(await page.getByRole('link',{name:'Business match source'}).getAttribute('href'),'https://example.test/about');
    assert.equal(await page.getByText('Source: Podcast feed · Not Apollo-verified',{exact:true}).count(),1);
    assert.equal(await page.getByText('Draft recipient',{exact:true}).count(),1);
    assert.equal(await page.getByRole('button',{name:'Use for draft',exact:true}).count(),1);
    assert.equal(await page.getByText('Apollo contact matching is paused. Existing contacts remain available.',{exact:true}).count(),1);

    await page.evaluate(() => {
      fixture.metadata.clipping_apollo.match.business_name = '<img src=x onerror="window.injected=true">';
      fixture.metadata.clipping_apollo.match.reason = '<script>window.injected=true</script>';
      fixture.metadata.clipping_apollo.match.source_url = 'javascript:window.injected=true'; draw();
    });
    assert.equal(await page.locator('.contact-provenance img, .contact-provenance script').count(),0);
    assert.equal(await page.getByRole('link',{name:'Business match source'}).count(),0);
    assert.equal(await page.evaluate(() => !!window.injected),false);
    assert.match(await page.locator('.contact-provenance').last().textContent(), /<img src=x/);

    await page.evaluate(() => { fixture.contacts[1].apollo_person_id='different-person'; draw(); });
    assert.equal(await page.getByText('Matched business:',{exact:false}).count(),0);
    assert.equal(await page.locator('.contact-verified').count(),1);
    await page.evaluate(() => {
      // The existing public contact can gain verification without changing its source or notes.
      delete fixture.contacts[1].apollo_person_id; fixture.contacts[1].source='website';
      fixture.metadata.clipping_apollo.contact_id='apollo'; draw();
    });
    assert.equal(await page.getByText('Matched business:',{exact:false}).count(),1);
    assert.equal(await page.locator('.contact-verified').count(),1);
    await page.evaluate(() => { fixture.metadata.clipping_apollo.contact_id='another-contact'; draw(); });
    assert.equal(await page.getByText('Matched business:',{exact:false}).count(),0);
    await page.evaluate(() => { delete fixture.metadata.clipping_apollo.contact_id; draw(); });
    assert.equal(await page.getByText('Matched business:',{exact:false}).count(),0);
    await page.evaluate(() => { fixture.contacts[1].email_status='invalid'; fixture.contacts[1].email_verified_at='bad date'; draw(); });
    assert.equal(await page.locator('.contact-verified').count(),0);
    assert.equal(await page.getByText('Apollo email: not verified',{exact:true}).count(),1);
    assert.equal(await page.getByText('bad date',{exact:false}).count(),0);

    await page.evaluate(() => { fixture.recipient_locked_reason='This email was already sent.'; fixture.outreach.status='sent'; draw(); });
    assert.equal(await page.locator('[data-recipient]').count(),0);
    assert.equal(await page.getByText('Email recipient',{exact:true}).count(),1);
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Contact evidence must fit a phone');
    await page.evaluate(() => {
      fixture.metadata.clipping_apollo.match={business_name:'Fixture & Partners',domain:'example.test',source_url:'https://example.test/about',reason:'Company domain and current employer match the show.'};
      fixture.contacts[1].apollo_person_id='fixture-person'; fixture.contacts[1].source='apollo'; fixture.contacts[1].email_status='valid';
      fixture.contacts[1].email_verified_at='2026-11-16T10:00:00Z'; draw();
    });
    const folder=path.join(root,'logs','clipping-contact-ui'); fs.mkdirSync(folder,{recursive:true});
    await page.screenshot({path:path.join(folder,'mobile.png'),fullPage:true});
    await page.setViewportSize({width:1000,height:900});
    await page.screenshot({path:path.join(folder,'desktop.png'),fullPage:true});
    await page.evaluate(() => { state.segment.slug='startup-acquisitions'; delete fixture.apollo_contact_matching; delete fixture.metadata.clipping_apollo; draw(); });
    assert.equal(await page.locator('.contact-provenance').count(),0);
    assert.deepEqual(network,[]); assert.deepEqual(errors,[]);
    console.log('Clipping contact UI passed: verification/source/date, person-scoped business evidence, escaped content, safe links, paused status, recipient locks, mobile layout, and other-project preservation. Synthetic fixtures only.');
  } finally { await browser.close(); }
}
run().catch(error => { console.error(error); process.exit(1); });
