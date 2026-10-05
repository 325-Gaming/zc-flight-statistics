let view = null;
let state = null;
let selectedRecord = null;
let selectedMenu = null;
let themeSequence = 0;
const appElement = document.getElementById('app');
const dialogLayer = document.getElementById('dialog-layer');
const localStyles = new Set(['classic']);
const themeNames = [
  'window-background', 'panel-background', 'text', 'muted-text', 'border',
  'control-background', 'control-hover-background', 'control-pressed-background',
  'control-text', 'control-disabled-background', 'control-disabled-text',
  'input-background', 'input-text', 'placeholder-text', 'focus',
  'selection-background', 'selection-text', 'accent-background', 'accent-text',
  'accent-hover-background', 'accent-pressed-background',
  'table-heading-background', 'table-heading-text', 'table-row-hover-background',
  'danger-background', 'danger-hover-background', 'danger-pressed-background',
  'danger-text', 'success-text', 'warning-text',
  'scrollbar-track', 'scrollbar-thumb',
];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function showDialog(title, message, confirm = false, checkboxLabel = '') {
  return new Promise(resolve => {
    const previousFocus = document.activeElement;
    dialogLayer.hidden = false;
    dialogLayer.innerHTML = `<div class="dialog-box" role="dialog" aria-modal="true">
      <h2>${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p>
      ${checkboxLabel ? `<label class="check-row"><input id="dialog-checkbox" type="checkbox">${escapeHtml(checkboxLabel)}</label>` : ''}
      <div class="actions">${confirm ? '<button id="dialog-cancel">取消</button>' : ''}
      <button id="dialog-ok" class="primary">确定</button></div></div>`;
    const finish = answer => {
      const checked = checkboxLabel ? document.getElementById('dialog-checkbox').checked : false;
      dialogLayer.hidden = true;
      dialogLayer.innerHTML = '';
      const target = previousFocus?.isConnected && previousFocus !== document.body
        ? previousFocus : appElement;
      target.focus({preventScroll: true});
      resolve(checkboxLabel ? {confirmed: answer, checked} : answer);
    };
    document.getElementById('dialog-ok').onclick = () => finish(true);
    if (confirm) document.getElementById('dialog-cancel').onclick = () => finish(false);
    document.getElementById('dialog-ok').focus();
  });
}

async function api(name, payload = {}) {
  const response = await window.pywebview.api.action(name, payload);
  if (!response.ok) {
    await showDialog('操作失败', response.error || '未知错误');
    return {failed: true};
  }
  return response.data;
}

function closeMenus() {
  appElement.querySelectorAll('.menu-popover').forEach(popover => popover.hidden = true);
  selectedMenu = null;
}

async function applyTheme(name) {
  const sequence = ++themeSequence;
  const safeName = /^[a-z0-9][a-z0-9_-]{0,63}$/.test(name) ? name : 'classic';
  const url = localStyles.has(safeName)
    ? `themes/${safeName}.css`
    : `https://yubo.run/zc/css/zc-flight-live/${safeName}.css?v=${Date.now()}-${sequence}`;
  const previous = document.getElementById('theme-css');
  const next = document.createElement('link');
  next.rel = 'stylesheet';
  next.href = url;
  next.onload = async () => {
    if (sequence !== themeSequence) { next.remove(); return; }
    // Validate the new stylesheet alone so an older theme cannot hide missing tokens.
    const previousName = document.body.dataset.pageStyle;
    previous.disabled = true;
    document.body.dataset.pageStyle = safeName;
    const computed = getComputedStyle(document.body);
    const missing = themeNames.filter(token =>
      !/^#[0-9a-f]{6}$/i.test(computed.getPropertyValue(`--client-${token}`).trim())
    );
    if (missing.length && safeName !== 'classic') {
      console.warn(`Theme ${safeName} has invalid client colors:`, missing);
      next.remove();
      previous.disabled = false;
      document.body.dataset.pageStyle = previousName;
      await applyTheme('classic');
      await showDialog('主题不可用', `当前加载的“${safeName}”CSS 缺少 ${missing.length} 项客户端控件颜色，已使用 classic。`);
      return;
    }
    next.id = 'theme-css';
    previous.replaceWith(next);
  };
  next.onerror = async () => {
    next.remove();
    if (sequence !== themeSequence) return;
    if (safeName !== 'classic') {
      await applyTheme('classic');
      await showDialog('主题加载失败', '已使用 classic 主题。');
    }
  };
  document.head.appendChild(next);
}

