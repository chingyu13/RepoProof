const jszipScript = document.createElement('script');
jszipScript.src = '/static/vendor/jszip.min.js';
jszipScript.onerror = () => {
  const fallback = document.createElement('script');
  fallback.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
  document.head.appendChild(fallback);
};
document.head.appendChild(jszipScript);

const $ = id => document.getElementById(id);
let currentProject = null;
let pendingFile = null;
let maxProjectMB = 1024;
let priorContextFiles = [];
let scopeContextFiles = [];
let localProvider = {url:'http://127.0.0.1:11434', model:'qwen2.5-coder:7b'};
let localModelReady = false;
let localSetupPlatform = /Windows/i.test(navigator.userAgent) ? 'windows' : 'macos';
let localCopyReset = null;

/* theme */
const savedTheme = localStorage.getItem('rp-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
else if (matchMedia('(prefers-color-scheme: dark)').matches) document.documentElement.dataset.theme = 'dark';
function syncThemeBtn(){
  const dark = document.documentElement.dataset.theme === 'dark';
  $('segSun').classList.toggle('active', !dark);
  $('segMoon').classList.toggle('active', dark);
}
$('themeToggle').onclick = ()=>{
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('rp-theme', next);
  syncThemeBtn();
};
syncThemeBtn();

/* stepper state */
let currentStep = 1;
let maxUnlockedStep = 1;
function renderStepper(){
  document.querySelectorAll('#stepper .step').forEach(el=>{
    const s = +el.dataset.step;
    const locked = s > maxUnlockedStep;
    el.classList.toggle('done', s < maxUnlockedStep && s !== currentStep);
    el.classList.toggle('current', s === currentStep);
    el.classList.toggle('locked', locked);
    el.setAttribute('aria-disabled', locked ? 'true' : 'false');
    if (s === currentStep) el.setAttribute('aria-current', 'step');
    else el.removeAttribute('aria-current');
  });
  const labels = ['Link the Project', 'Question Framework', 'Review and Approve', 'Publish Assessment'];
  const previous = $('stepPrevious'), next = $('stepNext');
  const canGoBack = currentStep > 1;
  const canGoForward = currentStep < maxUnlockedStep;
  previous.classList.toggle('hidden', !canGoBack);
  next.classList.toggle('hidden', !canGoForward);
  previous.setAttribute('aria-label', canGoBack ? `Back to ${labels[currentStep - 2]}` : 'Previous step');
  next.setAttribute('aria-label', canGoForward ? `Continue to ${labels[currentStep]}` : 'Next step');
}
function goToStep(n, {unlock=false}={}){
  if (unlock) maxUnlockedStep = Math.max(maxUnlockedStep, n);
  if (n < 1 || n > 4 || n > maxUnlockedStep) return;
  currentStep = n;
  renderStepper();
  const workflow = $('workflow');
  workflow.scrollTo({left:(n - 1) * workflow.clientWidth, behavior:'smooth'});
  window.scrollTo({top:0, behavior:'smooth'});
}
document.querySelectorAll('#stepper .step').forEach(el=>{
  const activate = ()=>goToStep(+el.dataset.step);
  el.addEventListener('click', activate);
  el.addEventListener('keydown', e=>{
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
  });
});
$('stepPrevious').onclick = ()=>goToStep(currentStep - 1);
$('stepNext').onclick = ()=>goToStep(currentStep + 1);
window.addEventListener('resize', ()=>{
  $('workflow').scrollTo({left:(currentStep - 1) * $('workflow').clientWidth, behavior:'auto'});
});
renderStepper();

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(()=>({detail:r.statusText}));
  if (r.status === 401) {
    location.href = '/?login=required';
    throw new Error('Creator session expired.');
  }
  if (!r.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

function renderContextFileTags(tagsId, files, inputId){
  const tags = $(tagsId);
  tags.replaceChildren();
  files.forEach((file, index)=>{
    const tag = document.createElement('span');
    tag.className = 'context-file-tag';
    tag.title = file.name;
    const name = document.createElement('span');
    name.className = 'context-file-name';
    name.textContent = file.name;
    const remove = document.createElement('button');
    remove.className = 'context-file-remove';
    remove.type = 'button';
    remove.textContent = '×';
    remove.setAttribute('aria-label', `Remove ${file.name}`);
    remove.title = `Remove ${file.name}`;
    remove.onclick = ()=>{
      files.splice(index, 1);
      if (inputId) $(inputId).value = '';
      renderContextFileTags(tagsId, files, inputId);
    };
    tag.append(name, remove);
    tags.appendChild(tag);
  });
}

function bindContextFiles(buttonId, inputId, tagsId, target){
  const input = $(inputId);
  $(buttonId).onclick = ()=>input.click();
  input.onchange = ()=>{
    target.splice(0, target.length, ...input.files);
    renderContextFileTags(tagsId, target, inputId);
  };
}
bindContextFiles('uploadPrior', 'priorFiles', 'priorFileTags', priorContextFiles);
bindContextFiles('uploadScope', 'scopeFiles', 'scopeFileTags', scopeContextFiles);

function selectedLlm(){
  const option = $('gProvider').selectedOptions[0];
  return {
    provider: option?.dataset.provider || 'mock',
    model: option?.dataset.model || '',
  };
}

function localSetupCommand(platform){
  const model = encodeURIComponent(localProvider.model);
  return platform === 'windows'
    ? `irm '${location.origin}/api/local-setup/windows/script?model=${model}' | iex`
    : `curl -fsSL '${location.origin}/api/local-setup/macos/script?model=${model}' | /bin/zsh`;
}

function setLocalPlatform(platform){
  localSetupPlatform = platform === 'windows' ? 'windows' : 'macos';
  const windows = localSetupPlatform === 'windows';
  $('localMac').classList.toggle('active', !windows);
  $('localWindows').classList.toggle('active', windows);
  $('localMac').setAttribute('aria-selected', String(!windows));
  $('localWindows').setAttribute('aria-selected', String(windows));
  $('localTerminalStep').textContent = windows
    ? 'Open Windows Terminal or PowerShell, paste this command, then press Enter:'
    : 'Open Terminal, paste this command, then press Return:';
  $('localCommand').textContent = localSetupCommand(localSetupPlatform);
  $('localCopy').textContent = 'Copy';
  $('localCopy').classList.remove('copied');
}

async function copyLocalSetupCommand(){
  const command = localSetupCommand(localSetupPlatform);
  const button = $('localCopy');
  clearTimeout(localCopyReset);
  try {
    await navigator.clipboard.writeText(command);
    button.textContent = 'Copied';
    button.classList.add('copied');
  } catch (_error) {
    const range = document.createRange();
    range.selectNodeContents($('localCommand'));
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    button.textContent = localSetupPlatform === 'windows' ? 'Press Ctrl+C' : 'Press ⌘C';
  }
  localCopyReset = setTimeout(()=>{
    button.textContent = 'Copy';
    button.classList.remove('copied');
  }, 1800);
}

function setLocalStatus(text, {install=false, pull=false, checking=true, progress=null, ready=false}={}){
  $('providerNote').textContent = text;
  $('localSetup').classList.toggle('ready', ready);
  $('localInstructions').classList.toggle('hidden', !install);
  $('localPull').classList.toggle('hidden', !pull);
  $('localCheck').classList.toggle('hidden', !checking);
  $('localProgress').classList.toggle('hidden', progress === null);
  if (progress !== null) {
    $('localProgress').firstElementChild.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  }
}

async function localFetch(path, options={}, timeoutMs=4000){
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(), timeoutMs);
  try {
    return await fetch(`${localProvider.url}${path}`, {...options, signal:controller.signal});
  } finally {
    clearTimeout(timer);
  }
}

async function checkLocalModel(){
  localModelReady = false;
  const selectedModel = localProvider.model;
  setLocalStatus('Checking local Ollama…', {checking:false});
  try {
    const response = await localFetch('/api/tags');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    const installed = (body.models || []).some(model=>
      model.name === selectedModel || model.model === selectedModel);
    if (selectedModel !== localProvider.model) return false;
    localModelReady = installed;
    if (installed) {
      setLocalStatus(`${selectedModel} ready.`, {checking:false, ready:true});
    } else {
      setLocalStatus(`${selectedModel} is not installed.`, {pull:true});
    }
  } catch (_error) {
    if (selectedModel === localProvider.model) {
      setLocalStatus(`${selectedModel} is not detected.`, {install:true});
    }
  }
  return localModelReady;
}

async function pullLocalModel(){
  const selectedModel = localProvider.model;
  $('localPull').disabled = true;
  setLocalStatus(`Downloading ${selectedModel}…`, {checking:false, progress:0});
  try {
    const response = await fetch(`${localProvider.url}/api/pull`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:selectedModel, stream:true}),
    });
    if (!response.ok) throw new Error(`Model download failed (HTTP ${response.status}).`);
    if (response.body) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = '';
      while (true) {
        const {value, done} = await reader.read();
        buffered += decoder.decode(value || new Uint8Array(), {stream:!done});
        const lines = buffered.split('\n');
        buffered = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const update = JSON.parse(line);
          if (update.total && update.completed) {
            const percent = Math.round(update.completed / update.total * 100);
            setLocalStatus(`Downloading ${selectedModel}… ${percent}%`, {
              checking:false, progress:percent,
            });
          }
        }
        if (done) break;
      }
    }
    await checkLocalModel();
  } catch (error) {
    setLocalStatus(error.message || 'Model download failed.', {pull:true});
  } finally {
    $('localPull').disabled = false;
  }
}

