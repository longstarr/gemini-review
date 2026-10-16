/* Synthetic OFFLINE accessibility trees; no network or Gemini calls. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createGeminiAxSession } = require('./browser_ax_bridge.js');
const { geminiUtf8Sha256: hash } = require('./browser_bridge.js');
function fixture(options = {}, journalChanges = {}) {
  const req = { task_id: 'synthetic', request_id: 'synthetic-b-1', stage: 'B', kind: 'baseline',
    question_sha256: 'a'.repeat(64), prompt: 'synthetic synthetic-b-1\n中文 "code"\\path\n' };
  req.request_sha256 = hash(req.prompt);
  const state = { users: 1, replies: 1, raw: JSON.stringify({ task_id: req.task_id,
    question_sha256: req.question_sha256, proposal: '中文\n"code"\\path' }, null, 2),
    busy: false, copy: true, oldCopy: false, input: '', mode: 'Argon',
    url: 'https://gemini.google.com/app/synthetic-chat', clicks: 0, ...options };
  const tab = { id: 'synthetic-tab', async getAXState() {
    let tree = `Browser tab: synthetic-tab, Title: "Synthetic", URL: "${state.url}".\n`;
    if (state.oldCopy) tree += '\t2 button 复制\n';
    for (let i = 0; i < state.users; i++) tree += `\t${10+i} heading Value: 5, 你说 ${req.request_id}\n\t20 text ${req.task_id}\n`;
    for (let i = 0; i < state.replies; i++) tree += `\t${30+i} heading Gemini 说, Value: 6\n\t40 button 复制代码\n\t50 text ${state.raw}\n`;
    if (state.copy) tree += '\t60 button 复制\n';
    tree += `\t80 text entry area (settable) Description: 为 Gemini 输入提示, Value: ${state.input}\n\t\t81 text input\n`;
    tree += '\t90 pop up button Description: 打开模式选择器，当前模式为“'+state.mode+'”\n';
    if (state.busy) tree += '\t91 button 停止回答\n';
    else if (!state.users) tree += '\t92 button 发送\n';
    return tree;
  }, async setValue(index, value) { assert.equal(index, 80); state.input = value; },
  async click(index) { assert.equal(index, 92); state.clicks++; state.users = 1; state.replies = 1;
    state.input = ''; state.url = 'https://gemini.google.com/app/synthetic-chat'; } };
  const journal = { request_id: req.request_id, request_sha256: req.request_sha256,
    status: 'SENDING', tab_id: tab.id, fresh_context_observed: true,
    send_intent_at: '2026-10-16T00:00:00Z', ...journalChanges };
  return { req, state, tab, journal, session: createGeminiAxSession(req, tab, journal, hash, {mode:'Argon'}) };
}
test('complete multiline code preserves Chinese, escapes and full value after two real reads', async () => {
  const f = fixture(); assert.equal((await f.session.inspect()).status, 'WAITING');
  assert.equal((await f.session.inspect()).status, 'CAPTURE_READY');
  const result = f.session.capture();
  assert.deepEqual(JSON.parse(result.raw_response), JSON.parse(f.state.raw));
  assert.equal(result.raw_response_sha256, hash(result.raw_response));
});
test('busy generation, copy outside reply, truncated and wrong-identity replies never complete', async () => {
  for (const options of [{ busy: true }, { copy: false, oldCopy: true }, { raw: '{' },
    { raw: JSON.stringify({ task_id: 'wrong', question_sha256: 'a'.repeat(64) }) }]) {
    const f = fixture(options); await f.session.inspect();
    assert.equal((await f.session.inspect()).status, 'WAITING');
    assert.throws(() => f.session.capture());
  }
});
test('fresh input roundtrip and durable intent precede exactly one click', async () => {
  const f = fixture({ users: 0, replies: 0, copy: false, url: 'https://gemini.google.com/app' },
    { status: 'QUEUED', send_intent_at: undefined, fresh_context_observed: false });
  assert.equal((await f.session.inspect()).status, 'FRESH');
  await f.session.draft(); assert.equal((await f.session.inspect()).status, 'DRAFTED');
  await assert.rejects(f.session.send(f.journal), /durable send intent/);
  await f.session.send({ ...f.journal, status: 'SENDING', send_intent_at: '2026-10-16T00:00:00Z' });
  await assert.rejects(f.session.send(f.journal)); assert.equal(f.state.clicks, 1);
});
test('recovery of an uncertain send is observation-only', async () => {
  const f = fixture({}, { status: 'SEND_UNKNOWN' });
  await f.session.inspect(); await assert.rejects(f.session.draft());
  await assert.rejects(f.session.send(f.journal)); assert.equal(f.state.clicks, 0);
});
test('extra conversation turns and mode changes are rejected', async () => {
  for (const options of [{ users: 2 }, { replies: 2 }, { mode: 'Other' }]) {
    const f = fixture(options); await assert.rejects(f.session.inspect());
  }
  const spoof = fixture({ mode: 'Other', raw: JSON.stringify({ task_id: 'synthetic',
    question_sha256: 'a'.repeat(64), proposal: '当前模式为“Argon”' }) });
  await assert.rejects(spoof.session.inspect(), /visible mode missing/);
});
test('capture refuses fabricated clipboard text and missing final conversation URL', async () => {
  const f = fixture(); await f.session.inspect(); await f.session.inspect();
  assert.throws(() => f.session.capture(''));
  assert.throws(() => f.session.capture(JSON.stringify({ task_id: 'synthetic',
    question_sha256: 'a'.repeat(64), proposal: 'changed' })));
  const g = fixture({ url: 'https://gemini.google.com/app' });
  await g.session.inspect(); await g.session.inspect(); assert.throws(() => g.session.capture(), /conversation URL/);
});

test('English AX controls obey the same full-input and completion contract', async () => {
  const f = fixture();
  const original = f.tab.getAXState.bind(f.tab);
  f.tab.getAXState = async () => (await original()).replaceAll('为 Gemini 输入提示', 'Enter a prompt for Gemini')
    .replaceAll('你说', 'You said').replaceAll('Gemini 说', 'Gemini said')
    .replaceAll('复制代码', 'Copy code').replaceAll('复制', 'Copy')
    .replaceAll('停止回答', 'Stop generating').replaceAll('发送', 'Send')
    .replaceAll('打开模式选择器，当前模式为“Argon”', 'Open mode picker, current mode is "Argon"');
  await f.session.inspect();
  assert.equal((await f.session.inspect()).status, 'CAPTURE_READY');
  assert.equal(JSON.parse(f.session.capture().raw_response).task_id, f.req.task_id);
});

test('source being audited may contain the AX diff warning without impersonating a diff', async () => {
  const f = fixture();
  const value = JSON.parse(f.state.raw);
  value.proposal = 'Source string: diff from the previous accessibility tree; [truncated] is literal test data.';
  f.state.raw = JSON.stringify(value, null, 2);
  await f.session.inspect();
  assert.equal((await f.session.inspect()).status, 'CAPTURE_READY');
  assert.equal(JSON.parse(f.session.capture().raw_response).proposal, value.proposal);
});

test('real AX diff header cannot be used as a full observation', async () => {
  const f = fixture();
  f.tab.getAXState = async () => 'Browser tab: synthetic\nThe following is a diff from the previous accessibility tree\n+1 button Copy';
  await assert.rejects(f.session.inspect(), /Full accessibility tree/);
});

test('changed draft and changed mode require a new successful inspection before sending', async () => {
  const f = fixture({ users:0,replies:0,copy:false,url:'https://gemini.google.com/app' },
    {status:'QUEUED',send_intent_at:undefined,fresh_context_observed:false});
  await f.session.inspect(); await f.session.draft(); await f.session.inspect();
  f.state.input += ' UNEXPECTED';
  assert.equal((await f.session.inspect()).status,'FRESH');
  await assert.rejects(f.session.send({...f.journal,status:'SENDING',send_intent_at:'now'}));
  f.state.mode = 'Other';
  await assert.rejects(f.session.inspect(),/mode missing/);
  assert.equal(f.state.clicks,0);
});

test('a pending observation after an uncertain send never enables another send', async () => {
  const f=fixture({}, {status:'SEND_UNKNOWN'});
  const original=f.tab.getAXState.bind(f.tab); let resume;
  f.tab.getAXState=()=>new Promise(resolve=>{resume=resolve;});
  const pending=f.session.inspect();
  await assert.rejects(f.session.draft()); await assert.rejects(f.session.send(f.journal));
  resume(await original()); await pending;
  f.tab.getAXState=original; await f.session.inspect();
  assert.equal(f.state.clicks,0);
});

test('AX preserves a complete prose-framed nested JSON value and refuses two JSON values', async () => {
  const f=fixture(); f.state.raw='好的\n```json\n'+f.state.raw+'\n```\n谢谢';
  await f.session.inspect(); assert.equal((await f.session.inspect()).status,'CAPTURE_READY');
  assert.equal(f.session.capture().raw_response,f.state.raw);
  f.state.raw='{}\n'+f.state.raw;
  assert.equal((await f.session.inspect()).status,'WAITING'); assert.throws(()=>f.session.capture());
});

test('a simulated 45-second backend delay cannot turn uncertain sending into a resend', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const f=fixture({}, {status:'SEND_UNKNOWN'}), original=f.tab.getAXState.bind(f.tab);
  let finished=false;
  f.tab.getAXState=async()=>{await new Promise(resolve=>setTimeout(resolve,45000));return original();};
  const pending=f.session.inspect().then(value=>{finished=true;return value;});
  t.mock.timers.tick(40001); await Promise.resolve();
  assert.equal(finished,false); await assert.rejects(f.session.send(f.journal));
  t.mock.timers.tick(4999); await pending;
  assert.equal(f.state.clicks,0);
});

test('DOM-to-AX recovery accepts full Chinese/English model labels and preserves exact receipt binding', async () => {
  for(const label of ['打开模式选择器，当前模式为“Argon”','Open mode picker, current mode is "Argon"']) {
    const f=fixture({}, {model_observed:label});
    const migrated=createGeminiAxSession(f.req,f.tab,f.journal,hash);
    await migrated.inspect();assert.equal((await migrated.inspect()).status,'CAPTURE_READY');
    assert.equal(migrated.capture().model_observed,label);
  }
});

test('an AX mode override cannot replace the model frozen in a durable journal', () => {
  const f=fixture();
  assert.throws(()=>createGeminiAxSession(f.req,f.tab,{...f.journal,model_observed:'Other'},hash,{mode:'Argon'}),/bound journal/);
});
