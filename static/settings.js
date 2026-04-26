'use strict';

let _currentSettings = {};

// ── Load settings ─────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const resp = await fetch('/api/settings');
    if (!resp.ok) throw new Error('Failed to load settings');
    _currentSettings = await resp.json();
    populateForm(_currentSettings);
  } catch (e) {
    console.error('Error loading settings:', e);
  }
}

function populateForm(s) {
  setVal('base_url', s.base_url);
  setVal('whisper_model', s.whisper_model);
  setVal('whisper_device', s.whisper_device);
  setVal('max_concurrent_jobs', s.max_concurrent_jobs);
  setVal('max_duration_seconds', s.max_duration_seconds);
  setVal('llm_provider', s.llm_provider);
  setVal('llm_model', s.llm_model);
  setVal('llm_base_url', s.llm_base_url);
  setVal('summary_max_words', s.summary_max_words);

  const keyHint = document.getElementById('key-hint');
  if (s.llm_api_key_masked) {
    keyHint.textContent = `Current: ${s.llm_api_key_masked}`;
  } else {
    keyHint.textContent = 'No API key set';
  }

  updateLlmVisibility(s.llm_provider);

  // Auth section
  const badge = document.getElementById('auth-badge');
  if (s.auth_enabled) {
    badge.textContent = 'Enabled';
    badge.className = 'auth-status-badge enabled';
    document.getElementById('auth-enabled-section').classList.remove('hidden');
    document.getElementById('auth-disabled-section').classList.add('hidden');
  } else {
    badge.textContent = 'Disabled';
    badge.className = 'auth-status-badge disabled';
    document.getElementById('auth-enabled-section').classList.add('hidden');
    document.getElementById('auth-disabled-section').classList.remove('hidden');
  }

  // Theme
  const savedTheme = localStorage.getItem('ytqueue_theme') || 'dark';
  setVal('theme-select', savedTheme);

  if (_currentSettings.auth_enabled) {
    const logoutLink = document.getElementById('logout-link');
    if (logoutLink) logoutLink.classList.remove('hidden');
  }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (!el || val === null || val === undefined) return;
  el.value = val;
}

// ── LLM provider visibility ───────────────────────────────────────────────────

function updateLlmVisibility(provider) {
  const showKey  = provider === 'anthropic' || provider === 'openai';
  // Show base URL for Ollama (required) and OpenAI (optional custom endpoint)
  const showBase = provider !== 'none';
  const showModel = provider !== 'none';

  document.getElementById('row-llm-key').style.display  = showKey  ? '' : 'none';
  document.getElementById('row-llm-base').style.display = showBase ? '' : 'none';
  document.getElementById('row-llm-model').style.display = showModel ? '' : 'none';
}

document.getElementById('llm_provider').addEventListener('change', (e) => {
  updateLlmVisibility(e.target.value);
});

// ── Show/hide API key ─────────────────────────────────────────────────────────

document.getElementById('toggle-key').addEventListener('click', () => {
  const input = document.getElementById('llm_api_key');
  const btn   = document.getElementById('toggle-key');
  input.type  = input.type === 'password' ? 'text' : 'password';
  btn.textContent = input.type === 'password' ? 'Show' : 'Hide';
});

// ── Save helpers ──────────────────────────────────────────────────────────────

async function saveSection(payload, statusId) {
  const statusEl = document.getElementById(statusId);
  statusEl.textContent = 'Saving…';
  statusEl.className = 'save-status';

  try {
    const resp = await fetch('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Save failed');
    }

    const data = await resp.json();
    const n = data.saved.length;
    statusEl.textContent = n > 0 ? `Saved — ${n} setting${n !== 1 ? 's' : ''} applied` : 'No changes';
    statusEl.className = 'save-status ok';
    // Refresh displayed values without overriding what the user has in the form
    _currentSettings = { ..._currentSettings, ...payload };
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.className = 'save-status err';
  }
}

// ── Save: Server ──────────────────────────────────────────────────────────────

document.getElementById('save-server').addEventListener('click', () => {
  saveSection({ base_url: document.getElementById('base_url').value.trim() }, 'status-server');
});

// ── Save: Transcription ───────────────────────────────────────────────────────

