// Run against local Vite (:5173) and a pnpm build preview (:5191).
// Requires Playwright on NODE_PATH. Local API data are mocked; static data must come from real exports.
// (cd server && uv run python ../scripts/static-fixture.py <fixture-courses>)
// MARGINALIA_COURSES=<fixture-courses> pnpm build
// WEB_STATIC_ONLY=1 WEB_STATIC_URL=http://127.0.0.1:5178/<base> node scripts/web-regression.cjs
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
async function fixture(page) {
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
  if(path.endsWith('/exams'))return json(route,[]);
  if(path==='/api/agents/chat') return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"start","chatId":"fixture-chat"}\r\n\r\ndata: {"type":"text","delta":"合成串流回覆"}\r\n\r\ndata: {"type":"done","chatId":"fixture-chat"}\r\n\r\n'});
  if(path.endsWith('/decks/deck/assets'))return json(route,{path:'assets/pasted-0123456789.png'});
  if(path.endsWith('/upload'))return json(route,{saved:['materials/tiny.pdf'],manifest:{decks:[],videos:[]}});
  if(path.endsWith('/scan'))return json(route,{decks:[],videos:[]});
  if(path.endsWith('/jobs'))return json(route,{id:job.id});
  if(path==='/api/jobs/job-1'){jobReads++;return json(route,job);}
  throw new Error(`Unhandled fixture: ${path}`);
 });
 return {requests,job,jobReads:()=>jobReads};
}
async function exportedStatic(browser) {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const api=[], errors=[], failures=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.status()>=400)failures.push(r.url());});
 await page.route('**/api/**',route=>{api.push(route.request().url());return route.abort();});
 await page.route('https://example.com/**',route=>route.abort());
 const noEditing=async()=>{
  assert.equal(await page.locator('aside[aria-label="AI 助教"],.cm-content,input[type=file]').count(),0);
  assert.equal(await page.getByRole('tab',{name:'筆記檢查',exact:true}).count(),0);
  for(const name of ['編輯','產生筆記','重新掃描','AI 助教','問助教'])
   assert.equal(await page.getByRole('button',{name,exact:true}).count(),0);
 };
 try {
  // APIRequestContext bypasses page.route: these probes exercise the actual preview server.
  for(const path of ['/files/fixture/generated/decks/deck/slides/001.webp','/files/fixture/generated/decks/deck/thumbs/001.webp','/files/fixture/notes/deck/assets/架構圖.svg']){
   const response=await page.request.get(preview+path);
   assert.equal(response.status(),200,path);
   assert.match(response.headers()['content-type'],/^image\//);
   assert((await response.body()).length>0);
  }
  const origin=new URL(preview).origin;
  for(const url of new Set([origin+'/api/health',preview+'/api/health',preview+'/files/unexported/materials/secret.mp4'])){
   const response=await page.request.get(url,{headers:{Accept:'application/json'}});
   assert.equal(response.status(),404,url);
  }
  console.log('PASS actual preview HTTP: exported slides/thumbs/SVG return 200; API and unexported files return 404');
  await page.goto(preview+'/');
  await page.getByRole('heading',{name:'我的課程',exact:true}).waitFor();
  await noEditing();
  await page.goto(preview+'/c/fixture');
  await page.getByRole('heading',{name:'靜態驗證課程',exact:true}).waitFor();
  await noEditing();
  assert.equal(await page.locator('a[href*="/d/hidden/"]').count(),0);
  await page.goto(preview+'/c/fixture/d/deck/1');
  await page.locator(NOTES+' .mermaid-block svg').first().waitFor();
  await page.locator(NOTES+' mark').waitFor();
  await page.getByText('重點',{exact:true}).waitFor();
  assert.equal(await page.locator(NOTES+' button.timestamp').count(),3);
  assert(await page.locator(NOTES+' img').evaluateAll(imgs=>imgs.length>0&&imgs.every(i=>i.complete&&i.naturalWidth>0)));
  assert(await page.locator('img').evaluateAll(imgs=>imgs.every(i=>i.complete&&i.naturalWidth>0)));
  await noEditing();
  for(const [label,video] of [['中文影片','chinese'],['編碼影片','chinese'],['00:12','ascii']]){
   await page.getByRole('button',{name:label,exact:true}).first().click();
   assert.equal(await page.locator('video').getAttribute('src'),`https://example.com/public-videos/${video}.mp4`);
   await page.getByRole('button',{name:'關閉播放器'}).click();
  }
  await page.setViewportSize({width:375,height:812});
  await page.getByRole('tab',{name:'筆記',exact:true}).first().click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  await noEditing();
  await page.goto(preview+'/c/text-only/d/deck/1');
  await page.locator(NOTES+' .prose-note').waitFor();
  assert.equal(await page.locator('button.timestamp').count(),0);
  assert((await page.locator(NOTES+' .prose-note').innerText()).includes('00:12'));
  // Exam prep in the static reader: handout and quiz read-only, answers checked in the browser, no agent.
  // Preview answers unknown paths with index.html; what matters is that the upload's text is never served.
  for(const url of [preview+'/files/fixture/exams/midterm/uploads/secret-paper.md',preview+'/files/fixture/exams/midterm/attempts/'+'a'.repeat(32)+'.json']){
   const response=await page.request.get(url,{headers:{Accept:'application/json'}});
   assert(response.status()===404||!(await response.text()).includes('不可匯出'),url);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(preview+'/c/fixture');
  await page.getByRole('link',{name:/期中考/}).click();
  await page.waitForURL('**/exam/midterm/handout');
  await page.locator('.prose-note mark').waitFor();
  assert(await page.locator('.prose-note img[alt="投影片"]').evaluate(i=>i.complete&&i.naturalWidth>0));
  assert.equal(await page.locator('.prose-note img[alt="隱藏"]').count(),0);
  assert.equal(await page.getByRole('button',{name:'準備',exact:true}).count(),0);
  await noEditing();
  await page.getByRole('button',{name:'模擬考',exact:true}).click();
  await page.getByText('合成選擇題').waitFor();
  assert.equal(await page.getByText('合成詳解').count(),0);
  await page.getByLabel(/對/).check();
  await page.getByLabel('你的答案').fill('合成作答');
  await page.getByRole('button',{name:'交卷並對答案'}).click();
  await page.getByText('合成詳解').waitFor();
  await page.getByText('合成參考答案').waitFor();
  assert.equal(await page.getByRole('button',{name:/Agent/}).count(),0);
  assert(await page.evaluate(()=>JSON.parse(localStorage.getItem('marginalia.exam.fixture.midterm'))[0].score===2));
  await page.goto(preview+'/c/fixture/edit');
  await page.waitForURL(preview+'/');
  await noEditing();
  assert.deepEqual(api,[]);assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log('PASS actual static export: course/deck JSON, subpath, images, mermaid/highlight/callout, Unicode video URLs, text timestamps, mobile and read-only routes, exam handout/quiz with local checking');
 } finally {await page.close();}
}
async function unicodeVideoLinks(browser, base) {
 const page=await browser.newPage();
 try {
  await fixture(page);
  const unicodeMarkdown='[中文影片](video:課堂一?t=12) [編碼影片](video:%E8%AA%B2%E5%A0%82%E4%B8%80?t=24) [ASCII影片](video:video-b?t=12) [未知影片](video:不存在?t=12) [拒絕腳本](javascript:alert(1)) [拒絕資料](data:text/html,test)';
  const unicodeCourse={...course,info:{...info,videoUrls:{'課堂一':'https://example.com/public-videos/chinese.mp4','video-b':'https://example.com/public-videos/ascii.mp4'}},videos:[...course.videos,{id:'課堂一',source:'materials/chinese.mp4',title:'中文影片',duration:100}]};
  await page.route('**/api/courses/fixture',route=>json(route,unicodeCourse));
  await page.route('**/api/courses/fixture/decks/deck/notes/1',route=>json(route,{markdown:unicodeMarkdown,meta,review:null}));
  await page.route('**/files/fixture/**',route=>route.abort());
  await page.route('https://example.com/public-videos/**',route=>route.abort());
  await page.goto(base+'/c/fixture/d/deck/1');
  await page.getByRole('button',{name:'中文影片',exact:true}).waitFor();
  assert.equal(await page.locator(NOTES+' button.timestamp').count(),3);
  for(const [label,video] of [['中文影片','chinese'],['編碼影片','chinese'],['ASCII影片','ascii']]){
   await page.getByRole('button',{name:label,exact:true}).click();
   const expected=`/files/fixture/materials/${video==='ascii'?'test':video}.mp4`;
   assert.equal(await page.locator('video').getAttribute('src'),expected);
   await page.getByRole('button',{name:'關閉播放器'}).click();
  }
  assert.equal(await page.locator('a[href^="javascript:"],a[href^="data:"]').count(),0);
  assert.equal(await page.getByRole('button',{name:'未知影片',exact:true}).count(),0);
  console.log('PASS Unicode literal/encoded timestamps and manifest lookup in local mode');
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
// Exam prep: setup, handout with slide images and editing, mock exam answering, 對答案 and repeat agent grading.
async function examFlow(browser, base) {
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();
 const errors=[], requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('dialog',dialog=>dialog.accept());
 await page.route('**/fixture.svg',r=>r.fulfill({contentType:'image/svg+xml',body:image}));
 await page.route('**/files/fixture/generated/decks/deck/slides/*.webp',r=>r.fulfill({contentType:'image/svg+xml',body:image}));
 const exam={id:'midterm',title:'期中考',scope:{decks:['deck'],videos:[]},options:{minutes:30}};
 let sections=[{section:1,title:'行程與中斷',status:'generated',sources:['deck#1'],markdown:'> [!IMPORTANT]\n> ==中斷讓 CPU 先處理緊急事件==。\n\n![投影片一](slide:deck/1)\n\n![外部](https://example.com/x.png)'},
  {section:2,title:'記憶體管理',status:'generated',sources:[],markdown:'**Paging** 把記憶體切成固定大小。'}];
 const questions=[
  {id:'q1',type:'choice',origin:'past',prompt:'哪個會讓行程進入 waiting？',options:[{id:'A',text:'時間片用完'},{id:'B',text:'等待 I/O'}],answer:['B'],multiple:false,points:2,solution:'等待 I/O 時行程不能用 CPU。'},
  {id:'q2',type:'fill',origin:'new',prompt:'{{1}} 演算法可能造成 {{2}}。',blanks:[['SJF'],['starvation','飢餓']],points:4},
  {id:'q3',type:'short',origin:'new',prompt:'說明 context switch 的成本。',points:6,solution:'保存與載入 PCB。',rubric:[{point:'提到 PCB',points:6}]},
 ];
 const quiz={hash:'h1',questions};
 let attempt=null, gradings=0;
 await page.route('**/api/**',async route=>{
  const request=route.request(), path=new URL(request.url()).pathname, method=request.method();
  requests.push({path,method,body:request.postData()});
  if(path==='/api/courses/fixture')return json(route,course);
  if(path.endsWith('/alignment'))return json(route,{videos:{},segments:[]});
  if(path==='/api/courses/fixture/exams')return json(route,[{id:'midterm',title:'期中考',sectionCount:2,questionCount:3}]);
  if(path==='/api/courses/fixture/exams/midterm')return method==='PUT'?json(route,{...exam,...JSON.parse(request.postData())}):json(route,{exam,uploads:[{name:'past.png',kind:'image',size:10,url:'/fixture.svg'}],handout:sections.map(({markdown,...s})=>s),quiz:{questionCount:3,hash:'h1'}});
  const section=/\/handout\/(\d+)$/.exec(path);
  if(section){
   const n=Number(section[1]);
   if(method==='PUT'){const markdown=JSON.parse(request.postData()).markdown;sections=sections.map(s=>s.section===n?{...s,markdown,status:'edited'}:s);return json(route,{meta:{section:n,title:sections[n-1].title,status:'edited'}});}
   return json(route,{markdown:sections[n-1].markdown,meta:sections[n-1]});
  }
  if(path.endsWith('/decks/deck'))return json(route,{deck:course.decks[0],slides});
  if(path.endsWith('/quiz'))return json(route,quiz);
  if(path.endsWith('/midterm/attempts')){
   if(method==='GET')return json(route,[]);
   const answers=JSON.parse(request.postData()).answers;
   attempt={id:'a'.repeat(32),quizHash:'h1',submittedAt:meta.updatedAt,answers,gradings:{},
    results:{q1:{status:'correct',score:2,maxScore:2},q2:{status:'partial',score:2,maxScore:4},q3:{status:'pending',score:null,maxScore:6}},score:4,maxScore:12};
   return json(route,attempt);
  }
  if(path.endsWith('/grade')){
   const body=JSON.parse(request.postData());gradings++;
   const grading={id:`g${gradings}`,answer:body.answer,score:gradings===1?2:6,maxScore:6,verdict:gradings===1?'partial':'correct',summary:gradings===1?'少了 PCB':'完整',issues:gradings===1?[{quote:'要花時間',problem:'沒說花在哪裡',fix:'寫出保存 PCB'}]:[],missing:gradings===1?['提到 PCB']:[],createdAt:meta.updatedAt};
   attempt={...attempt,gradings:{q3:[...(attempt.gradings.q3??[]),grading]},results:{...attempt.results,q3:{status:grading.verdict,score:grading.score,maxScore:6}},score:4+grading.score};
   return json(route,{grading,attempt});
  }
  if(path.endsWith('/accounts'))return json(route,[account]);
  if(path.endsWith('/chats'))return json(route,[]);
  throw new Error(`Unhandled exam fixture: ${path}`);
 });
 try {
  await page.goto(base+'/c/fixture');
  await page.getByRole('heading',{name:'考前複習'}).waitFor();
  await page.getByRole('link',{name:/期中考/}).click();
  await page.waitForURL('**/exam/midterm/handout');
  await page.getByRole('heading',{name:/行程與中斷/}).waitFor();
  assert.equal(await page.locator('.prose-note img[alt="投影片一"]').getAttribute('src'),'/files/fixture/generated/decks/deck/slides/001.webp');
  assert.equal(await page.locator('.prose-note img[alt="外部"]').count(),0);
  assert.equal(await page.getByRole('navigation',{name:'目錄'}).getByRole('link').count(),2);
  // Edit a section with the note editor and save it.
  await page.getByRole('button',{name:'編輯',exact:true}).first().click();
  await page.locator('.cm-content').fill('改寫後的段落 ==重點==');
  await page.getByRole('button',{name:'完成',exact:true}).click();
  await page.getByText('改寫後的段落').waitFor();
  assert.equal(JSON.parse(requests.find(r=>r.method==='PUT'&&r.path.endsWith('/handout/1')).body).markdown,'改寫後的段落 ==重點==');
  if(process.env.WEB_SCREENSHOTS){fs.mkdirSync(process.env.WEB_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/exam-handout.png'});}
  // Setup tab lists uploads and saves scope.
  await page.getByRole('button',{name:'準備',exact:true}).click();
  await page.getByText('past.png').waitFor();
  // Mock exam: answer, submit, check.
  await page.getByRole('button',{name:'模擬考',exact:true}).click();
  await page.getByText('哪個會讓行程進入 waiting？').waitFor();
  assert.equal(await page.getByText('等待 I/O 時行程不能用 CPU。').count(),0); // solutions hidden before checking
  await page.getByLabel(/等待 I\/O/).check();
  await page.locator('input:not([type])').first().fill('sjf');
  await page.getByLabel('你的答案').fill('要花時間');
  await page.getByText('已作答 3 / 3').waitFor();
  await page.getByRole('button',{name:'交卷並對答案'}).click();
  await page.getByText('等待 I/O 時行程不能用 CPU。').waitFor();
  assert.deepEqual(JSON.parse(requests.find(r=>r.method==='POST'&&r.path.endsWith('/attempts')).body).answers,{q1:['B'],q2:['sjf',''],q3:'要花時間'});
  await page.getByRole('button',{name:'請 Agent 批改'}).click();
  await page.getByText('沒說花在哪裡').waitFor();
  await page.getByLabel('改寫答案').fill('要保存與載入 PCB');
  await page.getByRole('button',{name:'改寫後再批改'}).click();
  await page.getByText('第 2 次批改').waitFor();
  assert.equal(await page.getByText('第 1 次批改').count(),1);
  assert.equal(JSON.parse(requests.filter(r=>r.path.endsWith('/grade')).at(-1).body).answer,'要保存與載入 PCB');
  await page.getByRole('button',{name:'只看錯題'}).click();
  assert.equal(await page.getByText('哪個會讓行程進入 waiting？').count(),0);
  await page.setViewportSize({width:375,height:812});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  if(process.env.WEB_SCREENSHOTS)await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/exam-quiz-mobile.png'});
  assert.deepEqual(errors,[]);
  console.log('PASS exam prep: handout slide images and editing, mock exam answers, 對答案, repeat agent grading, mobile width');
 } finally {await context.close();}
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
  await exportedStatic(browser);
  await mermaidStaysLocal(browser,local);
  await uploadBeforeLeave(browser,local);
  await landscapeOverlays(browser,local);
  await uploadCancelledByLayout(browser,local);
  await unicodeVideoLinks(browser,local);
  await examFlow(browser,local);

  assert.deepEqual(errors,[]);
  console.log('PASS: local/static contracts, draft protection, review cards, image paste, real images/video source, region/chat SSE, upload/scan, stable job SSE/reconnect, mobile overflow, URL sanitization');
 } finally {await browser.close();}
}
(process.env.WEB_STATIC_ONLY ? (async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEB_BROWSER_PATH});
 try {await exportedStatic(browser);} finally {await browser.close();}
})() : run()).catch(error=>{console.error(error);process.exitCode=1;});
