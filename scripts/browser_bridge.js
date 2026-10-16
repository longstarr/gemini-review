/* Execute this source inside cua_repl; never start a second automation browser.
 * Supply UI locators grounded in a fresh Gemini DOM observation, not guessed selectors.
 * Offline tests use explicit synthetic adapters and do not establish live compatibility.
 */
function geminiUtf8Sha256(text) {
  const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const bytes = Array.from(new TextEncoder().encode(text));
  const bits = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  for (let i = 7; i >= 0; i--) bytes.push(Math.floor(bits / 2 ** (i * 8)) & 255);
  const r = (x, n) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < bytes.length; offset += 64) {
    const w = [];
    for (let i = 0; i < 16; i++) w[i] = (bytes[offset+i*4]<<24) | (bytes[offset+i*4+1]<<16) |
      (bytes[offset+i*4+2]<<8) | bytes[offset+i*4+3];
    for (let i = 16; i < 64; i++) {
      const x = w[i-15], y = w[i-2];
      w[i] = (w[i-16] + (r(x,7)^r(x,18)^(x>>>3)) + w[i-7] + (r(y,17)^r(y,19)^(y>>>10))) | 0;
    }
    let [a,b,c,d,e,f,g,z] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (z + (r(e,6)^r(e,11)^r(e,25)) + ((e&f)^(~e&g)) + k[i] + w[i]) | 0;
      const t2 = ((r(a,2)^r(a,13)^r(a,22)) + ((a&b)^(a&c)^(b&c))) | 0;
      z=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0;
    }
    [a,b,c,d,e,f,g,z].forEach((value, i) => { h[i] = (h[i] + value) | 0; });
  }
  return h.map(x => (x>>>0).toString(16).padStart(8,'0')).join('');
}


function geminiJsonText(raw) {
  const text = raw.replace(/^\uFEFF/, '');
  const chunks = []; let start = -1, stack = [], quoted = false, escaped = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (start < 0) { if ('{['.includes(char)) { start = index; stack = [char]; } continue; }
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') quoted = false;
      continue;
    }
    if (char === '"') quoted = true;
    else if ('{['.includes(char)) stack.push(char);
    else if ('}]'.includes(char)) {
      if ((stack.pop() === '{' ? '}' : ']') !== char) throw new Error('Mismatched JSON delimiters');
      if (!stack.length) { chunks.push(text.slice(start, index + 1)); start = -1; }
    }
  }
  if (start >= 0 || chunks.length !== 1 || !chunks[0].startsWith('{')) throw new Error('Expected one complete JSON object');
  geminiParseJson(chunks[0]);
  return chunks[0];
}

function geminiParseJson(text) {
  const value = JSON.parse(text);
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\],:]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g) || [];
  const stack = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token === '{') stack.push(new Set());
    else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop();
    else if (token.startsWith('"') && tokens[i + 1] === ':') {
      const key = JSON.parse(token), keys = stack[stack.length - 1];
      if (keys.has(key)) throw new Error('Duplicate JSON key');
      keys.add(key);
    }
  }
  if (value === null || Array.isArray(value) || typeof value !== 'object') throw new Error('JSON object required');
  return value;
}

function geminiInputText(element) {
  return element.isContentEditable || element.getAttribute?.('contenteditable') === 'true' || element.tagName === 'DIV'
    ? (element.innerText ?? element.textContent ?? '') : (element.value ?? element.innerText ?? '');
}

function geminiUiName(value) {
  if (!Array.isArray(value)) return value;
  return new RegExp('^(?:' + value.map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')$');
}

