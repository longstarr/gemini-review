/* Official CUA accessibility fallback. One UI operation per call for slow backends.
 * Load together with geminiUtf8Sha256 from browser_bridge.js inside cua_repl.
 * No browser internals, raw CDP, network, filesystem or credential access.
 */
function createGeminiAxSession(request, tab, journal, hash, ui = {}) {
  const common = typeof module !== 'undefined' && module.exports ? require('./browser_bridge.js') : { geminiJsonText, geminiParseJson, geminiModeName };
  const boundMode = common.geminiModeName(journal.model_observed);
  const labels = { prompt: ['为 Gemini 输入提示', 'Enter a prompt for Gemini', 'Ask Gemini'],
    user: ['你说', 'You said'], model: ['Gemini 说', 'Gemini said'], mode: boundMode,
    stop: ['停止回答', 'Stop generating', 'Stop response'], copy: ['复制', 'Copy', 'Copy response'],
    codeCopy: ['复制代码', 'Copy code'], send: ['发送', 'Send', 'Send message'], ...ui };
  if (typeof labels.mode !== 'string' || !labels.mode) throw new Error('Observe visible mode and provide ui.mode');
  if (boundMode && labels.mode !== boundMode) throw new Error('Mode override differs from bound journal');
  const escape = s => Array.isArray(s) ? '(?:' + s.map(escape).join('|') + ')' : s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const plain = common.geminiJsonText;
  const parseJson = common.geminiParseJson;
  if (hash(request.prompt) !== request.request_sha256 || journal.request_id !== request.request_id ||
      journal.request_sha256 !== request.request_sha256 ||
      (journal.tab_id && journal.tab_id !== tab.id)) throw new Error('Request/journal binding mismatch');
  if (!['QUEUED', 'SENDING', 'SEND_UNKNOWN'].includes(journal.status)) throw new Error('Inactive request');
  let attempted = journal.status !== 'QUEUED', fresh = journal.fresh_context_observed === true;
  if (attempted && (!fresh || !journal.send_intent_at)) throw new Error('Recovery needs durable send/fresh evidence');
  let state = attempted ? 'WAITING' : 'NEEDS_FRESH', last = null, previousRaw = null, stable = 0;
  const identity = parsed => parsed && parsed.task_id === request.task_id &&
    (request.kind === 'baseline' ? parsed.question_sha256 === request.question_sha256 :
      parsed.request_id === request.request_id && parsed.plan_sha256 === request.plan_sha256 &&
      parsed.round === request.round && parsed.phase === request.phase &&
      parsed.complete === true && parsed.end_marker === 'END_REVIEW');
  function parse(tree) {
    if (tree.split('\n').slice(0, 3).some(line => line.startsWith('The following is a diff from the previous accessibility tree'))) throw new Error('Full accessibility tree required');
    const heading = name => new RegExp('^\\t*\\d+ heading (?:Value: \\d+, )?' + escape(name) + '(?:,| |$)', 'gm');
    const input = tree.match(new RegExp('^\\t*(\\d+) text entry area[^\\n]*Description: ' + escape(labels.prompt) + ', Value: ([\\s\\S]*?)(?=\\n\\t+\\d+ [a-z]|(?![\\s\\S]))', 'm'));
    const models = [...tree.matchAll(heading(labels.model))], users = [...tree.matchAll(heading(labels.user))];
    const bodyStart = models.length === 1 ? models[0].index : -1;
    const tail = bodyStart < 0 ? '' : tree.slice(bodyStart);
    const scope = tail.split(/\n\t*\d+ text entry area/)[0];
    const control = (text, source = tree) => [...source.matchAll(new RegExp('^\\t*(\\d+) button ' + escape(text) + '(?:\\r?$)', 'gm'))];
    const values = [...scope.matchAll(/^\t*\d+ text ([\s\S]*?)(?=\n\t+\d+ [a-z]|(?![\s\S]))/gm)]
      .map(match => match[1]).filter(value => value.includes('{') || value.includes('['));
    const copy = control(labels.copy, scope), codeCopy = control(labels.codeCopy, scope);
    const raw = values.length === 1 ? values[0] : '';
    const url = tree.split('\n')[0].match(/URL: "([^"]+)"/)?.[1];
    let parsed; try { parsed = parseJson(plain(raw)); } catch (_) {}
    return { url, input_index: input ? Number(input[1]) : null, input_value: input?.[2],
      user_count: users.length, response_count: models.length, raw,
      mode_ok: new RegExp('^\\t*\\d+ pop up button[^\\n]*Description: (?:打开模式选择器，当前模式为“' + escape(labels.mode) + '”|Open mode (?:picker|selector), current mode (?:is |)["“]?' + escape(labels.mode) + '["”]?)(?:,|$)', 'mi').test(tree),
      stop_visible: control(labels.stop).length > 0, copy_visible: copy.length === 1,
      code_copy_index: codeCopy.length === 1 ? Number(codeCopy[0][1]) : null,
      send_index: control(labels.send).length === 1 ? Number(control(labels.send)[0][1]) : null,
      prompt_echo_matches: users.length === 1 && bodyStart > users[0].index &&
        tree.slice(users[0].index, bodyStart).includes(request.request_id) &&
        tree.slice(users[0].index, bodyStart).includes(request.task_id), identity_matches: Boolean(identity(parsed)) };
  }
  return {
    async inspect() {
      const facts = parse(await tab.getAXState({ emit: false, disableDiffing: true }));
      if (facts.user_count > 1 || facts.response_count > 1) throw new Error('Unexpected additional turns');
      if (!facts.mode_ok) throw new Error('Requested visible mode missing');
      if (!attempted) {
        if (!/^https:\/\/gemini\.google\.com\/app\/?(?:\?[^#]*)?$/.test(facts.url || '') ||
            facts.user_count || facts.response_count || facts.input_index === null) throw new Error('Fresh context not observed');
        fresh = true;
        state = facts.input_value === request.prompt ? 'DRAFTED' : 'FRESH';
      } else {
        stable = facts.raw && facts.raw === previousRaw ? stable + 1 : 1;
        previousRaw = facts.raw;
        state = facts.prompt_echo_matches && !facts.stop_visible && facts.copy_visible &&
          stable >= 2 && facts.identity_matches ? 'CAPTURE_READY' : 'WAITING';
      }
      last = facts;
      return { ...facts, raw: undefined, input_value: undefined, status: state, stable_observations: stable,
        tab_id: tab.id, fresh_context_observed: fresh, prompt_matches: facts.input_value === request.prompt };
    },
    async draft() {
      if (attempted || state !== 'FRESH' || last?.input_index === null) throw new Error('Fresh observation required');
      const index = last.input_index; last = null; state = 'DRAFT_UNKNOWN';
      await tab.setValue(index, request.prompt);
      return { status: state }; // inspect next; never send based solely on a successful write.
    },
    async send(intent) {
      if (attempted || state !== 'DRAFTED' || last?.send_index == null ||
          intent.status !== 'SENDING' || !intent.send_intent_at || intent.tab_id !== tab.id ||
          intent.request_id !== request.request_id || intent.request_sha256 !== request.request_sha256) {
        throw new Error('Verified draft and durable send intent required; do not resend');
      }
      const index = last.send_index; attempted = true; last = null; state = 'SEND_UNKNOWN';
      await tab.click(index); state = 'WAITING'; return { status: state };
    },
    async copyCode() {
      if (state !== 'CAPTURE_READY' || last?.code_copy_index == null) throw new Error('Complete scoped code required');
      const index = last.code_copy_index; last = null; state = 'COPY_PENDING';
      await tab.click(index); return { status: state }; // inspect before the next UI decision.
    },
    capture(rawText = last?.raw) {
      if (state !== 'CAPTURE_READY' || !last || typeof rawText !== 'string' ||
          !identity(parseJson(plain(rawText))) ||
          JSON.stringify(parseJson(plain(rawText))) !== JSON.stringify(parseJson(plain(last.raw)))) throw new Error('Complete response not confirmed');
      if (!/^https:\/\/gemini\.google\.com\/app\/[A-Za-z0-9_-]+(?:\?[^#]*)?$/.test(last.url || '')) throw new Error('Actual conversation URL required');
      return { protocol: 'gemini-review/2', task_id: request.task_id, request_id: request.request_id,
        stage: request.stage, request_sha256: request.request_sha256, tab_id: tab.id,
        source_url: last.url, model_observed: journal.model_observed || labels.mode, fresh_context: fresh,
        prompt_echo_matches: last.prompt_echo_matches, captured_at: new Date().toISOString(),
        completion: { stop_visible: false, copy_visible: true, stable_observations: stable },
        capture_method: rawText === last.raw ? 'accessibility-code-value' : 'scoped-code-clipboard',
        raw_response: rawText, raw_response_sha256: hash(rawText) };
    },
  };
}
if (typeof module !== 'undefined' && module.exports) module.exports = { createGeminiAxSession };
