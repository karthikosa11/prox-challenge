// ── Theme ─────────────────────────────────────────────────────────────────────

const MERMAID_DARK = {
  theme: 'dark',
  themeVariables: {
    primaryColor: '#1c2130', primaryTextColor: '#e2e8f5', primaryBorderColor: '#e8924a',
    lineColor: '#8896b0', secondaryColor: '#161b24', tertiaryColor: '#111318',
    background: '#111318', mainBkg: '#1c2130', nodeBorder: '#252d3e',
    titleColor: '#e8924a', edgeLabelBackground: '#1c2130',
  },
};

const MERMAID_LIGHT = {
  theme: 'default',
  themeVariables: {
    primaryColor: '#e8eef6', primaryTextColor: '#1a2540', primaryBorderColor: '#d4722a',
    lineColor: '#4a5a78', secondaryColor: '#f0f4f8', tertiaryColor: '#ffffff',
    background: '#ffffff', mainBkg: '#e8eef6', nodeBorder: '#d0dae8',
    titleColor: '#d4722a', edgeLabelBackground: '#f0f4f8',
  },
};

function isDark() {
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('icon-moon').style.display = dark ? 'block' : 'none';
  document.getElementById('icon-sun').style.display = dark ? 'none' : 'block';
  mermaid.initialize({ startOnLoad: false, flowchart: { curve: 'basis', htmlLabels: true }, securityLevel: 'loose', ...(dark ? MERMAID_DARK : MERMAID_LIGHT) });
  localStorage.setItem('theme', dark ? 'dark' : 'light');
}

document.getElementById('theme-toggle').addEventListener('click', () => applyTheme(!isDark()));

// Init theme from storage
applyTheme(localStorage.getItem('theme') !== 'light');

// ── Marked ────────────────────────────────────────────────────────────────────

marked.setOptions({
  gfm: true, breaks: true,
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
    return hljs.highlightAuto(code).value;
  },
});

// ── Quick questions ───────────────────────────────────────────────────────────

const QUESTIONS = [
  { label: 'Duty cycle at 200A / 240V', query: "What's the duty cycle for MIG at 200A on 240V?" },
  { label: 'TIG polarity wiring', query: 'Show me the polarity wiring diagram for TIG welding.' },
  { label: 'Flux-cored porosity fix', query: "I'm getting porosity in my flux-cored welds. Help me troubleshoot." },
  { label: 'MIG on ¼″ mild steel', query: 'What are the MIG settings for ¼ inch mild steel on 240V?' },
  { label: '6010 stick setup', query: 'How do I set up the machine for 6010 stick electrode?' },
  { label: 'Wire feed tensioner', query: 'Walk me through setting up the wire feed tensioner.' },
];

const WELCOME_LABELS = [
  'Duty cycle at 200A / 240V',
  'TIG polarity wiring',
  'MIG settings for ¼″ steel',
  'Porosity in flux-cored welds',
];

// ── DOM ───────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const messagesEl = $('messages');
const msgInput = $('msg-input');
const sendBtn = $('send-btn');
const toolActivity = $('tool-activity');
const toolText = $('tool-text');

const state = {
  sessionId: crypto.randomUUID(),
  isStreaming: false,
  msgEl: null,
  proseEl: null,
  rawText: '',
  images: [],
};

// ── Sidebar chips ─────────────────────────────────────────────────────────────

function setupSidebar() {
  const container = $('quick-questions');
  QUESTIONS.forEach(({ label, query }) => {
    const btn = document.createElement('button');
    btn.className = 'chip';
    btn.textContent = label;
    btn.onclick = () => { if (!state.isStreaming) { msgInput.value = query; autoResize(msgInput); sendMessage(); } };
    container.appendChild(btn);
  });
}

// ── Input helpers ─────────────────────────────────────────────────────────────

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

msgInput.addEventListener('input', () => autoResize(msgInput));
msgInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!state.isStreaming) sendMessage(); }
});