function renderMain() {
  const s = state;
  const captain = s.captain;
  const captainTitle = captain ? `【${captain.title}】` : '资料暂不可用';
  const captainNickname = captain?.nickname || '';
  const captainText = `机长 ${captainTitle}${captainNickname ? ` ${captainNickname}` : ''}`;
  const menus = [
    ['文件', [['设置', 'settings'], ['导入乘客名单…', 'import'], [null], ['退出登录', 'logout'], ['退出', 'exit']]],
    ['操作', [['撤销上一条', 'undo'], ['抽卡记录…', 'history']]],
    ['统计', [['直播页面设置…', 'page'], ['查看统计', 'statistics']]],
  ];
  const menuHtml = menus.map(([label, items], index) => `<div class="menu-wrap">
    <button class="menu-trigger" data-menu="${index}" aria-expanded="false">${label}</button>
    <div class="menu-popover" id="menu-${index}" hidden>${items.map(([item, action]) =>
      item === null ? '<div class="menu-separator" role="separator"></div>' :
      `<button data-menu-action="${action}">${item}</button>`).join('')}</div></div>`).join('');
  const passengers = s.passengers.map((name, index) =>
    `<button data-passenger="${index}" class="${index === s.user_id ? 'selected' : ''}">${escapeHtml(name)}</button>`
  ).join('');
  const single = [3, 4, 5, 6].map(rarity =>
    `<button class="gacha-button" data-rarity="${rarity}"><strong>${'零一二三四五六'[rarity]}星</strong>
    <small>${escapeHtml(s.hotkeys[`hotkey_${rarity}x`] ? `快捷键 ${s.hotkeys[`hotkey_${rarity}x`]}` : '')}</small></button>`
  ).join('');
  appElement.innerHTML = `<div class="menu-bar">${menuHtml}
    <div class="captain-profile" title="${escapeHtml(captainText)}">
      <span class="captain-label">机长</span>
      <span class="captain-details"><span class="captain-title">${escapeHtml(captainTitle)}</span>
        ${captainNickname ? `<span class="captain-nickname">${escapeHtml(captainNickname)}</span>` : ''}</span>
    </div></div>
    <div class="main-layout"><aside class="sidebar panel"><h2>乘客列表</h2>
      <div class="passenger-list">${passengers}</div></aside>
    <main class="main-panel"><div class="result">${escapeHtml(s.result)}</div>
      <div class="navigation"><button id="previous" ${s.user_id === 0 ? 'disabled' : ''}>上一位乘客</button>
      <button id="insert">新乘客</button><button id="next">下一位乘客</button></div>
      <label for="nickname">当前乘客：</label>
      <div class="nickname-row"><input id="nickname" value="${escapeHtml(s.nickname)}"><button id="rename">重命名</button></div>
      <fieldset class="panel"><legend>单抽</legend><div class="action-row">${single}</div></fieldset>
      <fieldset class="panel"><legend>十连</legend><div class="action-row">
        <button class="gacha-button" id="purple"><strong>紫光镀彩</strong></button>
        <button class="gacha-button wide" id="ten"><strong>十连</strong>
        <small>${escapeHtml(s.hotkeys.hotkey_gacha10 ? `快捷键 ${s.hotkeys.hotkey_gacha10}` : '')}</small></button>
      </div></fieldset><p class="status" role="status">${escapeHtml(s.status)}</p></main></div>`;
  appElement.querySelectorAll('[data-menu]').forEach(button => button.onclick = event => {
    event.stopPropagation();
    const index = button.dataset.menu;
    appElement.querySelectorAll('.menu-popover').forEach(popover => {
      popover.hidden = popover.id !== `menu-${index}` || selectedMenu === index;
    });
    selectedMenu = selectedMenu === index ? null : index;
  });
  appElement.querySelectorAll('[data-menu-action]').forEach(button => button.onclick = async () => {
    const action = button.dataset.menuAction;
    closeMenus();
    if (action === 'exit') {
      if (await showDialog('退出', '确定退出客户端吗？', true)) await api('close');
    } else if (action === 'logout') {
      const choice = await showDialog('退出登录', '确定退出羽bot个人中心吗？未勾选时将返回登录页面。', true, '同时退出客户端');
      if (choice.confirmed) {
        const result = await api('logout');
        if (result && !result.failed) {
          if (!result.revoked) {
            await showDialog('退出登录未完全成功',
              '本地会话已清除，但未能确认服务端会话已撤销。请检查网络连接，并联系管理员核查。');
          }
          await api('close', {relogin: !choice.checked});
        }
      }
    } else if (action === 'undo') {
      await undoLast();
    } else await api('open', {view: action});
  });
  appElement.querySelectorAll('[data-passenger]').forEach(button => button.onclick = () => mainAction('select', {index: Number(button.dataset.passenger)}));
  appElement.querySelectorAll('[data-rarity]').forEach(button => button.onclick = () => mainAction('single', {rarity: Number(button.dataset.rarity)}));
  for (const name of ['previous', 'insert', 'next', 'purple', 'ten']) {
    document.getElementById(name).onclick = () => mainAction(name);
  }
  const nicknameInput = document.getElementById('nickname');
  document.getElementById('rename').onclick = () => mainAction('rename', {nickname: nicknameInput.value});
  nicknameInput.onchange = async () => {
    const data = await api('sync', {nickname: nicknameInput.value});
    if (!data?.failed) state = data;
  };
  nicknameInput.onkeydown = event => {
    if (event.key === 'Enter') nicknameInput.blur();
  };
}

