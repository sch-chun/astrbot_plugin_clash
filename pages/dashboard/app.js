const bridge = window.AstrBotPluginPage;
const statusBadge = document.getElementById('status-badge');
const container = document.getElementById('groups-container');

let currentGroups = {};

function showMessage(msg, isError = true) {
  const el = document.getElementById('notification');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  el.style.background = isError ? '#d32f2f' : '#388e3c';
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
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
    renderGroups();
  } catch (err) {
    statusBadge.textContent = '❌ 加载失败';
    showMessage(`状态加载失败：${err.message}`);
    console.error(err);
  }
}

function renderGroups() {
  if (Object.keys(currentGroups).length === 0) {
    container.innerHTML = '<p>没有可切换的代理组。</p>';
    return;
  }
  let html = '';
  for (const [groupName, groupData] of Object.entries(currentGroups)) {
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
              <button class="btn-test" data-group="${groupName}" data-node="${node}" title="测试延迟">📶</button>
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
      btn.textContent = '⏳';
      await testDelay(group, node);
      btn.disabled = false;
      btn.textContent = '📶';
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

async function testDelay(group, node) {
  const delaySpan = document.getElementById(`delay-${group}-${node}`);
  if (!delaySpan) return;
  delaySpan.textContent = '测速中...';
  try {
    const result = await bridge.apiGet('delay', { group, node, timeout: 3000 });
    const delay = result[node];
    if (delay !== undefined && delay !== null) {
      delaySpan.textContent = `${delay}ms`;
    } else {
      delaySpan.textContent = '超时';
    }
  } catch (err) {
    delaySpan.textContent = '错误';
    showMessage(`测速失败：${err.message}`);
    console.error(err);
  }
}

// 初始化
await bridge.ready();
loadStatus();
