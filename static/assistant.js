const form = document.querySelector('#assistant-form');
const input = document.querySelector('#assistant-input');
const send = document.querySelector('#assistant-send');
const reset = document.querySelector('#assistant-reset');
const messages = document.querySelector('#assistant-messages');
const conversation = document.querySelector('#assistant-conversation');
const examples = document.querySelector('#assistant-examples');
const status = document.querySelector('#assistant-status');
const attachButton = document.querySelector('#assistant-attach');
const fileInput = document.querySelector('#assistant-files');
const attachmentList = document.querySelector('#assistant-attachments');
const suggestion = document.querySelector('#assistant-suggestion');
const suggestionText = document.querySelector('#assistant-suggestion-text');
const maxFiles = Number(fileInput.dataset.maxFiles);
const maxBytes = Number(fileInput.dataset.maxBytes);
const fallbackStarters = [...examples.querySelectorAll('button')].map((button) => button.dataset.message);
const storageKey = 'koubo-project-chat';
const historyLimit = 12;
const streamType = 'application/x-ndjson';
const stepStatuses = { running: '进行中', done: '完成', failed: '失败', interrupted: '结果未收到' };
let busy = false;
let uploading = false;
let transcript = [];
let sentFiles = [];
let draftFiles = [];
let nextPrompt = '';
let suggestionRequest;

try {
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
  if (Array.isArray(saved)) transcript = saved;
  else if (Array.isArray(saved?.transcript)) {
    transcript = saved.transcript;
    sentFiles = saved.attachments || [];
  }
  nextPrompt = transcript.at(-1)?.nextPrompt || '';
} catch { /* 允许在不保存会话的浏览器中使用。 */ }

function saveTranscript() {
  transcript = transcript.slice(-historyLimit);
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({ transcript, attachments: sentFiles }));
  } catch {
    // 对话仍可在当前页面继续。
  }
}

function updateControls() {
  send.disabled = busy || uploading || (!input.value.trim() && draftFiles.length === 0);
  attachButton.disabled = busy || uploading;
  reset.disabled = busy || uploading || (messages.childElementCount === 0 && draftFiles.length === 0);
  examples.hidden = messages.childElementCount > 0;
  suggestion.hidden = busy || uploading || !nextPrompt || Boolean(input.value.trim());
  suggestionText.textContent = nextPrompt;
}

function setStatus(message, error = false) {
  status.textContent = message;
  status.hidden = !message;
  status.dataset.error = String(error);
}

function fillInput(message) {
  input.value = message;
  input.focus();
  input.setSelectionRange(message.length, message.length);
  updateControls();
}

function renderStarters(prompts) {
  examples.replaceChildren(...prompts.map((prompt) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn';
    button.textContent = prompt;
    button.addEventListener('click', () => fillInput(prompt));
    return button;
  }));
}

async function requestSuggestions(body, onResult) {
  suggestionRequest?.abort();
  const controller = new AbortController();
  suggestionRequest = controller;
  try {
    const response = await fetch('/assistant/suggestions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: controller.signal,
    });
    if (!response.ok) return;
    const result = await response.json();
    if (!controller.signal.aborted) onResult(result);
  } catch { /* 对话和默认快捷选项仍可用。 */ }
}

function showStarters() {
  renderStarters(fallbackStarters);
  requestSuggestions({}, ({ starters }) => {
    if (starters?.length) renderStarters(starters);
  });
}

function requestFollowup(user, answer) {
  if (!user || !answer?.context) return;
  requestSuggestions({
    message: user.content, reply: answer.content, receipts: (answer.receipts || []).map(({ label }) => label),
    has_attachments: sentFiles.length > 0,
  }, ({ next_prompt }) => {
    nextPrompt = next_prompt || '';
    answer.nextPrompt = nextPrompt;
    saveTranscript();
    updateControls();
  });
}

function useSuggestion() {
  if (suggestion.hidden) return;
  fillInput(nextPrompt);
}

function renderDraftFiles() {
  attachmentList.hidden = draftFiles.length === 0;
  attachmentList.replaceChildren(...draftFiles.map((file) => {
    const item = document.createElement('li');
    const name = document.createElement('span');
    name.textContent = file.name;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '×';
    remove.setAttribute('aria-label', `移除附件 ${file.name}`);
    remove.addEventListener('click', () => {
      draftFiles = draftFiles.filter(({ id }) => id !== file.id);
      setStatus('');
      renderDraftFiles();
    });
    item.append(name, remove);
    return item;
  }));
  updateControls();
}