document.getElementById('save-transcription').addEventListener('click', () => {
  saveSection({
    whisper_model:        document.getElementById('whisper_model').value,
    whisper_device:       document.getElementById('whisper_device').value,
    max_concurrent_jobs:  parseInt(document.getElementById('max_concurrent_jobs').value, 10),
    max_duration_seconds: parseInt(document.getElementById('max_duration_seconds').value, 10),
  }, 'status-transcription');
});

// ── Save: LLM ─────────────────────────────────────────────────────────────────

document.getElementById('save-llm').addEventListener('click', () => {
  const apiKey  = document.getElementById('llm_api_key').value.trim();
  const baseUrl = document.getElementById('llm_base_url').value.trim();
  const payload = {
    llm_provider:      document.getElementById('llm_provider').value,
    llm_model:         document.getElementById('llm_model').value.trim(),
    summary_max_words: parseInt(document.getElementById('summary_max_words').value, 10),
  };
  if (apiKey)  payload.llm_api_key  = apiKey;
  if (baseUrl) payload.llm_base_url = baseUrl;

  saveSection(payload, 'status-llm');
});

// ── Enable authentication ─────────────────────────────────────────────────────

document.getElementById('btn-enable-auth').addEventListener('click', async () => {
  const statusEl  = document.getElementById('status-enable-auth');
  const pw        = document.getElementById('enable_password').value;
  const pw2       = document.getElementById('enable_password2').value;

  if (!pw) {
    statusEl.textContent = 'Password cannot be empty';
    statusEl.className = 'save-status err';
    return;
  }
  if (pw !== pw2) {
    statusEl.textContent = 'Passwords do not match';
    statusEl.className = 'save-status err';
    return;
  }

  statusEl.textContent = 'Enabling…';
  statusEl.className = 'save-status';

  try {
    const resp = await fetch('/api/settings/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enable: true, password: pw }),
    });
    if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || 'Failed'); }

    statusEl.textContent = 'Authentication enabled';
    statusEl.className = 'save-status ok';
    document.getElementById('enable_password').value = '';
    document.getElementById('enable_password2').value = '';
    await loadSettings();
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.className = 'save-status err';
  }
});

// ── Disable authentication ────────────────────────────────────────────────────

document.getElementById('btn-disable-auth').addEventListener('click', async () => {
  if (!confirm('Disable password protection? The app will be publicly accessible.')) return;

  const statusEl = document.getElementById('status-password');
  statusEl.textContent = 'Disabling…';
  statusEl.className = 'save-status';

  try {
    const resp = await fetch('/api/settings/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enable: false }),
    });
    if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || 'Failed'); }

    statusEl.textContent = 'Authentication disabled';
    statusEl.className = 'save-status ok';
    await loadSettings();
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.className = 'save-status err';
  }
});

// ── Change password ───────────────────────────────────────────────────────────

document.getElementById('save-password').addEventListener('click', async () => {
  const statusEl   = document.getElementById('status-password');
  const currentPw  = document.getElementById('current_password').value;
  const newPw      = document.getElementById('new_password').value;
  const confirmPw  = document.getElementById('confirm_password').value;

  if (!currentPw || !newPw) {
    statusEl.textContent = 'All password fields are required';
    statusEl.className = 'save-status err';
    return;
  }
  if (newPw !== confirmPw) {
    statusEl.textContent = 'New passwords do not match';
    statusEl.className = 'save-status err';
    return;
  }

  statusEl.textContent = 'Updating…';
  statusEl.className = 'save-status';

  try {
    const resp = await fetch('/api/settings/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
    });
    if (!resp.ok) { const e = await resp.json(); throw new Error(e.detail || 'Failed'); }

    statusEl.textContent = 'Password updated';
    statusEl.className = 'save-status ok';
    document.getElementById('current_password').value = '';
    document.getElementById('new_password').value = '';
    document.getElementById('confirm_password').value = '';
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.className = 'save-status err';
  }
});

// ── Theme toggle ─────────────────────────────────────────────────────────────

document.getElementById('theme-select').addEventListener('change', (e) => {
  const theme = e.target.value;
  localStorage.setItem('ytqueue_theme', theme);
  document.documentElement.setAttribute('data-theme', theme);
});

// ── Init ──────────────────────────────────────────────────────────────────────

loadSettings();
