const bridge = window.AstrBotPluginPage;
const statusBadge = document.getElementById('status-badge');
const container = document.getElementById('groups-container');

let currentGroups = {};
let currentMode = 'rule';

function showMessage(msg, isError = true) {
  const el = document.getElementById('notification');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  el.style.background = isError ? '#d32f2f' : '#388e3c';
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

function updateModeUI(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn[data-mode]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
}

function getFilteredGroups() {
  if (currentMode === 'rule') {
    return Object.fromEntries(
      Object.entries(currentGroups).filter(([name]) => name.toUpperCase() !== 'GLOBAL')
    );
  } else if (currentMode === 'global') {
    return Object.fromEntries(
      Object.entries(currentGroups).filter(([name]) => name.toUpperCase() === 'GLOBAL')
    );
  } else if (currentMode === 'direct') {
    return {};
  } else {
    return currentGroups;
  }
}

async function loadStatus() {
  try {
    const status = await bridge.apiGet('status');
    if (!status.running) {
      statusBadge.textContent = '⛔ 代理未运行';
      container.innerHTML = '<p>mihomo 尚未启动，请检查插件配置或使用 /clash start 命令启动。</p>';
      return;
    }
    statusBadge.textContent = '✅ 代理运行中';
    currentGroups = status.groups || {};
    if (status.mode) {
      updateModeUI(status.mode);
    }
    renderGroups();
  } catch (err) {
    statusBadge.textContent = '❌ 加载失败';
    showMessage(`状态加载失败：${err.message}`);
    console.error(err);
  }
}

async function setMode(mode) {
  try {
    await bridge.apiPost('mode', { mode });
    showMessage(`已切换到 ${mode} 模式`, false);
    currentMode = mode;
    updateModeUI(mode);
    renderGroups();
  } catch (err) {
    showMessage(`切换模式失败：${err.message}`);
  }
}

function renderGroups() {
  const filteredGroups = getFilteredGroups();

  if (Object.keys(filteredGroups).length === 0) {
    let msg = '';
    if (currentMode === 'direct') {
      msg = '🔄 直连模式下所有流量将直接访问，不经过代理。';
    } else if (currentMode === 'global') {
      msg = '🌐 全局模式下未找到 GLOBAL 组，请检查订阅配置。';
    } else {
      msg = '没有可切换的代理组。';
    }
    container.innerHTML = `<p>${msg}</p>`;
    return;
  }

  let html = '';
  for (const [groupName, groupData] of Object.entries(filteredGroups)) {
    html += `
      <div class="group-card" data-group="${groupName}">
        <div class="group-header">
          <span class="group-name">${groupName}</span>
          <span class="current-node">当前：${groupData.now || '未选择'}</span>
        </div>
        <div class="node-list">
          ${groupData.all.map(node => `
            <span class="node-item ${node === groupData.now ? 'active' : ''}" data-group="${groupName}" data-node="${node}">
              ${node}
              <span class="delay" id="delay-${groupName}-${node}"></span>
              <button class="btn-test" data-group="${groupName}" data-node="${node}" title="测试延迟"></button>
            </span>
          `).join('')}
        </div>
      </div>
    `;
  }
  container.innerHTML = html;

  document.querySelectorAll('.node-item').forEach(el => {
    el.addEventListener('click', async (e) => {
      if (e.target.tagName === 'BUTTON') return;
      const group = el.dataset.group;
      const node = el.dataset.node;
      await switchNode(group, node);
    });
  });

  document.querySelectorAll('.btn-test').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const group = btn.dataset.group;
      const node = btn.dataset.node;
      btn.disabled = true;
      btn.textContent = '…';
      await testDelay(group, node, false);
      btn.disabled = false;
      btn.textContent = '';
    });
  });
}

async function switchNode(group, node) {
  try {
    await bridge.apiPost('switch', { group, node });
    showMessage('切换成功', false);
    await loadStatus();
  } catch (err) {
    showMessage(`切换失败：${err.message}`);
  }
}

async function testDelay(group, node, silent = false) {
  const delaySpan = document.getElementById(`delay-${group}-${node}`);
  if (!delaySpan) return;
  delaySpan.textContent = '测速中...';
  try {
    const result = await bridge.apiGet('delay', {
      group,
      node,
      timeout: 5000,
      url: 'http://www.gstatic.com/generate_204'
    });
    const delay = result[node];
    if (delay !== undefined && delay !== null) {
      delaySpan.textContent = `${delay}ms`;
      delaySpan.style.color = delay < 100 ? '#2e7d32' : delay < 300 ? '#ed6c02' : '#d32f2f';
    } else {
      delaySpan.textContent = '超时';
    }
  } catch (err) {
    delaySpan.textContent = '错误';
    if (!silent) {
      showMessage(`测速失败：${err.message}`);
    }
    console.error(err);
  }
}

async function batchTest() {
  const btn = document.getElementById('batch-test-btn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '测速中…';

  const filtered = getFilteredGroups();
  const tasks = [];
  for (const [groupName, groupData] of Object.entries(filtered)) {
    for (const node of groupData.all) {
      tasks.push(testDelay(groupName, node, true));
    }
  }
  await Promise.allSettled(tasks);

  btn.disabled = false;
  btn.textContent = '一键测速';
}

// 初始化
await bridge.ready();

document.querySelectorAll('.mode-btn[data-mode]').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.dataset.mode;
    setMode(mode);
  });
});

document.getElementById('batch-test-btn')?.addEventListener('click', batchTest);

loadStatus();