async function uploadAttachments(files) {
  if (uploading || busy || !files.length) return;
  uploading = true;
  updateControls();
  setStatus('正在读取附件…');
  const failures = [];
  for (const file of files) {
    if (draftFiles.length >= maxFiles) {
      failures.push(`每次最多添加 ${maxFiles} 个附件。`);
      break;
    }
    if (file.size > maxBytes) {
      failures.push(`${file.name} 超过 5 MB。`);
      continue;
    }
    try {
      const response = await fetch('/assistant/attachments', {
        method: 'POST', headers: {
          'Content-Type': 'application/octet-stream', 'X-Attachment-Name': encodeURIComponent(file.name),
        }, body: file,
      });
      const data = await response.json();
      if (response.ok) draftFiles.push(data);
      else failures.push(`${file.name} · ${data.detail}`);
    } catch {
      failures.push(`${file.name} 上传失败，请重试。`);
    }
  }
  uploading = false;
  setStatus(failures.join(' '), failures.length > 0);
  renderDraftFiles();
  input.focus();
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
  if (entry.files?.length) {
    const files = document.createElement('ul');
    files.className = 'project-chat-message-files';
    files.setAttribute('aria-label', '已发送附件');
    for (const name of entry.files) {
      const item = document.createElement('li');
      item.textContent = name;
      files.append(item);
    }
    message.append(files);
  }

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
if (!transcript.length) showStarters();
else if (transcript.at(-1).nextPrompt === undefined) requestFollowup(transcript.at(-2), transcript.at(-1));

attachButton.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  const files = [...fileInput.files];
  fileInput.value = '';
  uploadAttachments(files);
});
suggestion.addEventListener('click', useSuggestion);
input.addEventListener('input', updateControls);

reset.addEventListener('click', () => {
  transcript = [];
  sentFiles = [];
  draftFiles = [];
  nextPrompt = '';
  saveTranscript();
  messages.replaceChildren();
  input.value = '';
  setStatus('');
  renderDraftFiles();
  showStarters();
  input.focus();
});

input.addEventListener('keydown', (event) => {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Tab' && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey && !suggestion.hidden) {
    event.preventDefault();
    useSuggestion();
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    if (!send.disabled) form.requestSubmit();
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (send.disabled) return;
  const typed = input.value.trim();
  const message = typed || '请阅读本轮上传的附件，概括主要内容。';
  const newFiles = draftFiles;
  const currentFiles = [...sentFiles, ...newFiles].slice(-maxFiles);
  suggestionRequest?.abort();
  nextPrompt = '';

  const history = transcript.filter((item) => item.context).map(({ role, content, receipts = [] }) => ({
    role,
    content: [content, ...receipts.map(({ label }) => label)].join('\n').slice(0, 5000),
  }));
  const user = { role: 'user', content: message, files: newFiles.map(({ name }) => name) };
  appendMessage(user);
  const pending = appendMessage({ role: 'assistant' });
  input.value = '';
  busy = true;
  draftFiles = [];
  renderDraftFiles();
  setStatus('助手正在处理…');

  const steps = [];
  const confirmedReceipts = [];
  let answer;
  let expired = [];
  try {
    const response = await fetch('/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: streamType },
      body: JSON.stringify({
        message, history, attachment_ids: currentFiles.map(({ id }) => id),
        new_attachment_ids: newFiles.map(({ id }) => id),
      }),
    });
    const { reply, receipts, ok, expired_attachment_ids = [] } = await readReply(response, ({ id, label, state, detail, receipt }) => {
      const step = { id, label, state, detail };
      steps[id - 1] = step;
      if (receipt) confirmedReceipts.push(receipt);
      pending.updateStep(step);
      status.textContent = state === 'running' ? `正在${label}…` : '助手正在继续处理…';
      conversation.scrollTop = conversation.scrollHeight;
    });
    expired = expired_attachment_ids;
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
    if (expired.length) {
      sentFiles = sentFiles.filter(({ id }) => !expired.includes(id));
      draftFiles = newFiles.filter(({ id }) => !expired.includes(id));
      if (!input.value.trim()) input.value = typed;
    } else {
      sentFiles = currentFiles;
    }
    transcript.push({ ...user, context: answer.context }, answer);
    saveTranscript();
    pending.updateReply(answer);
    busy = false;
    setStatus('');
    renderDraftFiles();
    conversation.scrollTop = conversation.scrollHeight;
    input.focus();
    requestFollowup(user, answer);
  }
});