function syncLocalSetup(){
  const selected = selectedLlm();
  const local = selected.provider === 'local';
  $('localSetup').classList.toggle('hidden', !local);
  if (local) {
    localProvider.model = selected.model;
    setLocalPlatform(localSetupPlatform);
    checkLocalModel();
  }
}

$('localCheck').onclick = checkLocalModel;
$('localPull').onclick = pullLocalModel;
$('localMac').onclick = ()=>setLocalPlatform('macos');
$('localWindows').onclick = ()=>setLocalPlatform('windows');
$('localCopy').onclick = copyLocalSetupCommand;
setLocalPlatform(localSetupPlatform);

$('logout').onclick = async ()=>{
  await fetch('/api/logout', {method:'POST'});
  location.href = '/';
};

async function loadMeta(){
  const m = await api('/api/meta');
  maxProjectMB = m.max_project_mb;
  $('consentText').textContent = m.consent_text;
  if (m.data_sharing_text) $('shareDataText').textContent = m.data_sharing_text;
  const size = m.max_project_mb >= 1024 ? `${(m.max_project_mb/1024).toLocaleString()} GB` : `${m.max_project_mb.toLocaleString()} MB`;
  $('sizeNote').textContent = `Any code project up to ${size}`;
  $('sizeNote').title = `Larger projects: Pro tier pending — ${m.pro_contact}`;
  if (m.mock_mode) $('mockBadge').classList.remove('hidden');

  const p = m.providers || {};
  localProvider = {
    url:(p.local?.url || 'http://127.0.0.1:11434').replace(/\/$/, ''),
    model:p.local?.model || 'qwen2.5-coder:7b',
  };
  const sel = $('gProvider');
  sel.innerHTML = '';
  const addOpt = (value, label, enabled, provider, model='', hidden=false) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    option.disabled = !enabled;
    option.hidden = hidden;
    option.dataset.provider = provider;
    option.dataset.model = model;
    sel.appendChild(option);
  };
  const openaiModels = p.openai?.models || [
    {id:p.openai?.model || 'gpt-4o-mini', name:p.openai?.model || 'GPT API', note:''},
  ];
  openaiModels.forEach(model=>{
    const note = model.note ? ` — ${model.note}` : '';
    const unavailable = p.openai?.available ? '' : ' — no key';
    addOpt(
      `openai:${model.id}`,
      `OpenAI · ${model.name}${note}${unavailable}`,
      !!p.openai?.available,
      'openai',
      model.id,
    );
  });
  const localModels = p.local?.models || [{
    id:p.local?.model || 'qwen2.5-coder:7b',
    name:p.local?.model || 'Qwen 2.5 Coder 7B',
    note:'',
    think:null,
  }];
  localModels.forEach(model=>{
    const note = model.note ? ` — ${model.note}` : '';
    addOpt(
      `local:${model.id}`,
      `Local · ${model.name}${note}`,
      true,
      'local',
      model.id,
    );
  });
  const hasRealModel = !!p.openai?.available || !!p.local?.available;
  addOpt(
    'mock',
    'Mock (free, no LLM)',
    true,
    'mock',
    '',
    hasRealModel && p.default !== 'mock',
  );
  const preferred = p.default === 'openai'
    ? `openai:${p.openai?.model || ''}`
    : p.default === 'local'
      ? `local:${p.local?.model || ''}`
      : 'mock';
  sel.value = preferred;
  if (!sel.selectedOptions[0] || sel.selectedOptions[0].disabled) {
    const fallback = [...sel.options].find(option=>!option.disabled && !option.hidden);
    sel.value = fallback?.value || 'mock';
  }
  syncPlanControls();   // blueprint step only applies to the planned providers
  syncLocalSetup();

  topicCatalog = m.topics || [];
  areas = [
    ['architecture', 4], ['api', 3], ['data_flow', 5], ['project_logic', 2], ['database', 3],
  ].filter(([id])=>topicCatalog.some(topic=>topic.id === id)).map(([id, w])=>({id, w}));
  renderAreas();
}