async function undoLast() {
  const record = await api('undo_preview');
  if (!record || record.failed) return;
  if (await showDialog('撤销上一条抽卡记录',
    `确定撤销 ${record.nickname} 最近上传的 ${record.count} 抽记录吗？`, true)) {
    const data = await api('undo', {id: record.id});
    if (!data?.failed) { state = data; renderMain(); }
  }
}

async function mainAction(name, payload = {}) {
  const data = await api(name, payload);
  if (!data?.failed && data) { state = data; renderMain(); }
}

function renderImport() {
  appElement.innerHTML = `<div class="content import-view">
    <label for="import-text">乘客名单（每行一位乘客）</label>
    <textarea id="import-text" spellcheck="false"></textarea>
    <div class="actions"><button id="import-open-file">打开文件</button>
      <button id="import-cancel">取消</button><button id="import-confirm" class="primary">确定</button></div></div>`;
  const input = document.getElementById('import-text');
  document.getElementById('import-open-file').onclick = async () => {
    const contents = await api('open_file');
    if (typeof contents === 'string') input.value = contents;
  };
  document.getElementById('import-cancel').onclick = () => api('close');
  document.getElementById('import-confirm').onclick = async () => {
    const result = await api('confirm', {text: input.value});
    if (!result?.failed) await api('close');
  };
  input.focus();
}

