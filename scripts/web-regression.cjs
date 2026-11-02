// Run against local Vite (:5173) and a pnpm build preview (:5191).
// Requires Playwright on NODE_PATH; all HTTP data are generated fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');
const local = process.env.WEB_LOCAL_URL || 'http://127.0.0.1:5173';
const preview = process.env.WEB_STATIC_URL || 'http://127.0.0.1:5191';
const image = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#eaf0eb"/><text x="100" y="180" font-size="64" fill="#24514b">Generated fixture</text><rect x="100" y="300" width="400" height="200" fill="#bdd5ce"/><rect x="650" y="300" width="400" height="200" fill="#d7cda9"/><text x="100" y="750" font-size="32">No course content</text></svg>`;
const meta = { status:'generated', updatedAt:'2026-11-03T00:00:00Z' };
const info = { id:'fixture',title:'介面驗證課程',subtitle:'僅使用合成資料',deckCount:1,videoCount:1,updatedAt:meta.updatedAt,videoUrls:{'video-b':'https://example.com/fixture.mp4'} };
const course = { info, decks:[{id:'deck',title:'測試簡報',slideCount:2}], videos:[{id:'video-b',title:'測試影片',duration:100,source:'materials/test.mp4'}],status:{} };
const slides = [1,2].map(index=>({index,title:`測試投影片 ${index}`,image:'/fixture.svg',thumb:'/fixture.svg',ranges:[{video:'video-b',start:12,end:24}],note:meta}));
const markdown = '# 合成筆記\n\n資料契約驗證 [00:12](video:video-b?t=12)。\n\n[拒絕郵件](mailto:test@example.com) [拒絕腳本](javascript:alert(1))\n\n<details><summary>補充</summary>安全的折疊文字</details>\n\n<script>window.injected=true</script><img src=x onerror="window.injected=true">';
const deck = {deck:course.decks[0],slides,notes:{'1':{markdown},'2':{markdown:'第二頁原始筆記',meta}}};
const account={id:'claude',provider:'claude',label:'測試帳號',loggedIn:true,models:[{id:'sonnet',label:'Sonnet'}],efforts:['medium']};
const NOTES = 'section[aria-label="筆記"]';
const json = (route,body)=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
async function fixture(page, isStatic=false) {
 const requests=[];
 await page.route('**/fixture.svg',r=>r.fulfill({contentType:'image/svg+xml',body:image}));
 await page.addInitScript(()=>{
  window.sources=[];
  window.EventSource=class {
   constructor(){this.listeners={};this.closed=false;window.sources.push(this);}
   addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
   close(){this.closed=true;}
   emit(name,body){for(const fn of this.listeners[name]??[])fn({data:JSON.stringify(body)});}
  };
 });
 let saved={markdown,meta,review:null};
 const review={findings:[{reviewer:'correctness',severity:'high',quote:'資料契約驗證',problem:'時間點對不上老師講的內容',fix:'改成 [00:14](video:video-b?t=14)'},{reviewer:'style',severity:'low',quote:'',problem:'可以加一張圖',fix:''}],unresolved:[{reviewer:'correctness',severity:'high',quote:'資料契約驗證',problem:'時間點對不上老師講的內容',fix:'改成 [00:14](video:video-b?t=14)'}],revised:true,reviewedAt:meta.updatedAt};
 const job={id:'job-1',course:'fixture',kind:'pipeline',state:'running',progress:0,message:'等待進度',steps:[]};
 let jobReads=0;
 await page.route('**/api/**',async route=>{
  const request=route.request(), path=new URL(request.url()).pathname;
  requests.push({path,method:request.method(),body:request.postData(),headers:request.headers()});
  if(isStatic) throw new Error(`Static mode requested API: ${path}`);
  if(path==='/api/courses')return json(route,[info]);
  if(path==='/api/courses/fixture')return json(route,course);
  if(path.endsWith('/alignment'))return json(route,{videos:{},segments:Array.from({length:100},(_,i)=>({video:'video-b',start:i,end:i+1,deck:'deck',slide:1}))});
  if(path.endsWith('/decks/deck'))return json(route,{deck:deck.deck,slides});
  if(path.includes('/notes/')) {
   if(request.method()==='PUT'){
    await new Promise(resolve=>setTimeout(resolve,1000));
    saved={markdown:JSON.parse(request.postData()).markdown,meta:{...meta,status:'edited'},review:null};
    return json(route,{meta:saved.meta});
   }
   return json(route,path.endsWith('/1')?{...saved,review}:{markdown:'第二頁原始筆記',meta,review:null});
  }
  if(path.endsWith('/transcript'))return json(route,{segments:[{start:14,end:18,text:'合成逐字稿'}],partial:false});
  if(path.endsWith('/accounts'))return json(route,[account]);
  if(path.endsWith('/chats'))return json(route,[]);
  if(path==='/api/agents/chat') return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"start","chatId":"fixture-chat"}\r\n\r\ndata: {"type":"text","delta":"合成串流回覆"}\r\n\r\ndata: {"type":"done","chatId":"fixture-chat"}\r\n\r\n'});
  if(path.endsWith('/decks/deck/assets'))return json(route,{path:'assets/pasted-0123456789.png'});
  if(path.endsWith('/upload'))return json(route,{saved:['materials/tiny.pdf'],manifest:{decks:[],videos:[]}});
  if(path.endsWith('/scan'))return json(route,{decks:[],videos:[]});
  if(path.endsWith('/jobs'))return json(route,{id:job.id});
  if(path==='/api/jobs/job-1'){jobReads++;return json(route,job);}
  throw new Error(`Unhandled fixture: ${path}`);
 });
 await page.route('**/data/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/data/courses.json')return json(route,[info]);
  if(path.endsWith('/course.json'))return json(route,course);
  if(path.endsWith('/decks/deck.json'))return json(route,deck);
  if(path.endsWith('/transcripts/video-b.json'))return json(route,{segments:[],partial:false});
  throw new Error(`Unhandled static fixture: ${path}`);
 });
 return {requests,job,jobReads:()=>jobReads};
}
async function unicodeVideoLinks(browser, base, isStatic) {
 const page=await browser.newPage();
 try {
  await fixture(page,isStatic);
  const unicodeMarkdown='[中文影片](video:課堂一?t=12) [編碼影片](video:%E8%AA%B2%E5%A0%82%E4%B8%80?t=24) [ASCII影片](video:video-b?t=12) [未知影片](video:不存在?t=12) [拒絕腳本](javascript:alert(1)) [拒絕資料](data:text/html,test)';
  const unicodeCourse={...course,info:{...info,videoUrls:{'課堂一':'https://example.com/public-videos/chinese.mp4','video-b':'https://example.com/public-videos/ascii.mp4'}},videos:[...course.videos,{id:'課堂一',source:'materials/chinese.mp4',title:'中文影片',duration:100}]};
  if(isStatic){
   await page.route('**/data/fixture/course.json',route=>json(route,unicodeCourse));
   await page.route('**/data/fixture/decks/deck.json',route=>json(route,{...deck,notes:{'1':{markdown:unicodeMarkdown,meta}}}));
  }else{
   await page.route('**/api/courses/fixture',route=>json(route,unicodeCourse));
   await page.route('**/api/courses/fixture/decks/deck/notes/1',route=>json(route,{markdown:unicodeMarkdown,meta,review:null}));
  }
  await page.route('**/files/fixture/**',route=>route.abort());
  await page.route('https://example.com/public-videos/**',route=>route.abort());
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.getByRole('button',{name:'中文影片',exact:true}).waitFor();
  assert.equal(await page.locator(NOTES+' button.timestamp').count(),3);
  for(const [label,video] of [['中文影片','chinese'],['編碼影片','chinese'],['ASCII影片','ascii']]){
   await page.getByRole('button',{name:label,exact:true}).click();
   const expected=isStatic?`https://example.com/public-videos/${video}.mp4`:`/files/fixture/materials/${video==='ascii'?'test':video}.mp4`;
   assert.equal(await page.locator('video').getAttribute('src'),expected);
   await page.getByRole('button',{name:'關閉播放器'}).click();
  }
  assert.equal(await page.locator('a[href^="javascript:"],a[href^="data:"]').count(),0);
  assert.equal(await page.getByRole('button',{name:'未知影片',exact:true}).count(),0);
  console.log(`PASS Unicode literal/encoded timestamps and manifest lookup in ${isStatic?'static':'local'} mode`);
 }finally{await page.close();}
}
async function mermaidStaysLocal(browser, base) {
 const page=await browser.newPage();
 try {
  await fixture(page);
  const remote=[];
  await page.route('https://evil.example/**',route=>{remote.push(route.request().url());route.abort();});
  const diagram=[
   '```mermaid\n%%{init: {"themeCSS": ".node rect { fill: url(https://evil.example/theme) }"}}%%\nflowchart LR\n  A["<img src=\'https://evil.example/label.png\' width=\'20\'> 標籤"] --> B["下一步"]\n```',
   '```mermaid\nflowchart TD\n  C@{ img: "https://evil.example/shape.png", label: "圖", pos: "t", w: 60, h: 60, constraint: "on" }\n```',
   '![遠端圖](https://evil.example/md.png)',
  ].join('\n\n');
  await page.route('**/api/courses/fixture/decks/deck/notes/1',route=>json(route,{markdown:diagram,meta,review:null}));
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.locator('.mermaid-block svg').first().waitFor();
  await page.waitForTimeout(1500);
  assert.deepEqual(remote,[]);
  // The label diagram renders; the image-shape one may fall back to source text once its image is blocked.
  assert.equal(await page.locator('.mermaid-block').count(),2);
  assert.equal(await page.locator('.mermaid-block img, .mermaid-block image').count(),0);
  console.log('PASS mermaid and markdown images never load remote URLs');
 }finally{await page.close();}
}
async function uploadBeforeLeave(browser, base) {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 try {
  const state=await fixture(page);
  let release;
  const held=new Promise(resolve=>{release=resolve;});
  let uploads=0;
  await page.route('**/api/courses/fixture/decks/deck/assets',async route=>{uploads++;await held;await json(route,{path:'assets/late-0123456789.png'});});
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  const editor=page.locator('.cm-content');
  await editor.waitFor();
  await editor.evaluate(element=>{
   const data=new DataTransfer();data.items.add(new File([new Uint8Array([137,80,78,71])],'late.png',{type:'image/png'}));
   element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
  });
  await page.getByText('圖片上傳中…').waitFor();
  await page.getByRole('button',{name:'下一頁'}).click();
  await page.getByRole('dialog').getByText('還有圖片在上傳').waitFor();
  await page.getByRole('button',{name:'儲存並離開',exact:true}).click();
  await page.getByText('等圖片上傳完成再儲存…').waitFor();
  assert.equal(state.requests.filter(r=>r.method==='PUT').length,0,'must not save while the upload is pending');
  assert(page.url().endsWith('/1'));
  release();
  await page.waitForURL('**/2');
  const puts=state.requests.filter(r=>r.method==='PUT');
  assert.equal(puts.length,1);
  const saved=JSON.parse(puts[0].body).markdown;
  assert(saved.includes('](assets/late-0123456789.png)'),saved);
  assert(!saved.includes('上傳中'),saved);
  // Discarding while an upload is pending cancels it; a late reply must not touch the next page's draft.
  await page.getByRole('button',{name:'上一頁'}).click();await page.waitForURL('**/1');
  let releaseSecond;
  const heldSecond=new Promise(resolve=>{releaseSecond=resolve;});
  await page.unroute('**/api/courses/fixture/decks/deck/assets');
  await page.route('**/api/courses/fixture/decks/deck/assets',async route=>{await heldSecond;await json(route,{path:'assets/stale-0123456789.png'}).catch(()=>{});});
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await editor.evaluate(element=>{
   const data=new DataTransfer();data.items.add(new File([new Uint8Array([137,80,78,71])],'stale.png',{type:'image/png'}));
   element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
  });
  await page.getByRole('button',{name:'下一頁'}).click();
  await page.getByRole('button',{name:'不儲存',exact:true}).click();await page.waitForURL('**/2');
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await editor.waitFor();
  releaseSecond();
  await page.waitForTimeout(500);
  assert(!(await editor.innerText()).includes('stale-0123456789'),'stale upload must not edit the next note');
  assert.equal(state.requests.filter(r=>r.method==='PUT').length,1);
  console.log('PASS saving waits for pending image uploads; stale uploads never edit another note');
 }finally{await page.close();}
}
async function landscapeOverlays(browser, base) {
 const context=await browser.newContext({viewport:{width:844,height:390}});
 await context.addInitScript(()=>localStorage.setItem('marginalia:panes',JSON.stringify({slides:true,notes:true,agent:true})));
 const page=await context.newPage();
 try {
  await fixture(page);
  const many=['claude','codex-a','codex-b','codex-c'].map((id,i)=>({...account,id,provider:i?'codex':'claude',label:i?`帳號 ${i}`:'Claude',efforts:i?['low','medium','high']:['low','medium','high','xhigh','max'],models:i?[{id:'gpt-5',label:'gpt-5'}]:[{id:'opus',label:'Opus'},{id:'sonnet',label:'Sonnet'},{id:'haiku',label:'Haiku'}]}));
  await page.route('**/api/agents/accounts',route=>json(route,many));
  const inView=async(locator)=>{const box=await locator.boundingBox();return box&&box.y>=0&&box.y+box.height<=390;};
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.locator('aside[aria-label="AI 助教"] header button[aria-haspopup]').first().click();
  const manage=page.getByRole('button',{name:'管理帳號連線'});
  await manage.waitFor();
  const popup=page.locator('[role="dialog"]').filter({has:manage});
  const box=await popup.boundingBox();
  assert(box.y>=0&&box.y+box.height<=390,`model menu must fit the viewport: ${JSON.stringify(box)}`);
  await popup.evaluate(element=>{element.scrollTop=element.scrollHeight;});
  assert(await inView(manage),'管理帳號連線 must be reachable by scrolling the menu');
  await page.keyboard.press('Escape');
  await page.goto(base+'/c/fixture');
  await page.getByRole('button',{name:'產生筆記'}).click();
  const dialog=page.getByRole('dialog');
  await dialog.waitFor();
  await page.waitForTimeout(300);
  const dbox=await dialog.boundingBox();
  assert(dbox.y>=0&&dbox.y+dbox.height<=390,`dialog must fit the viewport: ${JSON.stringify(dbox)}`);
  assert(await inView(dialog.getByRole('button',{name:'關閉'})),'close button visible');
  await dialog.evaluate(element=>{element.scrollTop=element.scrollHeight;});
  assert(await inView(dialog.getByRole('button',{name:'開始'})),'start button reachable');
  console.log('PASS overlays fit a landscape phone (844×390)');
 }finally{await context.close();}
}
async function uploadCancelledByLayout(browser, base) {
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addInitScript(()=>localStorage.setItem('marginalia:panes',JSON.stringify({slides:true,notes:true,agent:false})));
 const page=await context.newPage();
 try {
  const state=await fixture(page);
  const holds=[];
  await page.route('**/api/courses/fixture/decks/deck/assets',async route=>{await new Promise(resolve=>holds.push(resolve));await json(route,{path:'assets/late-0123456789.png'}).catch(()=>{});});
  const editor=page.locator('.cm-content');
  const paste=()=>editor.evaluate(element=>{
   const data=new DataTransfer();data.items.add(new File([new Uint8Array([137,80,78,71])],'slow.png',{type:'image/png'}));
   element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
  });
  const puts=()=>state.requests.filter(r=>r.method==='PUT').map(r=>JSON.parse(r.body).markdown);
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await editor.fill('保留的文字');
  await editor.press('End');
  // A: collapse the notes pane while the image uploads, then reopen it.
  await paste();
  await page.getByText('圖片上傳中…').waitFor();
  await page.locator('body > div header').first().getByRole('button',{name:'筆記',exact:true}).click();
  await page.getByText('圖片上傳已取消').first().waitFor();
  await page.locator('body > div header').first().getByRole('button',{name:'筆記',exact:true}).click();
  await editor.waitFor();
  for(const release of holds.splice(0))release();
  await page.waitForTimeout(300);
  assert.equal(await editor.innerText(),'保留的文字','the placeholder is gone and the draft kept');
  await editor.press('Control+s');
  await page.getByText(/已儲存/).waitFor();
  assert.deepEqual(puts(),['保留的文字']);
  // B: cross the phone breakpoint while the image uploads.
  await editor.press('End');
  await paste();
  await page.getByText('圖片上傳中…').waitFor();
  await page.setViewportSize({width:390,height:844});
  await editor.waitFor();
  for(const release of holds.splice(0))release();
  await page.waitForTimeout(300);
  assert(!(await editor.innerText()).includes('上傳中'),'no placeholder after the layout change');
  await page.setViewportSize({width:1440,height:1000});
  await editor.waitFor();
  // C: a placeholder that somehow remains (typed, pasted as text) blocks saving.
  await editor.fill('有殘留 ![上傳中：x.png #9]()');
  await editor.press('Control+s');
  await page.getByText('筆記裡還有沒上傳完成的圖片').waitFor();
  assert(puts().every(markdown=>!markdown.includes('上傳中')),JSON.stringify(puts()));
  console.log('PASS uploads cancelled by collapsing or resizing restore the draft; placeholders are never saved');
 }finally{await context.close();}
}
async function run() {
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',args:['--no-sandbox']});
 const errors=[];
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>localStorage.setItem('marginalia:panes',JSON.stringify({slides:true,notes:true,agent:true})));
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  const state=await fixture(page);
  await page.goto(local+'/c/fixture/d/deck/1');
  await page.locator(NOTES+' .timestamp').first().waitFor();
  assert.equal(await page.locator('section[aria-label="投影片"] img[alt^="第 1 頁"]').getAttribute('src'),'/fixture.svg');
  assert.equal(await page.locator(NOTES+' a[href^="mailto:"]').count(),0);
  assert.equal(await page.locator(NOTES+' script,'+NOTES+' .prose-note img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  // Review records render as cards, never as JSON.
  await page.getByRole('tab',{name:/筆記檢查/}).click();
  await page.getByText('時間點對不上老師講的內容').waitFor();
  await page.getByText('需要修正',{exact:true}).waitFor();
  await page.getByText('已自動修正 1 項').waitFor();
  assert(!(await page.locator(NOTES).innerText()).includes('"findings"'));
  await page.getByRole('tab',{name:'筆記',exact:true}).click();
  // Draft protection.
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  const editor=page.locator('.cm-content');
  await editor.fill('尚未儲存的草稿');
  await page.getByText('有尚未儲存的修改').waitFor();
  await editor.press('ArrowRight');assert(page.url().endsWith('/1'));
  await page.getByRole('button',{name:'下一頁'}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'繼續編輯'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  assert.equal(await editor.innerText(),'尚未儲存的草稿');
  // Pasting an image uploads it and inserts the assets/ path.
  await editor.evaluate(element=>{
   const data=new DataTransfer();data.items.add(new File([new Uint8Array([137,80,78,71])],'pasted.png',{type:'image/png'}));
   element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
  });
  await page.waitForFunction(()=>document.querySelector('.cm-content')?.innerText.includes('](assets/pasted-0123456789.png)'));
  await editor.press('Control+s');
  await page.getByText('儲存中…').waitFor();
  await page.getByText(/已儲存/).waitFor();
  assert(JSON.parse(state.requests.find(r=>r.method==='PUT').body).markdown.startsWith('尚未儲存的草稿'));
  await page.getByRole('button',{name:'完成',exact:true}).click();
  await page.getByText('你改過',{exact:true}).waitFor();
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await editor.fill(markdown);
  await page.getByRole('button',{name:'儲存',exact:true}).click();
  await page.getByText(/已儲存/).waitFor();
  await page.getByRole('button',{name:'完成',exact:true}).click();
  await page.locator(NOTES+' button.timestamp').first().click();
  assert((await page.locator('video').getAttribute('src')).endsWith('/files/fixture/materials/test.mp4'));
  await page.getByRole('button',{name:'關閉播放器'}).click();
  // Region must use fractional coordinates relative to the displayed image.
  const bounds=await page.locator('section[aria-label="投影片"] img[alt^="第 1 頁"]').boundingBox();
  await page.mouse.move(bounds.x+bounds.width*.2,bounds.y+bounds.height*.2);await page.mouse.down();
  await page.mouse.move(bounds.x+bounds.width*.6,bounds.y+bounds.height*.6);await page.mouse.up();
  await page.getByText('投影片框選範圍').waitFor();
  await page.getByRole('button',{name:'口試練習',exact:true}).click();
  await page.getByLabel('輸入問題').fill('測試區域');
  await page.getByRole('button',{name:'送出',exact:true}).click();
  await page.getByText('合成串流回覆',{exact:true}).waitFor();
  const chat=JSON.parse(state.requests.find(r=>r.path==='/api/agents/chat').body);
  assert.equal(chat.mode,'interview');assert.equal(chat.context.deck,'deck');assert.equal(chat.context.slide,1);
  assert(Math.abs(chat.context.region.x-.2)<.01);assert(Math.abs(chat.context.region.w-.4)<.01);
  await page.getByRole('button',{name:'下一頁'}).click();await page.waitForURL('**/2');
  await page.locator(NOTES).getByText('第二頁原始筆記',{exact:true}).waitFor();
  await page.getByText('合成串流回覆',{exact:true}).waitFor();
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await editor.fill('應被放棄的第二頁草稿');
  await page.getByText('有尚未儲存的修改').waitFor();
  assert(await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;}));
  await page.getByRole('button',{name:'上一頁'}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'不儲存',exact:true}).click();await page.waitForURL('**/1');
  await page.locator(NOTES+' .timestamp').first().waitFor();
  if(process.env.WEB_SCREENSHOTS){fs.mkdirSync(process.env.WEB_SCREENSHOTS,{recursive:true});await page.waitForTimeout(4500);await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/reader-desktop.png'});}
  await page.setViewportSize({width:375,height:812});
  await page.getByRole('tab',{name:'筆記',exact:true}).first().click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  if(process.env.WEB_SCREENSHOTS){await page.waitForTimeout(600);await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/reader-mobile.png'});}
  // Selecting note text offers 問助教, which carries the selection into the chat.
  await page.locator(NOTES+' .prose-note h1').evaluate(element=>{
   const range=document.createRange();range.selectNodeContents(element);
   const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
  });
  await page.getByRole('button',{name:'問助教'}).click();
  await page.getByLabel('輸入問題').fill('測試選取文字');
  await page.getByRole('button',{name:'送出',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.prose-chat').length===2&&!!document.querySelector('[aria-label="送出"]'));
  const selectionChat=JSON.parse(state.requests.filter(r=>r.path==='/api/agents/chat').at(-1).body);
  assert.deepEqual(selectionChat.context.selection,{text:'合成筆記',source:'note'});
  await page.getByRole('link',{name:`回到${info.title}`}).click();
  await page.getByRole('heading',{name:info.title,exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  await page.locator('input[type=file]').setInputFiles({name:'tiny.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF fixture')});
  await page.getByText('已匯入 1 個檔案',{exact:true}).waitFor();
  const upload=state.requests.find(r=>r.path.endsWith('/upload'));
  assert(upload.headers['content-type'].includes('multipart/form-data; boundary='));assert(upload.body.includes('name="files[]"'));
  await page.getByRole('button',{name:'重新掃描'}).click();await page.getByText('掃描完成',{exact:true}).waitFor();
  await page.getByRole('button',{name:'產生筆記'}).click();
  await page.getByRole('dialog').getByRole('button',{name:'開始'}).click();
  await page.waitForFunction(()=>window.sources.length===1);
  await page.evaluate(job=>window.sources[0].emit('job',{...job,progress:.5,message:'執行中'}),state.job);
  await page.getByText('50%',{exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.sources.length),1);
  state.job.progress=1;state.job.state='done';state.job.message='已完成';
  await page.evaluate(()=>window.sources[0].emit('open',{}));
  await page.getByText('100%',{exact:true}).waitFor();assert(state.jobReads()>=2);assert(await page.evaluate(()=>window.sources[0].closed));
  await context.close();
  const staticPage=await browser.newPage({viewport:{width:1440,height:1000}});staticPage.on('pageerror',e=>errors.push(e.message));
  const staticState=await fixture(staticPage,true);
  await staticPage.goto(preview+'/c/fixture/d/deck/1');
  await staticPage.locator(NOTES+' button.timestamp').first().waitFor();
  assert.equal(await staticPage.getByRole('button',{name:'編輯',exact:true}).count(),0);
  assert.equal(await staticPage.locator('aside[aria-label="AI 助教"],.cm-content').count(),0);
  assert.equal(staticState.requests.length,0);
  course.info.videoUrls={};
  await staticPage.reload();await staticPage.locator(NOTES+' .prose-note').waitFor();
  assert.equal(await staticPage.locator('button.timestamp').count(),0);
  assert((await staticPage.locator(NOTES+' .prose-note').innerText()).includes('00:12'));
  await mermaidStaysLocal(browser,local);
  await uploadBeforeLeave(browser,local);
  await landscapeOverlays(browser,local);
  await uploadCancelledByLayout(browser,local);
  await unicodeVideoLinks(browser,local,false);
  await unicodeVideoLinks(browser,preview,true);
  assert.deepEqual(errors,[]);
  console.log('PASS: local/static contracts, draft protection, review cards, image paste, real images/video source, region/chat SSE, upload/scan, stable job SSE/reconnect, mobile overflow, URL sanitization');
 } finally {await browser.close();}
}
run().catch(error=>{console.error(error);process.exitCode=1;});