/* drag & drop */
const dz = $('dropZone');
['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev, e=>{e.preventDefault(); dz.classList.add('hover');}));
['dragleave','drop'].forEach(ev=>dz.addEventListener(ev, e=>{e.preventDefault(); dz.classList.remove('hover');}));
dz.addEventListener('drop', async e=>{
  const item = e.dataTransfer.items && e.dataTransfer.items[0];
  const entry = item && item.webkitGetAsEntry && item.webkitGetAsEntry();
  if (entry && entry.isDirectory) {           // a folder was dropped
    try {
      const out = [];
      await readEntries(entry, '', out);
      await packAndStage(out, entry.name);
    } catch(err){ $('projectErr').textContent = 'Could not read the folder: ' + err.message; }
    return;
  }
  const f = e.dataTransfer.files[0];
  if (f) setPendingFile(f);
});

async function readEntries(entry, prefix, out){
  const SKIP = /(^|\/)(\.git|node_modules|\.venv|venv|__pycache__|dist|build|\.idea|\.vscode)(\/|$)/;
  if (entry.isFile) {
    const f = await new Promise((res, rej)=>entry.file(res, rej));
    out.push({file: f, rel: prefix + entry.name});
  } else if (entry.isDirectory) {
    if (SKIP.test('/' + prefix + entry.name + '/')) return;
    const reader = entry.createReader();
    let batch;
    do {
      batch = await new Promise((res, rej)=>reader.readEntries(res, rej));
      for (const e of batch) await readEntries(e, prefix + entry.name + '/', out);
    } while (batch.length);
  }
}
$('selectFileBtn').onclick = ()=>$('zipFile').click();
$('zipFile').onchange = ()=>{ if ($('zipFile').files[0]) setPendingFile($('zipFile').files[0]); };

/* folder upload: pack the selected folder into a zip in the browser */
const folderSupported = 'webkitdirectory' in document.createElement('input');
if (!folderSupported) {
  $('selectFolderBtn').disabled = true;
  $('selectFolderBtn').title = 'Your browser does not support folder selection — zip the folder and use Select File.';
}
$('selectFolderBtn').addEventListener('click', (e)=>{
  e.preventDefault();
  $('projectErr').textContent = '';
  $('folderInput').value = '';
  $('folderInput').click();
});
$('folderInput').addEventListener('change', async ()=>{
  try {
    const files = [...$('folderInput').files];
    if (!files.length) { $('projectErr').textContent = 'No files received from the folder picker. Try dragging the folder onto the drop zone instead.'; return; }
    const list = files.map(f => ({file: f, rel: f.webkitRelativePath || f.name}));
    const folderName = (list[0].rel.split('/')[0]) || 'project';
    await packAndStage(list, folderName);
  } catch(e){ $('projectErr').textContent = 'Folder selection failed: ' + e.message; }
});

const ANALYZE_EXT = new Set([
  'py','ipynb','r','rmd','java','kt','scala','js','jsx','mjs','ts','tsx','vue',
  'html','htm','css','scss','sql','c','h','cpp','cc','hpp','cs','go','rs','rb',
  'php','sh','ps1','swift','jl','lua','pl','m','dart','yaml','yml','toml','json',
  'md','txt','csv','tsv','xml','cfg','ini','gradle','env','properties'
]);
const KEEP_NAMES = new Set(['dockerfile','procfile','makefile','license','description','gemfile','rakefile']);
const NOTEBOOK_MAX = 25 * 1_000_000;   // notebooks embed outputs — allow larger
const TEXT_FILE_MAX = 3 * 1_000_000;   // skip oversized data/text files (server skips them too)

function analyzableFile(rel, size){
  const base = rel.split('/').pop().toLowerCase();
  if (base.includes('.min.')) return false;                 // minified bundles
  const ext = base.includes('.') ? base.split('.').pop() : '';
  const okType = ANALYZE_EXT.has(ext) || KEEP_NAMES.has(base)
    || base.startsWith('readme') || base.startsWith('requirements') || base.startsWith('.env');
  if (!okType) return false;
  return size <= (ext === 'ipynb' ? NOTEBOOK_MAX : TEXT_FILE_MAX);
}

async function packAndStage(list, folderName){
  $('projectErr').textContent = '';
  if (typeof JSZip === 'undefined') {
    $('projectErr').textContent = 'Folder packing needs internet access (JSZip CDN). Please zip the folder yourself and use Select File.';
    return;
  }
  const SKIP = /(^|\/)(\.git|node_modules|\.venv|venv|__pycache__|dist|build|\.idea|\.vscode)(\/|$)/;
  const preDir = list.filter(x => !SKIP.test('/' + x.rel));
  const kept = preDir.filter(x => analyzableFile(x.rel, x.file.size));
  const skipped = preDir.length - kept.length;
  if (!kept.length) {
    $('projectErr').textContent = 'No analyzable source files found in this folder — it looks like it only contains images, media, or other binaries. RepoProof analyzes code and text files.';
    return;
  }
  const total = kept.reduce((a,x)=>a+x.file.size, 0);
  if (total > maxProjectMB * 1_000_000) {
    $('projectErr').textContent = `Code/text content is ${(total/1_000_000).toFixed(0)} MB — over the ${maxProjectMB.toLocaleString()} MB limit. Pro tier pending — jobs@chingyu.site`;
    return;
  }
  $('fileRow').classList.remove('hidden');
  $('fileName').textContent = folderName + '/';
  $('fileMeta').innerHTML = `<span class="spin"></span> Packing ${kept.length} files${skipped ? ` (skipping ${skipped} non-code)` : ''}…`;
  try {
    const zip = new JSZip();
    kept.forEach(x => zip.file(x.rel, x.file));
    const blob = await zip.generateAsync({type:'blob', compression:'DEFLATE', compressionOptions:{level:1}});
    pendingFile = new File([blob], folderName + '.zip', {type:'application/zip'});
    $('fileName').textContent = folderName + '.zip';
    $('fileMeta').textContent = `${(blob.size/1_000_000).toFixed(1)} MB · ${kept.length} code/text files`
      + (skipped ? ` · ${skipped} non-code skipped` : '') + ' · ready to analyze';
  } catch(e) {
    $('fileMeta').textContent = '';
    $('projectErr').textContent = 'Could not pack the folder: ' + e.message;
  }
}
function setPendingFile(f){
  if (!f.name.toLowerCase().endsWith('.zip')) { $('projectErr').textContent = 'Only .zip archives are supported.'; return; }
  pendingFile = f;
  $('projectErr').textContent = '';
  $('fileRow').classList.remove('hidden');
  $('fileName').textContent = f.name;
  $('fileMeta').textContent = `${(f.size/1_000_000).toFixed(1)} MB · ready to analyze`;
}

async function submitProject({url, file}){
  $('projectErr').textContent='';
  if (!$('consent').checked) { $('projectErr').textContent = 'Please accept the required acknowledgment first.'; return; }
  const fd = new FormData();
  fd.append('github_url', url || '');
  fd.append('acknowledge', 'true');
  fd.append('share_data', $('shareData').checked ? 'true' : 'false');
  if (file) fd.append('file', file);
  const btn = $('analyzeProject');
  btn.disabled = true;
  if (file) $('fileMeta').innerHTML = `<span class="spin"></span> Analysing…`;
  btn.textContent = 'Analysing…';
  try {
    const p = await api('/api/projects', {method:'POST', body:fd});
    if (file) $('fileMeta').innerHTML = `<span class="status-ok">● Analyzed successfully</span>`;
    await loadProjects();
    await openProject(p.id);
  } catch(e){
    $('projectErr').textContent = e.message;
    if (file) $('fileMeta').textContent = 'Failed — see error below.';
  }
  btn.disabled = false; btn.textContent = 'Analyse project';
}
$('analyzeProject').onclick = ()=>{
  const url = $('ghUrl').value.trim();
  if (!url && !pendingFile) {
    $('projectErr').textContent = 'Paste a GitHub URL or drop a project file or folder.';
    return;
  }
  if (url && pendingFile) {
    $('projectErr').textContent = 'Choose one project source: either the URL or the selected upload.';
    return;
  }
  submitProject({url, file:pendingFile});
};

async function loadProjects(){
  const ps = await api('/api/projects');
  const ul = $('projectList');
  ul.innerHTML = ps.length ? '' : '<li class="small">None yet.</li>';
  ps.forEach(p=>{
    const li = document.createElement('li');
    const title = document.createElement('span');
    const name = document.createElement('strong');
    name.textContent = p.name;
    const meta = document.createElement('span');
    meta.className = 'small';
    meta.textContent = ` · ${p.source_type} · snapshot ${p.snapshot_id}`;
    title.append(name, meta);
    const files = document.createElement('span');
    files.className = 'small';
    files.textContent = `${p.stats.source_files ?? p.stats.python_files} source files`;
    const remove = document.createElement('button');
    remove.className = 'secondary project-delete';
    remove.type = 'button';
    remove.title = 'Delete project';
    remove.setAttribute('aria-label', `Delete ${p.name}`);
    remove.textContent = '×';
    remove.onclick = async event=>{
      event.stopPropagation();
      if (!confirm(`Delete ${p.name} and its generated assessments?`)) return;
      try {
        await api(`/api/projects/${p.id}`, {method:'DELETE'});
        if (currentProject === p.id) {
          currentProject = null;
          document.querySelectorAll('.project-content').forEach(el=>el.classList.add('hidden'));
          maxUnlockedStep = 1;
          goToStep(1);
        }
        await loadProjects();
      } catch (error) {
        $('projectErr').textContent = error.message;
      }
    };
    li.append(title, files, remove);
    li.onclick = ()=>openProject(p.id);
    ul.appendChild(li);
  });
}

async function openProject(id){
  const p = await api('/api/projects/'+id);
  if (currentProject !== null && currentProject !== id) {
    $('assumedKnowledge').value = '';
    $('projectScope').value = '';
    document.querySelectorAll('textarea.autogrow').forEach(el=>{ el.style.height = ''; });
    priorContextFiles.splice(0);
    scopeContextFiles.splice(0);
    $('priorFiles').value = '';
    $('scopeFiles').value = '';
    renderContextFileTags('priorFileTags', priorContextFiles, 'priorFiles');
    renderContextFileTags('scopeFileTags', scopeContextFiles, 'scopeFiles');
  }
  currentProject = id;
  document.querySelectorAll('.project-content').forEach(el=>el.classList.remove('hidden'));
  $('projTitle').textContent = `${p.name} — snapshot ${p.snapshot_id}`;
  const s = p.stats;
  const langs = Object.entries(s.files_by_language || {}).map(([k,v])=>`${v} ${k}`).join(', ')
                || `${s.python_files} Python`;
  $('projStats').textContent = `${s.source_files ?? s.python_files} source files (${langs}) · ${s.functions} functions · ${s.lines_of_code.toLocaleString()} LOC · ${p.chunk_count} evidence chunks` + (s.parse_errors?` · ${s.parse_errors} parse errors`:'');
  const qs = await loadQuestions();
  const as = await loadAssessments();
  goToStep(as.length ? 4 : (qs.length ? 3 : 2), {unlock:true});
}

$('gMode').onchange = ()=>{
  const exact = $('gMode').value==='exact';
  $('gExactWrap').classList.toggle('hidden', !exact);
  $('gRangeWrap').classList.toggle('hidden', exact);
};

const difficultyIcons = {
  1:'/static/assets/easy_easy.svg',
  2:'/static/assets/easy.svg',
  3:'/static/assets/mid.svg',
  4:'/static/assets/hard.svg',
  5:'/static/assets/hard_hard.svg',
};
function syncDifficultyIcon(normalize=false){
  const raw = $('gDiffAvg').value;
  if (raw === '') return;
  const level = Math.min(5, Math.max(1, Math.round(+raw || 3)));
  if (normalize) $('gDiffAvg').value = level;
  $('difficultyIcon').src = difficultyIcons[level];
  $('difficultyIcon').alt = `Difficulty ${level}`;
}
$('gDiffAvg').addEventListener('input', ()=>syncDifficultyIcon());
$('gDiffAvg').addEventListener('change', ()=>syncDifficultyIcon(true));
syncDifficultyIcon(true);

let topicCatalog = [];
let areas = [];
const topicById = id => topicCatalog.find(topic => topic.id === id);
function escXml(s){ return (s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function drawRadar(){
  const svg = $('radar');
  const n = areas.length, cx = 150, cy = 130, R = 112, LVL = 5;
  const pt = (i, r) => {
    const a = -Math.PI/2 + i * 2 * Math.PI / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  if (n < 3) { svg.innerHTML = `<text x="150" y="155" text-anchor="middle" class="radar-label">Add at least 3 focus areas</text>`; return; }
  let s = '';
  for (let l = 1; l <= LVL; l++) {
    const pts = Array.from({length:n}, (_,i)=>pt(i, R*l/LVL).join(',')).join(' ');
    s += `<polygon points="${pts}" class="radar-grid"/>`;
  }
  for (let i = 0; i < n; i++) {
    const [x,y] = pt(i, R);
    s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" class="radar-spoke"/>`;
  }
  const dataPts = areas.map((a,i)=>pt(i, R * Math.max(0, Math.min(5, a.w)) / LVL));
  s += `<polygon points="${dataPts.map(p=>p.join(',')).join(' ')}" class="radar-area"/>`;
  dataPts.forEach(p=>{ s += `<circle cx="${p[0]}" cy="${p[1]}" r="4" class="radar-dot"/>`; });
  areas.forEach((a,i)=>{
    const [x,y] = pt(i, R + 12);
    let labelX = x;
    let anchor = Math.abs(x - cx) < 10 ? 'middle' : (x > cx ? 'start' : 'end');
    if (x < 70) { labelX = 4; anchor = 'start'; }
    if (x > 230) { labelX = 296; anchor = 'end'; }
    const name = (topicById(a.id) || {name:a.id}).name;
    s += `<text x="${labelX}" y="${y + 3}" text-anchor="${anchor}" class="radar-label">${escXml(name.slice(0, 18))}</text>`;
  });
  svg.innerHTML = s;
}

function renderAreas(){
  const list = $('areaList');
  list.innerHTML = '';
  areas.forEach((area, idx)=>{
    const row = document.createElement('div');
    row.className = 'area-row';
    row.innerHTML = `<select class="aname" aria-label="Focus area"></select>
      <input type="range" class="aw" min="0" max="5" step="1" value="${area.w}">
      <span class="aval">${area.w}</span>
      <button class="secondary adel" type="button" title="Remove focus area">×</button>`;
    const select = row.querySelector('.aname');
    topicCatalog.forEach(topic=>{
      if (topic.id !== area.id && areas.some(item=>item.id === topic.id)) return;
      const option = document.createElement('option');
      option.value = topic.id;
      option.textContent = topic.name;
      select.appendChild(option);
    });
    select.value = area.id;
    select.onchange = ()=>{ area.id = select.value; renderAreas(); };
    const range = row.querySelector('.aw');
    const setFill = ()=>{ range.style.setProperty('--pct', (area.w/5*100)+'%'); };
    setFill();
    range.oninput = ()=>{ area.w = +range.value; row.querySelector('.aval').textContent = area.w; setFill(); drawRadar(); };
    row.querySelector('.adel').onclick = ()=>{ areas.splice(idx, 1); renderAreas(); };
    list.appendChild(row);
  });
  const add = $('newArea');
  add.innerHTML = '';
  const unused = topicCatalog.filter(topic=>!areas.some(area=>area.id === topic.id));
  unused.forEach(topic=>{
    const option = document.createElement('option');
    option.value = topic.id;
    option.textContent = topic.name;
    add.appendChild(option);
  });
  add.parentElement.style.display = unused.length ? '' : 'none';
  drawRadar();
}

$('addArea').onclick = ()=>{
  const id = $('newArea').value;
  if (!topicById(id)) return;
  areas.push({id, w:3});
  renderAreas();
};

const generationStages = {
  queued:'Queued',
  refreshing_project_evidence:'Refreshing project evidence',
  extracting_context:'Reading assessment context',
  aligning_targets:'Aligning targets with project evidence',
  planning_questions:'Planning questions',
  retrieving_evidence:'Retrieving evidence bundles',
  generating_questions:'Generating and validating questions',
  awaiting_local_model:'Waiting for local model',
  repairing_questions:'Repairing questions',
  finalizing:'Final checks',
  complete:'Complete',
};

function showGenerationProgress(run){
  const progress = run.progress || {};
  $('genStage').textContent = generationStages[progress.stage] || 'Generating questions';
  $('genProgress').textContent = progress.message || '';
  const context = run.context || {};
  $('genAlignment').textContent = context.targets
    ? `${context.matched} of ${context.targets} assessment targets matched to project evidence.`
    : '';
}

async function waitForGeneration(runId){
  while (true) {
    const run = await api(`/api/generation-runs/${runId}`);
    showGenerationProgress(run);
    if (run.status === 'complete' || run.status === 'awaiting_client') return run;
    if (run.status === 'failed') throw new Error(run.error || 'Question generation failed.');
    await new Promise(resolve=>setTimeout(resolve, 900));
  }
}

async function callLocalOllama(batch, task){
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(), 10 * 60 * 1000);
  const started = performance.now();
  try {
    const payload = {
      model:batch.model,
      messages:[
        {role:'system', content:batch.system},
        {role:'user', content:task.prompt},
      ],
      format:'json',
      stream:false,
      keep_alive:'10m',
      options:{temperature:task.temperature, num_predict:batch.max_tokens},
    };
    if (typeof batch.think === 'boolean') payload.think = batch.think;
    const response = await fetch(`${localProvider.url}/api/chat`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      signal:controller.signal,
      body:JSON.stringify(payload),
    });
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(body.error || `Local Ollama returned HTTP ${response.status}.`);
    const content = body.message?.content || body.response || '';
    if (!content) throw new Error('Local Ollama returned an empty response.');
    return {
      task_index:task.task_index,
      attempt:task.attempt,
      content,
      duration_seconds:(performance.now() - started) / 1000,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function runClientLocalGeneration(run){
  while (run.status === 'awaiting_client') {
    const batch = run.local_batch;
    if (!batch?.tasks?.length) throw new Error('No local generation tasks were returned.');
    const outputs = [];
    for (let index=0; index<batch.tasks.length; index++) {
      const task = batch.tasks[index];
      const phase = task.attempt ? 'Repairing' : 'Generating';
      $('genStage').textContent = `${phase} with ${batch.model}`;
      $('genProgress').textContent = `Question ${task.task_index + 1} · ${index + 1} of ${batch.tasks.length} in this batch`;
      try {
        outputs.push(await callLocalOllama(batch, task));
      } catch (error) {
        outputs.push({
          task_index:task.task_index,
          attempt:task.attempt,
          error:error.message || 'Local Ollama request failed.',
        });
      }
    }
    run = await api(`/api/generation-runs/${run.id}/local-completions`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({batch_id:batch.batch_id, outputs}),
    });
    showGenerationProgress(run);
    if (run.status === 'failed') throw new Error(run.error || 'Question generation failed.');
  }
  if (run.status !== 'complete') throw new Error('Local generation did not complete.');
  return run;
}

// --- Step 2 Local/Mock blueprint preview --------------------------------
// Local and Mock confirm a deterministic plan before generation. Hosted
// OpenAI remains the direct raw-project baseline.
let currentPlan = null;

// The creator sets one target average difficulty; the planner works with a
// range, so widen it by one level either side (clamped to 1..5).
function difficultyRange(){
  const avg = Math.min(5, Math.max(1, +$('gDiffAvg').value || 3));
  return {difficulty_min: Math.max(1, avg - 1), difficulty_max: Math.min(5, avg + 1)};
}

function frameworkConfig(){
  return {
    num_questions:+$('gNum').value, choice_count:+$('gChoices').value,
    correct_mode:$('gMode').value, correct_exact:+$('gExact').value,
    correct_min:+$('gMin').value, correct_max:+$('gMax').value,
    ...difficultyRange(),
    focus:$('gFocus').value,
    focus_areas: areas.filter(area=>area.w > 0).map(area=>({
      id:area.id, name:(topicById(area.id)||{}).name || area.id, weight:area.w})),
    ...selectedLlm()
  };
}

function contextForm(cfg){
  const form = new FormData();
  form.append('config_json', JSON.stringify(cfg));
  form.append('assumed_knowledge', $('assumedKnowledge').value);
  form.append('project_scope', $('projectScope').value);
  priorContextFiles.forEach(file=>form.append('prior_files', file));
  scopeContextFiles.forEach(file=>form.append('scope_files', file));
  return form;
}

const BP_COLORS = ['#626262','#2E6F8E','#7a5ea8','#a8683c','#3f7a5a','#8a4a63','#4a5b8a','#7a7a3c'];

function renderPlanPlot(plan){
  const svg = $('bpPlot'), marks = plan.plot || [];
  const H = 260, L = 52, R = 20, T = 18, B = 84;
  const points = [...new Set(marks.map(m=>m.assessment_point_id))];
  const templates = [...new Set(marks.map(m=>m.template_id))];
  const colorOf = id => BP_COLORS[templates.indexOf(id) % BP_COLORS.length];
  // Columns are a fixed step apart (not stretched to fill the width) and the
  // first one is inset, so no bar sits on the y axis.
  const STEP = 108;
  const W = Math.max(560, L + R + STEP * Math.max(points.length, 1));
  const xOf = i => L + STEP * (i + 0.5);
  const yOf = d => H - B - ((d-1)/4) * (H-T-B);
  let g = '';
  for (let d=1; d<=5; d++){
    g += `<line class="grid" x1="${L}" y1="${yOf(d)}" x2="${W-R}" y2="${yOf(d)}"/>`
       + `<text class="tick" x="${L-10}" y="${yOf(d)+5}" text-anchor="end">${d}</text>`;
  }
  g += `<line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${H-B}"/>`
     + `<line class="axis" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>`;
  points.forEach((pid, i)=>{
    const mark = marks.find(item=>item.assessment_point_id === pid);
    const label = mark?.assessment_point
      || (plan.catalog?.assessment_points || {})[pid] || pid;
    const words = label.split(/[\s/]+/).filter(Boolean).slice(0,3);
    g += words.map((w, k)=>
      `<text class="xlab" x="${xOf(i)}" y="${H-B+20+k*14}" text-anchor="middle">${esc(w)}</text>`).join('');
  });
  // One bar per planned question spanning its expected-difficulty range. No end
  // marker: the range is the estimate, there is no single predicted value.
  marks.forEach(m=>{
    const i = points.indexOf(m.assessment_point_id), c = colorOf(m.template_id);
    const lo = yOf(m.y_min), hi = yOf(m.y_max);
    const sameColumn = marks.filter(o=>o.assessment_point_id === m.assessment_point_id);
    const jitter = (sameColumn.indexOf(m) - (sameColumn.length - 1) / 2) * 18;
    const x = xOf(i) + jitter;
    g += `<line class="band" x1="${x}" y1="${lo}" x2="${x}" y2="${hi}" stroke="${c}">`
       + `<title>Q${m.index+1}: ${esc(m.assessment_point)} · ${esc(m.template)}`
       + ` · expected difficulty ${m.y_min}–${m.y_max}</title></line>`;
  });
  svg.innerHTML = g;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('width', W);
  svg.style.width = `${W}px`;
  // Colour encodes the Template (not the Assessment Point — several questions
  // can share a template, and a point can appear more than once).
  $('bpLegend').innerHTML = '<span class="bp-legend-label">Template:</span>' + templates.map(t=>
    `<span><i style="background:${colorOf(t)}"></i>${esc((plan.catalog?.templates||{})[t]||t)}</span>`
  ).join('');
}

function renderPlan(plan){
  currentPlan = plan;
  renderPlanPlot(plan);
  $('genCount').textContent = (plan.planned || []).length || 0;
  $('generate').disabled = !(plan.planned || []).length;
  $('blueprint').classList.remove('hidden');
}

async function buildPlan(){
  $('planErr').textContent = ''; $('planStatus').textContent = 'Planning…';
  $('previewPlan').disabled = true;
  try {
    const plan = await api(`/api/projects/${currentProject}/question-plans`, {
      method:'POST', body:contextForm(frameworkConfig())});
    renderPlan(plan);
    $('planStatus').textContent =
      `Planned ${(plan.planned||[]).length} question(s) — no model calls yet.`;
  } catch(e){ $('planErr').textContent = e.message; $('planStatus').textContent = ''; }
  $('previewPlan').disabled = false;
}

// One-line context fields that grow with their content, then scroll.
function autoGrow(el){
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 11 * 16) + 'px';
}
document.querySelectorAll('textarea.autogrow').forEach(el=>{
  el.addEventListener('input', ()=>autoGrow(el));
});

// The hosted API provider is the unconstrained benchmark baseline: it generates
// straight from the raw project files and does not consume a blueprint. So the
// planning step is hidden for it — showing a plan it will not follow would
// misrepresent what gets generated.
function usesBlueprint(){
  return selectedLlm().provider !== 'openai';
}

function syncPlanControls(){
  const planned = usesBlueprint();
  $('previewPlan').classList.toggle('hidden', !planned);
  if (!planned){
    currentPlan = null;
    $('blueprint').classList.add('hidden');
    $('planStatus').textContent = '';
    $('planErr').textContent = '';
  }
  $('directGenerate').classList.toggle('hidden', planned);
}

$('gProvider').addEventListener('change', ()=>{
  syncPlanControls();
  syncLocalSetup();
});
$('previewPlan').onclick = buildPlan;
$('rebuildPlan').onclick = buildPlan;

async function runGeneration(){
  $('genErr').textContent=''; $('genStatus').textContent='Generating…';
  $('generate').disabled = true; $('directGenerate').disabled = true;
  $('genStage').textContent = 'Preparing generation';
  $('genProgress').textContent = usesBlueprint()
    ? 'Confirming the question plan.' : 'Submitting the question framework.';
  $('genAlignment').textContent = '';
  $('genOverlay').classList.remove('hidden');
  try {
    let cfg = frameworkConfig();
    if (cfg.provider === 'local' && !localModelReady && !await checkLocalModel()) {
      throw new Error(`Install or download ${localProvider.model} before generating.`);
    }
    if (usesBlueprint()){
      if (!currentPlan) throw new Error('Preview a question plan first.');
      await api(`/api/question-plans/${currentPlan.id}/confirm`, {method:'POST'});
      cfg = {...cfg, question_plan_id: currentPlan.id};
    }
    const form = contextForm(cfg);
    const started = await api(`/api/projects/${currentProject}/generation-runs`, {
      method:'POST', body:form
    });
    let run = await waitForGeneration(started.id);
    if (run.status === 'awaiting_client') run = await runClientLocalGeneration(run);
    const res = run.result;
    $('genStatus').textContent = `Created ${res.created.length} question(s) via ${res.provider || (res.mock_mode ? 'mock' : 'LLM')}`
      + (res.metrics?.llm_calls ? ` · ${res.metrics.llm_calls} model call(s), ${res.metrics.llm_seconds}s` : '')
      + (res.replaced_drafts ? ` (replaced ${res.replaced_drafts} previous draft(s))` : '') + '.';
    if ((res.warnings || []).length) $('genErr').textContent = res.warnings.join('\n');
    await loadQuestions();
    goToStep(3, {unlock:true});
  } catch(e){ $('genErr').textContent = e.message; $('genStatus').textContent=''; }
  $('genOverlay').classList.add('hidden');
  $('generate').disabled = false;
  $('directGenerate').disabled = false;
}

$('generate').onclick = runGeneration;
$('directGenerate').onclick = runGeneration;

async function loadQuestions(){
  const qs = await api(`/api/projects/${currentProject}/questions`);
  const wrap = $('questions');
  wrap.innerHTML = qs.length ? '' : 'No questions yet.';
  selectedForPublish.clear();
  qs.forEach((q, i)=>wrap.appendChild(renderQuestion(q, i + 1)));
  const aa = $('approveAll');
  if (aa) aa.checked = qs.length > 0 && qs.every(q=>q.status === 'approved');
  return qs;
}

$('continuePublish').onclick = ()=>{
  $('reviewErr').textContent = '';
  if (selectedForPublish.size === 0) {
    $('reviewErr').textContent = 'Approve at least one question before continuing.';
    return;
  }
  goToStep(4, {unlock:true});
};

const selectedForPublish = new Set();

function renderQuestion(q, pos){
  const div = document.createElement('div');
  div.className = 'q';
  const approved = q.status === 'approved';
  if (approved) selectedForPublish.add(q.id);   // approval = selected for the assessment
  const ev = (q.evidence||[]).map(e=>`${e.title}${e.file?` — ${e.file}${e.lines?' : '+e.lines:''}`:''}`).join('<br>') || 'No evidence linked';
  // soft quality flags: advisory heuristics that no longer block generation —
  // the reviewer decides whether they matter for this question
  const flags = (q.flags && q.flags.length)
    ? `<div class="qflags">⚠ Review hints: ${q.flags.map(esc).join(' · ')}</div>`
    : '';
  div.innerHTML = `
    <span class="status ${q.status}">${q.status}</span>
    <div class="small" style="margin:0 0 .4rem"><strong>Q${pos}</strong> · ref #${q.id}${
      q.confidence == null ? '' : ` · <span
      title="The model's confidence that the answer key and explanation are correct based on the available project evidence."
      >confidence: ${q.confidence}</span>`}</div>
    ${flags}
    <textarea class="stem">${esc(q.stem)}</textarea>
    <div class="opts"></div>
    <div class="row" style="margin-top:.4rem">
      <div><label>Difficulty</label><input type="number" class="diff" value="${q.difficulty}" min="1" max="5"></div>
      <div style="flex:3"><label>Explanation (shown after submission)</label><textarea class="expl">${esc(q.explanation)}</textarea></div>
    </div>
    <div class="evidence"><strong>Evidence:</strong><br>${ev}</div>
    <p style="margin:.6rem 0 0">
      <button class="save secondary">Save</button>
      <button class="approve${approved?' is-approved':''}" type="button">${approved?'Approved':'Approve'}</button>
      <button class="reject secondary">Reject</button>
      <button class="qdel secondary" type="button" title="Delete this question permanently">Delete</button>
      <span class="err msg"></span>
    </p>`;
  const opts = div.querySelector('.opts');
  const gripSvg = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <circle cx="6" cy="3.5" r="1.4"/><circle cx="10" cy="3.5" r="1.4"/>
      <circle cx="6" cy="8" r="1.4"/><circle cx="10" cy="8" r="1.4"/>
      <circle cx="6" cy="12.5" r="1.4"/><circle cx="10" cy="12.5" r="1.4"/></svg>`;
  q.options.forEach(o=>{
    const row = document.createElement('div');
    row.className='opt';
    row.innerHTML = `<span class="drag-handle" title="Drag to reorder" role="button" aria-label="Drag to reorder">${gripSvg}</span>
      <input type="checkbox" class="corr" ${q.answer.includes(o.key)?'checked':''} title="correct">
      <strong class="okey">${o.key}.</strong> <input type="text" value="${esc(o.text)}" data-key="${o.key}">`;
    opts.appendChild(row);
  });
  // keep labels + keys positional (A, B, C…) after any reorder
  const relabel = ()=>{
    opts.querySelectorAll('.opt').forEach((row, i)=>{
      const key = String.fromCharCode(65 + i);
      row.querySelector('.okey').textContent = key + '.';
      row.querySelector('input[type=text]').dataset.key = key;
    });
  };
  // drag-to-reorder via the grip handle
  const rowAfter = (y)=>{
    const rows = [...opts.querySelectorAll('.opt:not(.dragging)')];
    return rows.reduce((closest, r)=>{
      const box = r.getBoundingClientRect();
      const offset = y - box.top - box.height/2;
      return (offset < 0 && offset > closest.offset) ? {offset, el:r} : closest;
    }, {offset:-Infinity, el:null}).el;
  };
  opts.querySelectorAll('.opt').forEach(row=>{
    const handle = row.querySelector('.drag-handle');
    handle.addEventListener('mousedown', ()=>row.setAttribute('draggable','true'));
    handle.addEventListener('touchstart', ()=>row.setAttribute('draggable','true'), {passive:true});
    row.addEventListener('dragstart', e=>{ row.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; });
    row.addEventListener('dragend', ()=>{ row.classList.remove('dragging'); row.removeAttribute('draggable'); relabel(); });
  });
  opts.addEventListener('dragover', e=>{
    e.preventDefault();
    const dragging = opts.querySelector('.dragging');
    if (!dragging) return;
    const after = rowAfter(e.clientY);
    if (after == null) opts.appendChild(dragging);
    else opts.insertBefore(dragging, after);
  });
  const collect = ()=>({
    stem: div.querySelector('.stem').value,
    options: [...opts.querySelectorAll('input[type=text]')].map(i=>({key:i.dataset.key,text:i.value})),
    answer: [...opts.querySelectorAll('.opt')].filter(r=>r.querySelector('.corr').checked).map(r=>r.querySelector('input[type=text]').dataset.key),
    difficulty: +div.querySelector('.diff').value,
    explanation: div.querySelector('.expl').value
  });
  const send = async (extra)=>{
    div.querySelector('.msg').textContent='';
    try {
      await api('/api/questions/'+q.id, {method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({...collect(), ...extra})});
      await loadQuestions();
    } catch(e){ div.querySelector('.msg').textContent = e.message; }
  };
  div.querySelector('.save').onclick = ()=>send({status:'draft'});
  div.querySelector('.approve').onclick = ()=>{
    if (approved) {                        // toggle off → back to draft, drop from assessment
      selectedForPublish.delete(q.id);
      send({status:'draft'});
    } else {                               // approve → select for the assessment
      selectedForPublish.add(q.id);
      send({status:'approved'});
    }
  };
  div.querySelector('.reject').onclick = ()=>{
    selectedForPublish.delete(q.id);
    send({status:'rejected'});
  };
  div.querySelector('.qdel').onclick = async ()=>{
    if (!confirm(`Delete question #${q.id} permanently?`)) return;
    div.querySelector('.msg').textContent = '';
    try {
      await api('/api/questions/'+q.id, {method:'DELETE'});
      selectedForPublish.delete(q.id);
      await loadQuestions();
    } catch(e){ div.querySelector('.msg').textContent = e.message; }
  };
  return div;
}

$('publish').onclick = async ()=>{
  $('pubErr').textContent=''; $('pubOk').textContent='';
  const ids = [...selectedForPublish];
  try {
    const res = await api(`/api/projects/${currentProject}/assessments`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({title:$('aTitle').value, question_ids:ids,
                            show_correct_count:$('aShowCount').checked,
                            adaptive:$('aAdaptive').checked,
                            framework: {
                              num_questions:+$('gNum').value, choice_count:+$('gChoices').value,
                              correct_mode:$('gMode').value, correct_exact:+$('gExact').value,
                              correct_min:+$('gMin').value, correct_max:+$('gMax').value,
                              difficulty:+$('gDiffAvg').value,
                              ...difficultyRange(),
                              focus:$('gFocus').value,
                              ...selectedLlm(),
                              assumed_knowledge:$('assumedKnowledge').value,
                              project_scope:$('projectScope').value,
                              context_files:[
                                ...priorContextFiles.map(file=>file.name),
                                ...scopeContextFiles.map(file=>file.name),
                              ],
                              focus_areas: areas.filter(area=>area.w > 0).map(area=>({
                                id:area.id, name:(topicById(area.id)||{}).name || area.id, weight:area.w})),
                            }})});
    $('pubOk').innerHTML = `Published. Take link: <a href="${res.take_url}" target="_blank">${location.origin}${res.take_url}</a>`;
    await loadAssessments();
    goToStep(4, {unlock:true});
  } catch(e){ $('pubErr').textContent = e.message; }
};

/* One-click approve/unapprove everything in the current review list */
$('approveAll').onchange = async ()=>{
  const target = $('approveAll').checked ? 'approved' : 'draft';
  const qs = await api(`/api/projects/${currentProject}/questions`);
  const errors = [];
  for (let i = 0; i < qs.length; i++){
    const q = qs[i];
    if (q.status === target) continue;
    if (target === 'draft' && q.status !== 'approved') continue;
    try { await api('/api/questions/'+q.id, {method:'PUT', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({status: target})}); }
    catch(e){ errors.push(`Q${i + 1}: ${e.message.replace('Cannot approve: ', '')}`); }
  }
  $('reviewErr').textContent = errors.length
    ? `${errors.length} question(s) could not be approved — fix or delete them: ` + errors.join(' | ')
    : '';
  await loadQuestions();   // also re-syncs the checkbox to the real state
};

function frameworkSummary(fw){
  if (!fw || !Object.keys(fw).length) return 'No framework snapshot recorded for this assessment.';
  const cc = fw.correct_mode === 'exact'
    ? `exact ${fw.correct_exact} correct`
    : `dynamic ${fw.correct_min}–${fw.correct_max} correct`;
  const areas = (fw.focus_areas || []).map(area=>`${area.name || area.id} ${area.weight}`).join(', ') || '—';
  const diff = fw.difficulty != null
    ? `target avg difficulty ${fw.difficulty}`
    : `difficulty ${fw.difficulty_min}–${fw.difficulty_max}`;
  return `${fw.num_questions} questions · ${fw.choice_count} options · ${cc} · ${diff}`
    + ` · provider: ${fw.model || fw.provider || 'default'}`
    + `\nFocus areas: ${areas}`
    + (fw.assumed_knowledge ? `\nAssumed prior knowledge: ${fw.assumed_knowledge}` : '')
    + (fw.project_scope ? `\nProject scope: ${fw.project_scope}` : '')
    + ((fw.context_files || []).length ? `\nContext files: ${fw.context_files.join(', ')}` : '')
    + (fw.focus ? `\nInstructions: ${fw.focus}` : '');
}

async function loadAssessments(){
  const as = await api(`/api/projects/${currentProject}/assessments`);
  const wrap = $('assessments');
  wrap.innerHTML = as.length ? '' : 'None yet.';
  as.forEach(a=>{
    const d = document.createElement('div');
    d.className = 'assessment-history';
    d.innerHTML = `
      <div class="assessment-summary">
        <a href="#" class="toggleDetail"><strong>${esc(a.title)}</strong> — ${esc(a.created_at)}</a>
        <span class="small"> · ${a.questions} questions · ${a.attempts} attempt(s) ·
          <a href="/a/${a.token}" target="_blank">take</a> ·
          <a href="#" class="viewAttempts">results</a></span>
      </div>
      <button class="assessment-delete" type="button" aria-label="Delete ${esc(a.title)}" title="Delete assessment">×</button>
      <div class="small results"></div>
      <div class="detail hidden" style="margin-top:.5rem"></div>`;
    d.querySelector('.assessment-delete').onclick = async ()=>{
      const attempts = a.attempts
        ? ` and its ${a.attempts} stored attempt(s)`
        : '';
      if (!confirm(`Delete "${a.title}"${attempts}?`)) return;
      try {
        await api(`/api/assessments/${a.id}`, {method:'DELETE'});
        await loadAssessments();
      } catch (error) {
        $('pubErr').textContent = error.message;
      }
    };
    d.querySelector('.toggleDetail').onclick = async (ev)=>{
      ev.preventDefault();
      const det = d.querySelector('.detail');
      if (!det.classList.contains('hidden')) { det.classList.add('hidden'); return; }
      if (!det.dataset.loaded){
        const full = await api(`/api/assessments/${a.id}`);
        let html = `<div style="white-space:pre-wrap;border-left:3px solid var(--card-border);padding-left:.6rem;margin-bottom:.5rem">${esc(frameworkSummary(full.framework))}</div>`;
        full.questions.forEach((q, i)=>{
          html += `<div style="margin:.45rem 0"><strong>Q${i+1}.</strong> ${esc(q.stem)}<br>` +
            q.options.map(o=>`<span style="margin-left:1em">${q.answer.includes(o.key)?'☑':'☐'} ${o.key}. ${esc(o.text)}</span>`).join('<br>') +
            `</div>`;
        });
        det.innerHTML = html;
        det.dataset.loaded = '1';
      }
      det.classList.remove('hidden');
    };
    d.querySelector('.viewAttempts').onclick = async (ev)=>{
      ev.preventDefault();
      const ats = await api(`/api/assessments/${a.id}/attempts`);
      d.querySelector('.results').innerHTML = ats.length
        ? ats.map(t=>`${esc(t.taker_name)||'(anonymous)'} — ${t.score.correct}/${t.score.total} (${t.score.percent}%) at ${t.submitted_at}`).join('<br>')
        : 'No attempts yet.';
    };
    wrap.appendChild(d);
  });
  return as;
}

function esc(s){ return (s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'); }

loadMeta().catch(e=>{
  $('consentText').textContent = 'Could not reach the RepoProof server (' + e.message + '). '
    + 'Open this page via the app URL (e.g. http://127.0.0.1:8000), not as a local file, and make sure "python run.py" is running.';
});
loadProjects().catch(e=>{
  $('projectList').innerHTML = '<li class="small">Could not load projects: ' + e.message + '</li>';
});