$('img-input').addEventListener('change', function() {
  Array.from(this.files).forEach(f => state.images.push({ file: f, url: URL.createObjectURL(f) }));
  this.value = '';
  renderPreviews();
});

function renderPreviews() {
  const el = $('img-previews');
  if (!state.images.length) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  el.style.display = 'flex';
  el.innerHTML = '';
  state.images.forEach((img, i) => {
    const chip = document.createElement('div');
    chip.className = 'img-chip';
    chip.innerHTML = `<img src="${img.url}" /><button onclick="removeImg(${i})">×</button>`;
    el.appendChild(chip);
  });
}

function removeImg(i) {
  URL.revokeObjectURL(state.images[i].url);
  state.images.splice(i, 1);
  renderPreviews();
}

// ── Send ──────────────────────────────────────────────────────────────────────

async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text && !state.images.length) return;
  if (state.isStreaming) return;

  const welcome = $('welcome');
  if (welcome) welcome.remove();

  state.isStreaming = true;
  sendBtn.disabled = true;
  msgInput.disabled = true;
  setStatus('thinking', 'Thinking...');

  addUserMsg(text, state.images);

  const form = new FormData();
  form.append('message', text || 'Analyze this image.');
  form.append('session_id', state.sessionId);
  state.images.forEach(img => form.append('images', img.file));

  msgInput.value = '';
  autoResize(msgInput);
  state.images = [];
  renderPreviews();

  const { msgEl, proseEl } = addAssistantMsg();
  state.msgEl = msgEl;
  state.proseEl = proseEl;
  state.rawText = '';

  try {
    const res = await fetch('/api/chat', { method: 'POST', body: form });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split(/\r\n\r\n|\n\n/);
      buf = frames.pop();
      frames.forEach(f => { const e = parseFrame(f); if (e) handleEvent(e.event, e.data); });
    }
  } catch (err) {
    console.error(err);
    if (state.proseEl) {
      const spinner = state.proseEl.querySelector('.loading-dots');
      if (spinner) spinner.remove();
      state.proseEl.innerHTML = `<span style="color:var(--red);">Error: ${esc(err.message)}</span>`;
    }
    finalize();
  }
}

// ── SSE parsing ───────────────────────────────────────────────────────────────

function parseFrame(frame) {
  let event = 'message', data = null;
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) {
      try { data = JSON.parse(line.slice(5).trim()); } catch { data = line.slice(5).trim(); }
    }
  }
  return data !== null ? { event, data } : null;
}

function handleEvent(event, data) {
  switch (event) {
    case 'text_delta':    state.rawText += data.chunk || ''; break;
    case 'clear_text':   state.rawText = ''; break;
    case 'tool_start':   showTool(data); break;
    case 'tool_result':  hideTool(); break;
    case 'artifact':     renderArtifact(data); break;
    case 'manual_image': renderManualThumb(data); break;
    case 'done':         finalize(); break;
    case 'error':
      if (state.proseEl) {
        const spinner = state.proseEl.querySelector('.loading-dots');
        if (spinner) spinner.remove();
        state.proseEl.innerHTML = `<span style="color:var(--red);">Error: ${esc(data.message || 'Something went wrong')}</span>`;
      }
      finalize();
      break;
  }
}

// ── Tool status ───────────────────────────────────────────────────────────────

function showTool(data) {
  const labels = { search_manual: '🔍 Searching manual...', get_page_images: '🖼️  Fetching diagrams...' };
  toolText.textContent = labels[data.name] || `Running ${data.name}...`;
  toolActivity.classList.remove('hidden');
  setStatus('working', 'Working...');
}

function hideTool() {
  toolActivity.classList.add('hidden');
  setStatus('thinking', 'Thinking...');
}

// ── Artifacts ─────────────────────────────────────────────────────────────────

