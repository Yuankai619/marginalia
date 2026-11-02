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
   return json(route,path.endsWith('/1')?saved:{markdown:'第二頁原始筆記',meta,review:null});
  }
  if(path.endsWith('/transcript'))return json(route,{segments:[{start:14,end:18,text:'合成逐字稿'}],partial:false});
  if(path.endsWith('/accounts'))return json(route,[account]);
  if(path.endsWith('/chats'))return json(route,[]);
  if(path==='/api/agents/chat') return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"start","chatId":"fixture-chat"}\r\n\r\ndata: {"type":"text","delta":"合成串流回覆"}\r\n\r\ndata: {"type":"done","chatId":"fixture-chat"}\r\n\r\n'});
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
async function run() {
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',args:['--no-sandbox']});
 const errors=[];
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  const state=await fixture(page);
  await page.goto(local+'/c/fixture/d/deck/1');
  await page.locator('.note-column .timestamp').waitFor();
  assert.equal(await page.locator('.slide-canvas img').getAttribute('src'),'/fixture.svg');
  assert.equal(await page.locator('.note-column a[href^="mailto:"]').count(),0);
  assert.equal(await page.locator('.note-column script,.note-column img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await page.locator('.editor').fill('尚未儲存的草稿');
  await page.locator('.editor').press('ArrowRight');assert(page.url().endsWith('/1'));
  await page.getByRole('button',{name:'下一頁'}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'繼續編輯'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  assert.equal(await page.locator('.editor').inputValue(),'尚未儲存的草稿');
  await page.locator('.editor').press('Control+s');
  await page.waitForFunction(()=>document.querySelector('.editor')?.disabled);
  await page.locator('.status.edited').waitFor();
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await page.locator('.editor').fill(markdown);
  await page.getByRole('button',{name:'儲存',exact:true}).click();
  await page.locator('.note-column .timestamp').click();
  assert((await page.locator('video').getAttribute('src')).endsWith('/files/fixture/materials/test.mp4'));
  await page.getByRole('button',{name:'關閉播放器'}).click();
  // Region must use fractional coordinates relative to the displayed image.
  const bounds=await page.locator('.slide-canvas img').boundingBox();
  await page.mouse.move(bounds.x+bounds.width*.2,bounds.y+bounds.height*.2);await page.mouse.down();
  await page.mouse.move(bounds.x+bounds.width*.6,bounds.y+bounds.height*.6);await page.mouse.up();
  await page.getByRole('button',{name:'口試',exact:true}).click();
  await page.getByPlaceholder('問這一頁的概念…').fill('測試區域');
  await page.getByRole('button',{name:'傳送',exact:true}).click();
  await page.getByText('合成串流回覆',{exact:true}).waitFor();
  const chat=JSON.parse(state.requests.find(r=>r.path==='/api/agents/chat').body);
  assert.equal(chat.mode,'interview');assert.equal(chat.context.deck,'deck');assert.equal(chat.context.slide,1);
  assert(Math.abs(chat.context.region.x-.2)<.01);assert(Math.abs(chat.context.region.w-.4)<.01);
  await page.getByRole('button',{name:'下一頁'}).click();await page.waitForURL('**/2');
  await page.locator('.note-column').getByText('第二頁原始筆記',{exact:true}).waitFor();
  await page.getByText('合成串流回覆',{exact:true}).waitFor();
  await page.getByRole('button',{name:'編輯',exact:true}).click();
  await page.locator('.editor').fill('應被放棄的第二頁草稿');
  assert(await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;}));
  await page.getByRole('button',{name:'上一頁'}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'放棄修改',exact:true}).click();await page.waitForURL('**/1');
  await page.locator('.note-column .timestamp').waitFor();
  if(process.env.WEB_SCREENSHOTS){fs.mkdirSync(process.env.WEB_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/reader-desktop.png',fullPage:true});}
  await page.setViewportSize({width:375,height:812});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  if(process.env.WEB_SCREENSHOTS)await page.screenshot({path:process.env.WEB_SCREENSHOTS+'/reader-mobile.png',fullPage:true});
  await page.locator('.note-column .markdown').evaluate(element=>{
   const range=document.createRange();range.selectNodeContents(element.querySelector('h1'));
   const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
   element.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
  });
  await page.getByPlaceholder('問這一頁的概念…').fill('測試選取文字');
  await page.getByRole('button',{name:'傳送',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.messages .markdown').length===4&&!document.querySelector('.messages')?.textContent.includes('回覆中…'));
  const selectionChat=JSON.parse(state.requests.filter(r=>r.path==='/api/agents/chat').at(-1).body);
  assert.deepEqual(selectionChat.context.selection,{text:'合成筆記',source:'note'});
  await page.locator('.reader-heading a').click();
  await page.getByRole('heading',{name:info.title,exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),375);
  await page.locator('input[type=file]').setInputFiles({name:'tiny.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF fixture')});
  await page.getByText('檔案已匯入',{exact:true}).waitFor();
  const upload=state.requests.find(r=>r.path.endsWith('/upload'));
  assert(upload.headers['content-type'].includes('multipart/form-data; boundary='));assert(upload.body.includes('name="files[]"'));
  await page.getByRole('button',{name:'重新掃描'}).click();await page.getByText('掃描完成',{exact:true}).waitFor();
  await page.getByRole('button',{name:'開始生成'}).click();await page.waitForFunction(()=>window.sources.length===1);
  await page.evaluate(job=>window.sources[0].emit('job',{...job,progress:.5,message:'執行中'}),state.job);
  await page.getByText('50%',{exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.sources.length),1);
  state.job.progress=1;state.job.state='done';state.job.message='已完成';
  await page.evaluate(()=>window.sources[0].emit('open',{}));
  await page.getByText('100%',{exact:true}).waitFor();assert(state.jobReads()>=2);assert(await page.evaluate(()=>window.sources[0].closed));
  await page.close();
  const staticPage=await browser.newPage();staticPage.on('pageerror',e=>errors.push(e.message));
  const staticState=await fixture(staticPage,true);
  await staticPage.goto(preview+'/c/fixture/d/deck/1');
  await staticPage.locator('.note-column .timestamp').waitFor();
  assert.equal(await staticPage.locator('.agent,.editor,.note-tools button').count(),0);
  assert.equal(staticState.requests.length,0);
  course.info.videoUrls={};
  await staticPage.reload();await staticPage.locator('.note-column .markdown').waitFor();
  assert.equal(await staticPage.locator('.timestamp').count(),0);
  assert((await staticPage.locator('.note-column .markdown').innerText()).includes('00:12'));
  assert.deepEqual(errors,[]);
  console.log('PASS: local/static contracts, draft protection, real images/video source, region/chat SSE, upload/scan, stable job SSE/reconnect, mobile overflow, URL sanitization');
 } finally {await browser.close();}
}
run().catch(error=>{console.error(error);process.exitCode=1;});