function renderHistory() {
  const options = `<option value="current">当前乘客：${escapeHtml(state.current_nickname)}</option>
    <option value="all">全部乘客（当前活动）</option>` + state.passengers.map(name =>
    `<option value="passenger:${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  const rows = state.rows.map(row => `<tr data-id="${row.id}" class="${row.id === selectedRecord ? 'selected' : ''}">
    <td>${row.id}</td><td>${escapeHtml(row.nickname)}</td><td>${row.sequence}</td>
    <td>${escapeHtml(row.position)}</td><td>${escapeHtml(row.result)}</td>
    <td>${escapeHtml(row.created_at)}</td><td>${row.revoked ? '已撤销' : '有效'}</td></tr>`).join('');
  const selected = state.rows.find(row => row.id === selectedRecord);
  const siblings = selected ? state.rows.filter(row => row.nickname === selected.nickname)
    .sort((left, right) => left.sequence - right.sequence) : [];
  const selectedIndex = siblings.findIndex(row => row.id === selectedRecord);
  appElement.innerHTML = `<div class="content history"><div class="toolbar"><label for="history-filter">查看范围：</label>
    <select id="history-filter">${options}</select><button id="history-refresh">刷新</button></div>
    <div class="table-scroll"><table><thead><tr><th>记录 ID</th><th>乘客</th><th>记录序号</th><th>抽数</th>
    <th>抽卡结果</th><th>上传时间</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="history-footer"><span class="status">${escapeHtml(state.history_status || `共 ${state.rows.length} 条记录`)}</span>
      <span>将所选记录：</span><button id="revoke" ${state.pending || !selected || selected.revoked ? 'disabled' : ''}>撤销</button>
      <button id="restore" ${state.pending || !selected || !selected.revoked ? 'disabled' : ''}>恢复</button>
      <button data-move="first" ${state.pending || selectedIndex <= 0 ? 'disabled' : ''}>移至最前</button>
      <button data-move="previous" ${state.pending || selectedIndex <= 0 ? 'disabled' : ''}>与前一条交换位置</button>
      <button data-move="next" ${state.pending || selectedIndex < 0 || selectedIndex >= siblings.length - 1 ? 'disabled' : ''}>与后一条交换位置</button>
      <button data-move="last" ${state.pending || selectedIndex < 0 || selectedIndex >= siblings.length - 1 ? 'disabled' : ''}>移至最后</button>
      <button id="history-close">关闭</button></div></div>`;
  document.getElementById('history-filter').value = state.filter === 'passenger'
    ? `passenger:${state.nickname}` : state.filter;
  document.getElementById('history-filter').onchange = async event => {
    const value = event.target.value;
    const payload = value.startsWith('passenger:')
      ? {mode: 'passenger', nickname: value.slice(10)} : {mode: value};
    const data = await api('filter', payload);
    if (!data?.failed) { state = data; selectedRecord = null; renderHistory(); }
  };
  document.getElementById('history-refresh').onclick = refreshHistory;
  document.getElementById('history-close').onclick = () => api('close');
  appElement.querySelectorAll('tbody tr').forEach(row => row.onclick = () => {
    const scroll = appElement.querySelector('.table-scroll');
    const top = scroll.scrollTop;
    const left = scroll.scrollLeft;
    selectedRecord = Number(row.dataset.id);
    renderHistory();
    appElement.querySelector('.table-scroll').scrollTo(left, top);
  });
  for (const action of ['revoke', 'restore']) {
    document.getElementById(action).onclick = async () => {
      if (action === 'revoke' && !(await showDialog('撤销抽卡记录',
        `确定撤销 ${selected.nickname} 的这条 ${selected.count} 抽记录吗？`, true))) return;
      const data = await api(action, {id: selectedRecord});
      if (!data?.failed) { state = data; renderHistory(); }
    };
  }
  appElement.querySelectorAll('[data-move]').forEach(button => button.onclick = async () => {
    const data = await api('move', {id: selectedRecord, direction: button.dataset.move});
    if (!data?.failed) { state = data; renderHistory(); }
  });
}

async function refreshHistory() {
  const data = await api('refresh');
  if (!data?.failed) { state = data; renderHistory(); }
}

function settingsField(key, label, description, control) {
  return `<label for="setting-${key}">${label}</label>${control}
    ${description ? `<p class="hint">${description}</p>` : ''}`;
}

function renderSettings() {
  const data = state;
  const config = data.config;
  const poolOptions = data.pool_names.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
  const monitorOptions = data.monitors.map(monitor =>
    `<option value="${monitor.index}">${escapeHtml(monitor.description)}（${monitor.size.join('×')}，${monitor.position.join(', ')}）</option>`
  ).join('');
  const textInput = (key, value) => `<input id="setting-${key}" value="${escapeHtml(value)}">`;
  const fields = [
    settingsField('event_name', '活动名称', '基础活动名称，会与卡池名称拼接后提交抽卡记录。', textInput('event_name', config.event_name)),
    settingsField('pool_name', '卡池名称', '', `<select id="setting-pool_name">${poolOptions}</select>`),
    settingsField('user_name_list_file', '乘客名单文件', '相对于程序目录；更换后会替换当前乘客列表。', textInput('user_name_list_file', config.user_name_list_file)),
    '<p class="wide muted" id="event-preview"></p>',
    '<div class="wide form-separator" role="separator"></div>',
    settingsField('target_monitor_id', '截图显示器编号', '执行识别时需要截取的显示器编号。', `<div class="inline"><select id="setting-target_monitor_id">${monitorOptions}</select><button id="monitors-refresh">刷新列表</button><button id="monitors-preview">显示预览</button></div>`),
    ...['hotkey_gacha10', 'hotkey_3x', 'hotkey_4x', 'hotkey_5x', 'hotkey_6x'].map((key, index) =>
      settingsField(key, ['十连快捷键', '三星快捷键', '四星快捷键', '五星快捷键', '六星快捷键'][index],
        '可留空；设置窗口打开期间，全局快捷键无效。',
        `<div class="inline">${textInput(key, config[key] || '')}<button data-clear="${key}">移除</button></div>`)),
  ];
  appElement.innerHTML = `<div class="form-view"><div class="form-view-content"><div class="form-grid">${fields.join('')}</div></div>
    <div class="actions form-view-actions"><button id="settings-cancel">取消</button><button id="settings-save" class="primary">保存</button></div></div>`;
  document.getElementById('setting-pool_name').value = data.selected_pool;
  document.getElementById('setting-target_monitor_id').value = String(config.target_monitor_id);
  const updatePreview = () => {
    const eventName = document.getElementById('setting-event_name').value.trim();
    const poolName = document.getElementById('setting-pool_name').value.trim();
    document.getElementById('event-preview').textContent =
      `完整活动名称预览：${eventName && poolName ? `${eventName} ${poolName}` : '—'}\n${data.pool_message || ''}`;
  };
  document.getElementById('setting-event_name').oninput = updatePreview;
  document.getElementById('setting-pool_name').onchange = updatePreview;
  updatePreview();
  appElement.querySelectorAll('[data-clear]').forEach(button => button.onclick = () => {
    document.getElementById(`setting-${button.dataset.clear}`).value = '';
  });
  document.getElementById('monitors-refresh').onclick = async () => {
    const monitors = await api('monitors');
    if (!monitors?.failed) {
      state.monitors = monitors;
      const selector = document.getElementById('setting-target_monitor_id');
      const selected = selector.value;
      selector.innerHTML = monitors.map(monitor =>
        `<option value="${monitor.index}">${escapeHtml(monitor.description)}（${monitor.size.join('×')}，${monitor.position.join(', ')}）</option>`
      ).join('');
      selector.value = selected;
    }
  };
  document.getElementById('monitors-preview').onclick = () => api('preview', {
    monitor_id: document.getElementById('setting-target_monitor_id').value,
  });
  document.getElementById('settings-cancel').onclick = () => api('close');
  document.getElementById('settings-save').onclick = async () => {
    const values = {};
    for (const key of ['event_name', 'pool_name', 'target_monitor_id', 'user_name_list_file',
      'hotkey_gacha10', 'hotkey_3x', 'hotkey_4x', 'hotkey_5x', 'hotkey_6x']) {
      values[key] = document.getElementById(`setting-${key}`).value.trim();
    }
    if (values.user_name_list_file !== config.user_name_list_file &&
        !(await showDialog('替换乘客名单', '更换名单将替换当前列表，并切换到第一位乘客。是否继续？', true))) return;
    const result = await api('save', values);
    if (!result?.failed) await api('close');
  };
}

function renderPage() {
  const data = state;
  const s = data.settings;
  const check = ([key, label]) => `<label class="check-row ${key.endsWith('left_visible') || key.endsWith('right_visible') ? 'indent' : ''}">
    <input type="checkbox" id="page-${key}" ${s[key] ? 'checked' : ''}>${escapeHtml(label)}</label>`;
  const fields = data.text_items.map(([key, label]) =>
    `<label for="page-${key}">${escapeHtml(label)}</label><input id="page-${key}" value="${escapeHtml(s[key])}">`).join('');
  appElement.innerHTML = `<div class="form-view"><div class="form-view-content"><label class="check-row"><input type="checkbox" id="page-is_active" ${s.is_active ? 'checked' : ''}>
    ${escapeHtml(data.activity[1])}</label><div class="form-grid">
    <label for="page-poll_interval_seconds">数据轮询间隔（秒）</label>
    <input type="number" id="page-poll_interval_seconds" min="1" max="60" value="${s.poll_interval_seconds}">
    <p class="hint">仅在直播页面活跃刷新时生效，不活跃时固定为 60 秒。</p>
    <label for="page-page_style">页面样式</label><select id="page-page_style">${data.styles.map(name =>
      `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('')}</select>
    <p class="wide muted">页面项目，勾选表示显示，不勾选表示隐藏。</p>
    <div class="wide">${data.display_items.map(check).join('')}</div>${fields}</div></div>
    <div class="actions form-view-actions"><button id="page-cancel">取消</button><button id="page-save" class="primary">保存</button></div></div>`;
  document.getElementById('page-page_style').value = data.styles.includes(s.page_style) ? s.page_style : 'classic';
  const active = document.getElementById('page-is_active');
  const interval = document.getElementById('page-poll_interval_seconds');
  active.onchange = () => { interval.disabled = !active.checked; };
  interval.disabled = !active.checked;
  document.getElementById('page-cancel').onclick = () => api('close');
  document.getElementById('page-save').onclick = async () => {
    const seconds = Number(interval.value);
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60) {
      await showDialog('无法保存', '数据轮询间隔必须是 1 到 60 之间的整数。');
      return;
    }
    const values = {poll_interval_seconds: seconds,
      page_style: document.getElementById('page-page_style').value};
    for (const [key] of [data.activity, ...data.display_items]) {
      values[key] = document.getElementById(`page-${key}`).checked;
    }
    for (const [key] of data.text_items) values[key] = document.getElementById(`page-${key}`).value;
    const result = await api('save', values);
    if (!result?.failed) await api('close');
  };
}

function renderStatistics() {
  appElement.innerHTML = `<div class="content"><div class="url-row"><input id="statistics-url" readonly value="${escapeHtml(state.url)}">
    <button id="copy-url">点击复制</button></div><p class="muted">在 OBS 添加浏览器源，URL 填写上方 URL，宽度与高度设为与画布相同（1920×1080 / 2560×1440）。</p></div>`;
  document.getElementById('copy-url').onclick = async () => {
    try {
      await navigator.clipboard.writeText(state.url);
    } catch (_error) {
      const input = document.getElementById('statistics-url');
      input.select();
      document.execCommand('copy');
    }
    document.getElementById('copy-url').textContent = '已复制';
  };
}

function render() {
  appElement.classList.toggle('main-view', view === 'main');
  if (view === 'main') renderMain();
  else if (view === 'import') renderImport();
  else if (view === 'history') renderHistory();
  else if (view === 'settings') renderSettings();
  else if (view === 'page') renderPage();
  else if (view === 'statistics') renderStatistics();
  else if (view === 'preview') appElement.innerHTML = `<div class="content"><img class="preview-image" alt="显示器预览" src="${escapeHtml(state.image)}"></div>`;
}

window.receiveState = update => {
  if (update.theme) applyTheme(update.theme);
  if (update.passengers || update.rows) { state = update; render(); }
  else if (update.history_status && view === 'history') {
    state = {...state, ...update}; render();
  }
};

document.addEventListener('click', event => {
  if (!event.target.closest('.menu-wrap')) closeMenus();
});

document.addEventListener('keydown', async event => {
  if (view !== 'main' || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return;
  if (event.target.matches('input, textarea, [contenteditable]')) return;
  event.preventDefault();
  await undoLast();
});

window.addEventListener('pywebviewready', async () => {
  try {
    const bootstrap = await window.pywebview.api.bootstrap();
    view = bootstrap.view;
    state = bootstrap.data;
    applyTheme(bootstrap.theme);
    render();
  } catch (error) {
    appElement.innerHTML = `<div class="content error">无法加载窗口：${escapeHtml(error.message || error)}</div>`;
  }
});
