/* Synthetic OFFLINE browser adapter. No network, CUA or real Gemini interaction. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createGeminiWebBridge, geminiUtf8Sha256 } = require('./browser_bridge.js');
const { createHash } = require('node:crypto');

const ui = { promptName: 'synthetic prompt', sendName: 'synthetic send',
  stopName: 'synthetic stop', copyName: 'synthetic copy', responseSelector: 'synthetic-reply-turn',
  userSelector: 'synthetic-user-turn', replyTextSelector: 'synthetic-body',
  modelButtonName: 'synthetic mode', requiredModeText: 'Argon' };
const request = () => ({ task_id: 'synthetic-task', request_id: 'synthetic-task-b-1',
  stage: 'B', kind: 'baseline', question_sha256: 'a'.repeat(64), request_sha256: 'b'.repeat(64),
  prompt: 'SYNTHETIC synthetic-task synthetic-task-b-1 中文\n多行' });

class FakeTab {
  constructor(options = {}) {
    this.id = 'synthetic-tab';
    this.state = { url: 'about:blank', prompt: '', users: [], replies: 0, raw: '',
      busy: false, copy: false, sends: 0, model: 'synthetic Argon 中等', ...options };
    this.playwright = {
      domSnapshot: async () => 'SYNTHETIC SNAPSHOT',
      getByRole: (role, spec) => this.control(spec.name),
      locator: selector => this.locator(selector),
    };
  }
  async goto(url) { this.state.url = url; }
  async url() { return this.state.url; }
  async markHandoff() {}
  control(name, scoped = false) {
    const state = this.state;
    const isPrompt = name === ui.promptName;
    return {
      count: async () => 1,
      isEnabled: async () => true,
      isVisible: async () => name === ui.stopName ? state.busy
        : name === ui.copyName ? (scoped && state.copy) : true,
      getAttribute: async () => state.model,
      innerText: async () => isPrompt ? state.prompt : state.model,
      evaluate: async fn => fn({ innerText: state.prompt }),
      fill: async value => { state.prompt = value; },
      click: async () => {
        if (name !== ui.sendName) return;
        state.sends++;
        state.users = [state.prompt];
        state.url = 'https://gemini.google.com/app/synthetic-conversation';
        if (state.throwAfterSend) throw new Error('SYNTHETIC acknowledgment lost');
      },
    };
  }
  locator(selector) {
    const state = this.state;
    const result = {
      count: async () => selector === ui.userSelector ? state.users.length
        : selector === ui.responseSelector ? state.replies : selector === ui.replyTextSelector ? 1 : 0,
      last: () => result,
      textContent: async () => selector === ui.userSelector ? state.users.at(-1) : state.raw,
      getByRole: (role, spec) => this.control(spec.name, true),
      locator: child => this.locator(child),
    };
    return result;
  }
  finish(raw) {
    this.state.replies = 1; this.state.raw = raw; this.state.copy = true; this.state.busy = false;
  }
}
function setup(options) {
  const tab = new FakeTab(options);
  const bridge = createGeminiWebBridge({ tabs: { new: async () => tab } }, ui);
  const req = request();
  req.request_sha256 = geminiUtf8Sha256(req.prompt);
  return { bridge, tab, req };
}
async function send(fixture) {
  await fixture.bridge.open(fixture.req);
  await fixture.bridge.draft(fixture.req.request_id);
  await fixture.bridge.send(fixture.req.request_id);
}
const goodResponse = () => JSON.stringify({ task_id: 'synthetic-task', question_sha256: 'a'.repeat(64) });

test('fresh page, full prompt and scoped completion produce capture only after two observations', async () => {
  const f = setup(); await send(f); f.tab.finish(goodResponse());
  assert.equal((await f.bridge.observe(f.req.request_id)).status, 'WAITING');
  assert.equal((await f.bridge.observe(f.req.request_id)).status, 'CAPTURE_READY');
  const capture = f.bridge.capture(f.req.request_id);
  assert.equal(capture.raw_response, goodResponse());
  assert.equal(capture.fresh_context, true);
  assert.equal(f.tab.state.sends, 1);
});
test('history in a supposedly new page prevents sending', async () => {
  const f = setup({ users: ['SYNTHETIC existing conversation'] });
  await assert.rejects(f.bridge.open(f.req), /history/);
  assert.equal(f.tab.state.sends, 0);
});
test('streaming reply cannot complete even when copy and valid JSON are present', async () => {
  const f = setup(); await send(f); f.tab.finish(goodResponse()); f.tab.state.busy = true;
  await f.bridge.observe(f.req.request_id);
  assert.equal((await f.bridge.observe(f.req.request_id)).status, 'WAITING');
  assert.throws(() => f.bridge.capture(f.req.request_id), /not observed complete/);
});
test('copy outside current response does not count', async () => {
  const f = setup(); await send(f); f.tab.finish(goodResponse()); f.tab.state.copy = false;
  await f.bridge.observe(f.req.request_id);
  assert.equal((await f.bridge.observe(f.req.request_id)).status, 'WAITING');
});
test('truncated or wrong-task output cannot complete', async () => {
  const f = setup(); await send(f);
  for (const raw of ['{"task_id":', JSON.stringify({ task_id: 'wrong', question_sha256: 'a'.repeat(64) })]) {
    f.tab.finish(raw); await f.bridge.observe(f.req.request_id);
    assert.equal((await f.bridge.observe(f.req.request_id)).status, 'WAITING');
  }
});
test('send error never permits a second click; original reply can still be observed', async () => {
  const f = setup({ throwAfterSend: true });
  await f.bridge.open(f.req); await f.bridge.draft(f.req.request_id);
  await assert.rejects(f.bridge.send(f.req.request_id), /acknowledgment lost/);
  await assert.rejects(f.bridge.send(f.req.request_id), /cannot be repeated/);
  f.tab.finish(goodResponse()); await f.bridge.observe(f.req.request_id);
  assert.equal((await f.bridge.observe(f.req.request_id)).status, 'CAPTURE_READY');
  assert.equal(f.tab.state.sends, 1);
});
test('model changes after draft prevent send', async () => {
  const f = setup(); await f.bridge.open(f.req); await f.bridge.draft(f.req.request_id);
  f.tab.state.model = 'SYNTHETIC another model';
  await assert.rejects(f.bridge.send(f.req.request_id), /Model label changed/);
  assert.equal(f.tab.state.sends, 0);
});
test('capture UTF-8 hash matches Node SHA-256 for ASCII, Chinese, emoji, escapes and long blocks', () => {
  for (const value of ['', 'abc', '中文😀\n"quoted"\\path', 'long'.repeat(10000)]) {
    assert.equal(geminiUtf8Sha256(value), createHash('sha256').update(value, 'utf8').digest('hex'));
  }
});
test('queued prompt transfer corruption is rejected before creating a tab', async () => {
  const f = setup(); f.req.prompt += ' corrupted';
  await assert.rejects(f.bridge.open(f.req), /prompt\/hash mismatch/);
  assert.equal(f.tab.state.sends, 0);
});
test('a never-attempted queued request can adopt its verified empty tab after a reset', async () => {
  const f = setup({ url: 'https://gemini.google.com/app' });
  const journal = { request_id: f.req.request_id, request_sha256: f.req.request_sha256, status: 'QUEUED' };
  const bound = await f.bridge.adoptFresh(f.req, f.tab, journal);
  assert.equal(bound.tab_id, f.tab.id);
  await f.bridge.draft(f.req.request_id); await f.bridge.send(f.req.request_id);
  assert.equal(f.tab.state.sends, 1);
});
test('fresh adoption rejects sending, uncertain, attempted, wrong-tab and wrong-hash journals', async () => {
  for (const change of [{ status: 'SENDING' }, { status: 'SEND_UNKNOWN' },
    { send_intent_at: '2026-10-16T00:00:00Z' }, { tab_id: 'another-tab' },
    { request_sha256: '0'.repeat(64) }]) {
    const f = setup({ url: 'https://gemini.google.com/app' });
    const journal = { request_id: f.req.request_id, request_sha256: f.req.request_sha256,
      status: 'QUEUED', ...change };
    await assert.rejects(f.bridge.adoptFresh(f.req, f.tab, journal), /never-attempted/);
    assert.equal(f.tab.state.sends, 0);
  }
});
test('fresh adoption rejects existing history and a duplicate local binding', async () => {
  const f = setup({ url: 'https://gemini.google.com/app', users: ['SYNTHETIC history'] });
  const journal = { request_id: f.req.request_id, request_sha256: f.req.request_sha256, status: 'QUEUED' };
  await assert.rejects(f.bridge.adoptFresh(f.req, f.tab, journal), /history/);
  f.tab.state.users = [];
  await f.bridge.adoptFresh(f.req, f.tab, journal);
  await assert.rejects(f.bridge.adoptFresh(f.req, f.tab, journal), /never-attempted/);
});

test('framed nested JSON is extracted while ambiguous, duplicate and truncated data fail closed', () => {
  const {geminiJsonText,geminiParseJson}=require('./browser_bridge.js');
  const value={proposal:'中文😀\n```json\n{"inner":"}"}\n```',other:[{x:1}]};
  const raw=JSON.stringify(value);
  for(const framed of [raw,'好的\n```json\n'+raw+'\n```\n谢谢','\uFEFF'+raw])
    assert.deepEqual(geminiParseJson(geminiJsonText(framed)),value);
  for(const bad of ['{} {}','{"x":1,}','{"x":NaN}','{"x":1,"x":2}','{"x":1,"\\u0078":2}','{"x":','[{"x":1}]','{]'])
    assert.throws(()=>geminiJsonText(bad));
});

test('contenteditable uses complete text even when value is empty and preserves meaningful whitespace', () => {
  const {geminiInputText}=require('./browser_bridge.js');
  const text='header\n\n  indented code  \n';
  assert.equal(geminiInputText({isContentEditable:true,value:'',innerText:text}),text);
  assert.equal(geminiInputText({tagName:'TEXTAREA',value:text,innerText:'wrong'}),text);
  assert.notEqual(geminiInputText({isContentEditable:true,innerText:text+'mutation'}),text);
});

test('bilingual names escape regex metacharacters and match only whole control labels', () => {
  const {geminiUiName}=require('./browser_bridge.js');
  const matcher=geminiUiName(['复制','Copy','Copy response','Send (Ctrl+Enter)']);
  for(const label of ['复制','Copy','Copy response','Send (Ctrl+Enter)']) assert.ok(matcher.test(label));
  for(const label of ['Copy everything','Do not Copy','Send CtrlEnter']) assert.ok(!matcher.test(label));
});

test('DOM bridge completes full send/capture using either Chinese or English control names', async () => {
  const aliases={promptName:['为 Gemini 输入提示','Enter a prompt for Gemini'],sendName:['发送','Send'],
    stopName:['停止回答','Stop generating'],copyName:['复制','Copy'],modelButtonName:['模式','Mode']};
  for(const locale of [0,1]) {
    const tab=new FakeTab(), control=tab.control.bind(tab);
    tab.control=(name,scoped)=>{
      if(name instanceof RegExp) {
        const key=Object.keys(aliases).find(key=>name.test(aliases[key][locale]));
        assert.ok(key,'locator must match a real control in the selected language');
        return control(ui[key],scoped);
      }
      return control(name,scoped);
    };
    const bridge=createGeminiWebBridge({tabs:{new:async()=>tab}},{...ui,...aliases});
    const req=request();req.request_sha256=geminiUtf8Sha256(req.prompt);
    const f={tab,bridge,req};await send(f);tab.finish(goodResponse());
    await bridge.observe(req.request_id);assert.equal((await bridge.observe(req.request_id)).status,'CAPTURE_READY');
    assert.equal(bridge.capture(req.request_id).raw_response,goodResponse());assert.equal(tab.state.sends,1);
  }
});

test('first-line sentinel binds a user echo collapsed to 120 characters', async () => {
  const f=setup();f.req.prompt=`[TASK_ID:${f.req.task_id} REQUEST_ID:${f.req.request_id}] `+'raw source '.repeat(4000);
  f.req.request_sha256=geminiUtf8Sha256(f.req.prompt);await send(f);
  f.tab.state.users=[f.tab.state.users[0].slice(0,120)];f.tab.finish(goodResponse());
  await f.bridge.observe(f.req.request_id);assert.equal((await f.bridge.observe(f.req.request_id)).status,'CAPTURE_READY');
});