function geminiModeName(observed) {
  const label = String(observed ?? '').trim();
  const chinese = label.match(/当前模式为[“"]([^”"]+)[”"]/);
  const english = label.match(/current mode(?: is|:)?\s*[“"]?([^”",]+)[”"]?/i);
  return chinese?.[1] ?? english?.[1]?.trim() ?? label;
}

function createGeminiWebBridge(browser, ui, clock = () => new Date().toISOString()) {
  const sessions = new Map();
  const normalize = text => text.replace(/\r\n/g, '\n');
  const plainJson = geminiJsonText;
  function requireUi(names) {
    for (const name of names) {
      if (!ui[name]) throw new Error('Observe live DOM and configure UI field: ' + name);
    }
  }
  const prompt = tab => tab.playwright.getByRole('textbox', { name: geminiUiName(ui.promptName), exact: true });
  const button = (tab, name) => tab.playwright.getByRole('button', { name: geminiUiName(name), exact: true });
  const currentModel = async tab => {
    const control = button(tab, ui.modelButtonName);
    if (await control.count() !== 1) throw new Error('Model selector is ambiguous or missing');
    return (await control.getAttribute('aria-label')) || (await control.innerText());
  };
  function session(id) {
    const value = sessions.get(id);
    if (!value) throw new Error('Unknown request; recover from the durable local journal');
    return value;
  }
  function verifyQueued(request) {
    if (!['B', 'C', 'D'].includes(request.stage) || typeof request.prompt !== 'string' ||
        !request.prompt || geminiUtf8Sha256(request.prompt) !== request.request_sha256) {
      throw new Error('Queued request prompt/hash mismatch');
    }
  }
  async function assertFresh(tab) {
    const url = await tab.url();
    if (!/^https:\/\/gemini\.google\.com\/app\/?(?:\?[^#]*)?$/.test(url || '')) {
      throw new Error('A fresh Gemini app page is required');
    }
    if (await tab.playwright.locator(ui.userSelector).count() !== 0 ||
        await tab.playwright.locator(ui.responseSelector).count() !== 0) {
      throw new Error('New page contains message history; do not send');
    }
    if (await prompt(tab).count() !== 1 || !(await prompt(tab).isVisible())) {
      throw new Error('Prompt textbox is missing or ambiguous');
    }
  }
  return {
    async adoptFresh(request, tab, journalItem) {
      requireUi(['promptName', 'responseSelector', 'userSelector', 'modelButtonName']);
      verifyQueued(request);
      if (sessions.has(request.request_id) || journalItem.request_id !== request.request_id ||
          journalItem.request_sha256 !== request.request_sha256 ||
          journalItem.status !== 'QUEUED' || journalItem.send_intent_at ||
          (journalItem.tab_id && journalItem.tab_id !== tab.id)) {
        throw new Error('Only a verified queued, never-attempted request can adopt a fresh tab');
      }
      await assertFresh(tab);
      const model = await currentModel(tab);
      if (ui.requiredModeText && !model.includes(ui.requiredModeText)) throw new Error('Requested mode missing');
      sessions.set(request.request_id, { tab, request, fresh: true, status: 'FRESH', model,
        sendAttempted: false, lastText: null, stable: 0, capture: null });
      return { request_id: request.request_id, tab_id: tab.id, source_url: await tab.url(),
        model_observed: model, fresh_context_observed: true };
    },
    async open(request) {
      requireUi(['promptName', 'responseSelector', 'userSelector', 'modelButtonName']);
      verifyQueued(request);
      if (sessions.has(request.request_id)) throw new Error('Request already has a tab; do not recreate');
      if (!['B', 'C', 'D'].includes(request.stage) || !request.prompt || !request.request_sha256) {
        throw new Error('Use a queued browser-request.json from web_flow.py');
      }
      const tab = await browser.tabs.new();
      const value = { tab, request, fresh: false, status: 'CREATED', model: '',
                      sendAttempted: false, lastText: null, stable: 0, capture: null };
      sessions.set(request.request_id, value); // Even failed navigation retains ownership.
      await tab.goto('https://gemini.google.com/app');
      const snapshot = await tab.playwright.domSnapshot();
      await assertFresh(tab);
      value.model = await currentModel(tab);
      if (ui.requiredModeText && !value.model.includes(ui.requiredModeText)) {
        throw new Error('Requested Gemini mode is not visibly selected; inspect its menu');
      }
      value.fresh = true;
      value.status = 'FRESH';
      return { request_id: request.request_id, tab_id: tab.id, source_url: await tab.url(),
               model_observed: value.model, fresh_context_observed: true, snapshot };
    },
    async draft(id) {
      const value = session(id);
      if (value.status !== 'FRESH') throw new Error('Draft requires an unused fresh page');
      await assertFresh(value.tab);
      await prompt(value.tab).fill(value.request.prompt);
      const snapshot = await value.tab.playwright.domSnapshot();
      const entered = await prompt(value.tab).evaluate(geminiInputText);
      if (normalize(entered) !== normalize(value.request.prompt)) {
        throw new Error('Prompt text was not transferred intact; do not send');
      }
      value.status = 'DRAFTED';
      return { status: value.status, request_id: id, prompt_matches: true, snapshot };
    },
    async recheckFresh(id) {
      const value = session(id);
      if (value.sendAttempted) throw new Error('Cannot reset a page after a send attempt');
      const snapshot = await value.tab.playwright.domSnapshot();
      await assertFresh(value.tab);
      value.model = await currentModel(value.tab);
      if (ui.requiredModeText && !value.model.includes(ui.requiredModeText)) {
        throw new Error('Requested mode is not selected');
      }
      value.fresh = true;
      value.status = 'FRESH';
      return { status: value.status, tab_id: value.tab.id, snapshot };
    },
    async send(id) {
      requireUi(['sendName']);
      const value = session(id);
      if (value.status !== 'DRAFTED' || value.sendAttempted) {
        throw new Error('Send cannot be repeated; inspect existing conversation');
      }
      const entered = await prompt(value.tab).evaluate(geminiInputText);
      if (normalize(entered) !== normalize(value.request.prompt)) throw new Error('Draft changed before send');
      const model = await currentModel(value.tab);
      if (model !== value.model) throw new Error('Model label changed before send; reobserve');
      if (await button(value.tab, ui.sendName).count() !== 1 ||
          !(await button(value.tab, ui.sendName).isEnabled())) throw new Error('Send control unavailable');
      value.sendAttempted = true; // Local web_flow sending intent must already be persisted.
      value.status = 'SEND_UNKNOWN';
      await button(value.tab, ui.sendName).click();
      const snapshot = await value.tab.playwright.domSnapshot();
      value.status = 'WAITING';
      return { status: value.status, request_id: id, snapshot };
    },
    async observe(id) {
      requireUi(['stopName', 'copyName', 'replyTextSelector']);
      const value = session(id);
      if (!value.sendAttempted) throw new Error('No send attempt to observe');
      const tab = value.tab;
      const snapshot = await tab.playwright.domSnapshot();
      const user = tab.playwright.locator(ui.userSelector);
      const responses = tab.playwright.locator(ui.responseSelector);
      const userCount = await user.count();
      const responseCount = await responses.count();
      const stopVisible = await button(tab, ui.stopName).isVisible();
      if (userCount > 1 || responseCount > 1) throw new Error('Unexpected additional conversation turns');
      const echo = userCount === 1 ? (await user.last().textContent()) || '' : '';
      const echoMatches = echo.includes(value.request.request_id) && echo.includes(value.request.task_id);
      let raw = '', copyVisible = false;
      if (responseCount === 1) {
        const response = responses.last();
        copyVisible = await response.getByRole('button', { name: geminiUiName(ui.copyName), exact: true }).isVisible();
        const body = response.locator(ui.replyTextSelector);
        if (await body.count() !== 1) throw new Error('Reply text is missing or ambiguous; reobserve DOM');
        raw = (await body.textContent()) || '';
      }
      value.stable = raw && raw === value.lastText ? value.stable + 1 : 1;
      value.lastText = raw;
      let parsed = null;
      try { parsed = geminiParseJson(plainJson(raw)); } catch (_) { /* Local strict parser is authoritative. */ }
      const identityMatches = parsed && parsed.task_id === value.request.task_id &&
        (value.request.kind === 'baseline'
          ? parsed.question_sha256 === value.request.question_sha256
          : parsed.request_id === value.request.request_id && parsed.plan_sha256 === value.request.plan_sha256 &&
            parsed.round === value.request.round && parsed.phase === value.request.phase &&
            parsed.complete === true && parsed.end_marker === 'END_REVIEW');
      const complete = echoMatches && !stopVisible && copyVisible && value.stable >= 2 && identityMatches;
      value.status = complete ? 'CAPTURE_READY' : 'WAITING';
      if (complete) {
        value.capture = { protocol: 'gemini-review/2', task_id: value.request.task_id,
          request_id: id, stage: value.request.stage, request_sha256: value.request.request_sha256,
          tab_id: tab.id, source_url: await tab.url(), model_observed: value.model,
          fresh_context: value.fresh, prompt_echo_matches: echoMatches, captured_at: clock(),
          completion: { stop_visible: stopVisible, copy_visible: copyVisible,
                        stable_observations: value.stable }, raw_response: raw,
          raw_response_sha256: geminiUtf8Sha256(raw) };
      }
      return { status: value.status, request_id: id, stop_visible: stopVisible,
        response_count: responseCount, copy_visible: copyVisible, stable_observations: value.stable,
        json_identity_matches: Boolean(identityMatches), snapshot };
    },
    capture(id) {
      const value = session(id);
      if (value.status !== 'CAPTURE_READY' || !value.capture) throw new Error('Reply not observed complete');
      return JSON.parse(JSON.stringify(value.capture));
    },
    status(id) {
      const value = session(id);
      return { request_id: id, tab_id: value.tab.id, status: value.status,
               send_attempted: value.sendAttempted, fresh_context: value.fresh };
    },
    async keepForRecovery(id) { await session(id).tab.markHandoff(); },
  };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { createGeminiWebBridge, geminiUtf8Sha256, geminiJsonText, geminiParseJson, geminiInputText, geminiUiName, geminiModeName };