function renderArtifact(data) {
  if (!state.msgEl) return;
  const { type, title, content } = data;
  const icons = { html: '⚙️', svg: '🔌', mermaid: '📊' };
  const labels = { html: 'Interactive', svg: 'Diagram', mermaid: 'Flowchart' };

  const wrap = document.createElement('div');
  wrap.className = 'artifact-wrap';
  wrap.innerHTML = `
    <div class="artifact-bar">
      <span>${icons[type] || '📄'}</span>
      <span style="font-size:0.83em; font-weight:600; color:var(--text); flex:1;">${esc(title)}</span>
      <span style="font-size:0.68em; color:var(--text3); text-transform:uppercase; letter-spacing:0.05em;">${labels[type] || type}</span>
    </div>
    <div class="artifact-body"></div>
  `;
  const body = wrap.querySelector('.artifact-body');
  state.msgEl.appendChild(wrap);

  if (type === 'html') {
    const iframe = document.createElement('iframe');
    iframe.sandbox = 'allow-scripts';
    iframe.style.cssText = 'width:100%;border:none;min-height:260px;display:block;';
    window.addEventListener('message', e => {
      if (e.source === iframe.contentWindow && e.data?.type === 'resize') iframe.style.height = (e.data.height + 16) + 'px';
    });
    iframe.srcdoc = content;
    body.appendChild(iframe);

  } else if (type === 'svg') {
    body.style.cssText = 'padding:16px; display:flex; justify-content:center; background:var(--bg3);';
    const d = document.createElement('div');
    d.style.maxWidth = '100%';
    d.innerHTML = content;
    const svg = d.querySelector('svg');
    if (svg) { svg.style.maxWidth = '100%'; svg.style.height = 'auto'; }
    body.appendChild(d);

  } else if (type === 'mermaid') {
    body.style.cssText = 'padding:16px; overflow-x:auto; background:var(--bg);';
    const el = document.createElement('div');
    el.className = 'mermaid';
    el.id = 'mmd-' + Math.random().toString(36).slice(2, 8);
    el.textContent = content;
    body.appendChild(el);
    mermaid.run({ nodes: [el] }).catch(() => {
      el.innerHTML = `<pre style="color:var(--accent);font-size:0.8em;white-space:pre-wrap;">${esc(content)}</pre>`;
    });
  }

  scrollBottom();
}

function renderManualThumb(data) {
  if (!state.msgEl) return;
  const { pdf, page, caption } = data;
  const url = `/api/image/${encodeURIComponent(pdf)}/${page}`;
  const names = { 'owner-manual': "Owner's Manual", 'quick-start-guide': 'Quick-Start Guide', 'selection-chart': 'Selection Chart' };

  const el = document.createElement('div');
  el.className = 'manual-ref';
  el.innerHTML = `
    <img src="${url}" alt="p${page}" onerror="this.style.display='none'" />
    <div>
      <div style="font-size:0.72em; color:var(--accent); font-weight:600;">${names[pdf] || pdf}</div>
      <div style="font-size:0.8em; color:var(--text2);">Page ${page}</div>
      ${caption ? `<div style="font-size:0.72em; color:var(--text3); margin-top:2px;">${esc(caption)}</div>` : ''}
    </div>
  `;
  el.onclick = () => openLightbox(url);
  state.msgEl.appendChild(el);
  scrollBottom();
}

// ── Finalize ──────────────────────────────────────────────────────────────────

function finalize() {
  if (state.proseEl) {
    const spinner = state.proseEl.querySelector('.loading-dots');
    if (spinner) spinner.remove();

    if (state.rawText) {
      const clean = state.rawText
        .replace(/<artifact[\s\S]*?<\/artifact>/g, '')
        .replace(/<manual-image[\s\S]*?\/>/g, '')
        .trim();
      if (clean) {
        state.proseEl.innerHTML = marked.parse(clean);
        state.proseEl.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
      }
    }
  }

  toolActivity.classList.add('hidden');
  state.isStreaming = false;
  state.msgEl = null;
  state.proseEl = null;
  state.rawText = '';
  sendBtn.disabled = false;
  msgInput.disabled = false;
  msgInput.focus();
  setStatus('ready', 'Ready');
  scrollBottom();
}

