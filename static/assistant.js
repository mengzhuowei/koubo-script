const form = document.querySelector('#assistant-form');
const input = document.querySelector('#assistant-input');
const send = document.querySelector('#assistant-send');
const reset = document.querySelector('#assistant-reset');
const messages = document.querySelector('#assistant-messages');
const conversation = document.querySelector('#assistant-conversation');
const examples = document.querySelector('#assistant-examples');
const status = document.querySelector('#assistant-status');
const storageKey = 'koubo-project-chat';
const historyLimit = 12;
const streamType = 'application/x-ndjson';
const stepStatuses = { running: '进行中', done: '完成', failed: '失败', interrupted: '结果未收到' };
let busy = false;
let transcript = [];

try {
  transcript = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
  if (!Array.isArray(transcript)) transcript = [];
} catch {
  transcript = [];
}

function saveTranscript() {
  transcript = transcript.slice(-historyLimit);
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(transcript));
  } catch {
    // 对话仍可在当前页面继续。
  }
}

function updateControls() {
  send.disabled = busy;
  reset.disabled = busy || messages.childElementCount === 0;
  examples.hidden = messages.childElementCount > 0;
  status.hidden = !busy;
  status.textContent = busy ? '助手正在处理…' : '';
}

function appendMessage(entry) {
  const { role, steps = [] } = entry;
  const message = document.createElement('article');
  message.classList.add('project-chat-message', `project-chat-${role}`);
  const author = document.createElement('strong');
  author.textContent = role === 'user' ? '你' : '项目助手';
  message.append(author);

  const process = document.createElement('details');
  process.className = 'project-chat-process';
  process.open = true;
  process.hidden = true;
  const summary = document.createElement('summary');
  summary.textContent = '执行过程';
  const stepList = document.createElement('ol');
  stepList.className = 'project-chat-steps';
  process.append(summary, stepList);
  if (role === 'assistant') message.append(process);

  const text = document.createElement('p');
  const links = document.createElement('ul');
  links.className = 'project-chat-receipts';
  message.append(text, links);

  function updateStep({ id, label, state, detail }) {
    process.hidden = false;
    let row = stepList.children[id - 1];
    if (!row) {
      row = document.createElement('li');
      const action = document.createElement('span');
      action.textContent = label;
      const result = document.createElement('span');
      result.className = 'project-chat-step-status';
      row.append(action, result);
      stepList.append(row);
    }
    row.dataset.state = state;
    row.lastElementChild.textContent = detail ? `${stepStatuses[state]} · ${detail}` : stepStatuses[state];
  }

  function updateReply({ content = '', receipts = [], error = false }) {
    text.textContent = content;
    text.hidden = !content;
    text.classList.toggle('project-chat-error', error);
    links.replaceChildren();
    for (const receipt of receipts) {
      if (!/^\/(jobs|topics\/\d+(\/scripts(\?job=\d+)?)?)$/.test(receipt.url)) continue;
      const link = document.createElement('a');
      link.href = receipt.url;
      link.textContent = receipt.label;
      const item = document.createElement('li');
      item.append(link);
      links.append(item);
    }
    links.hidden = links.childElementCount === 0;
  }

  updateReply(entry);
  for (const step of steps) updateStep(step);
  messages.append(message);
  message.scrollIntoView({ block: 'nearest' });
  return { updateStep, updateReply };
}

async function readReply(response, onStep) {
  if (!response.ok) throw new Error('Chat request failed');
  if (!response.headers.get('Content-Type')?.startsWith(streamType)) return response.json();

  let remainder = '';
  let reply;
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    const lines = (remainder + chunk).split('\n');
    remainder = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'reply') reply = event.result;
      if (event.type === 'tool') onStep(event);
    }
  }
  if (reply) return reply;
  throw new Error('Chat stream ended without a reply');
}

for (const item of transcript) appendMessage(item);
updateControls();

for (const button of examples.querySelectorAll('button')) {
  button.addEventListener('click', () => {
    input.value = button.dataset.message;
    input.focus();
  });
}

reset.addEventListener('click', () => {
  transcript = [];
  saveTranscript();
  messages.replaceChildren();
  input.value = '';
  updateControls();
  input.focus();
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!busy) form.requestSubmit();
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || busy) return;

  const history = transcript.filter((item) => item.context).map(({ role, content, receipts = [] }) => ({
    role,
    content: [content, ...receipts.map(({ label }) => label)].join('\n').slice(0, 5000),
  }));
  const user = { role: 'user', content: message };
  appendMessage(user);
  const pending = appendMessage({ role: 'assistant' });
  input.value = '';
  busy = true;
  updateControls();

  const steps = [];
  const confirmedReceipts = [];
  let answer;
  try {
    const response = await fetch('/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: streamType },
      body: JSON.stringify({ message, history }),
    });
    const { reply, receipts, ok } = await readReply(response, ({ id, label, state, detail, receipt }) => {
      const step = { id, label, state, detail };
      steps[id - 1] = step;
      if (receipt) confirmedReceipts.push(receipt);
      pending.updateStep(step);
      status.textContent = state === 'running' ? `正在${label}…` : '助手正在继续处理…';
      conversation.scrollTop = conversation.scrollHeight;
    });
    answer = { role: 'assistant', content: reply, receipts, error: !ok, context: ok || receipts.length > 0 };
  } catch {
    answer = {
      role: 'assistant', content: '未能取得完整回复。可以查看任务列表，再重新发送消息。',
      receipts: confirmedReceipts, error: true, context: confirmedReceipts.length > 0,
    };
  } finally {
    for (const step of steps) {
      if (step.state === 'running') {
        step.state = 'interrupted';
        pending.updateStep(step);
      }
    }
    answer.steps = steps;
    transcript.push({ ...user, context: answer.context }, answer);
    saveTranscript();
    pending.updateReply(answer);
    busy = false;
    updateControls();
    conversation.scrollTop = conversation.scrollHeight;
    input.focus();
  }
});