// ── Message builders ──────────────────────────────────────────────────────────

function addUserMsg(text, images) {
  const el = document.createElement('div');
  el.style.cssText = 'display:flex; justify-content:flex-end; margin-bottom:16px;';
  el.innerHTML = `
    <div style="max-width:72%;">
      ${images.length ? `<div style="display:flex; gap:6px; margin-bottom:6px; justify-content:flex-end; flex-wrap:wrap;">${images.map(i => `<img src="${i.url}" style="width:70px;height:70px;object-fit:cover;border-radius:8px;border:1px solid var(--border);" />`).join('')}</div>` : ''}
      ${text ? `<div class="user-bubble">${esc(text)}</div>` : ''}
    </div>
  `;
  messagesEl.appendChild(el);
  scrollBottom();
}

function addAssistantMsg() {
  const el = document.createElement('div');
  el.style.marginBottom = '20px';

  const header = document.createElement('div');
  header.className = 'assistant-header';
  header.innerHTML = `
    <div class="assistant-avatar">⚡</div>
    <span style="font-size:0.78em; color:var(--text3); font-weight:500;">OmniPro Assistant</span>
  `;

  const proseEl = document.createElement('div');
  proseEl.className = 'prose';
  proseEl.style.paddingLeft = '32px';

  const dots = document.createElement('span');
  dots.className = 'loading-dots';
  dots.innerHTML = '<span></span><span></span><span></span>';
  proseEl.appendChild(dots);

  el.appendChild(header);
  el.appendChild(proseEl);
  messagesEl.appendChild(el);
  scrollBottom();

  return { msgEl: el, proseEl };
}

// ── Clear session ─────────────────────────────────────────────────────────────

$('clear-btn').addEventListener('click', async () => {
  if (state.isStreaming) return;
  const form = new FormData();
  form.append('session_id', state.sessionId);
  await fetch('/api/clear', { method: 'POST', body: form });
  state.sessionId = crypto.randomUUID();
  messagesEl.innerHTML = '';

  const welcome = document.createElement('div');
  welcome.id = 'welcome';
  welcome.style.cssText = 'margin: 60px auto 0; max-width: 460px;';
  welcome.innerHTML = `
    <div style="font-size:1.6rem; font-weight:700; color:var(--text); margin-bottom:6px;">What can I help with?</div>
    <div style="font-size:0.88rem; color:var(--text2); margin-bottom:22px; line-height:1.6;">
      Ask anything about the OmniPro 220 — I'll pull the specs from the manual and show you a diagram if it helps.
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
      ${WELCOME_LABELS.map((label, i) => {
        const subtitles = ['MIG process', 'DCEN setup diagram', 'Wire speed & voltage', 'Troubleshoot & fix'];
        return `<div class="welcome-card" onclick="askCard(this)">
          <div style="font-size:0.83rem; font-weight:500; color:var(--text); margin-bottom:3px;">${label}</div>
          <div style="font-size:0.73rem; color:var(--text3);">${subtitles[i]}</div>
        </div>`;
      }).join('')}
    </div>
  `;
  messagesEl.appendChild(welcome);
});

// ── Welcome card click ────────────────────────────────────────────────────────

function askCard(card) {
  if (state.isStreaming) return;
  const title = card.querySelector('div').textContent.trim();
  const match = QUESTIONS.find(q => q.label === title);
  if (match) { msgInput.value = match.query; autoResize(msgInput); sendMessage(); }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setStatus(s, text) {
  $('status-text').textContent = text;
  const colors = { ready: 'var(--green)', thinking: 'var(--accent)', working: 'var(--blue)' };
  $('status-indicator').style.background = colors[s] || 'var(--text3)';
}

function openLightbox(url) { $('lightbox-img').src = url; $('lightbox').classList.add('open'); }
function closeLightbox() { $('lightbox').classList.remove('open'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function esc(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

sendBtn.addEventListener('click', () => { if (!state.isStreaming) sendMessage(); });

setupSidebar();
msgInput.focus();
