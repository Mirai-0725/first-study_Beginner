'use strict';

// ===== 設定値 =====
const STORAGE_KEY = 'kakeibo-prototype-v1';
// F-07: 警告に切り替わる使用率(%)。要件の初期値 80%
const WARNING_THRESHOLD = 80;
const NAME_MAX_LENGTH = 50;

// ===== 状態 =====
let state = loadState();
let editingExpenseId = null; // 編集中の支出ID(null なら新規登録モード)
let editingPeriodId = null;  // ダイアログで編集中の期間ID(null なら新規作成)

// ===== 保存・読み込み =====
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    console.warn('データを読み込めませんでした', e);
  }
  return { periods: [], expenses: [], selectedPeriodId: null };
}

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (e) {
    console.warn('データを保存できませんでした', e);
  }
}

// ===== ユーティリティ =====
function newId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// 日付は "YYYY-MM-DD" の文字列で扱う(文字列比較で大小判定できる)
function todayString() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function formatYen(amount) {
  return '¥' + amount.toLocaleString('ja-JP');
}

function formatDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${y}/${m}/${d}`;
}

function formatPeriod(period) {
  return `${formatDate(period.start)} 〜 ${formatDate(period.end)}`;
}

function parseAmount(value) {
  const n = Number(value);
  return value !== '' && Number.isInteger(n) ? n : NaN;
}

function getSelectedPeriod() {
  return state.periods.find((p) => p.id === state.selectedPeriodId) || null;
}

function getExpensesInPeriod(period) {
  // 支出がどの期間に属するかは購入日で判定する
  return state.expenses
    .filter((e) => e.date >= period.start && e.date <= period.end)
    .sort((a, b) => (a.date === b.date ? b.createdAt - a.createdAt : b.date.localeCompare(a.date)));
}

// F-07: 使用率から状態を判定する
function getStatus(rate) {
  if (rate > 100) return 'over';
  if (rate >= WARNING_THRESHOLD) return 'warning';
  return 'normal';
}

const STATUS_LABELS = {
  normal: '予算内',
  warning: '上限に近づいています',
  over: '上限を超えました',
};

// ===== 描画 =====
const $ = (id) => document.getElementById(id);

function render() {
  const period = getSelectedPeriod();
  renderPeriodSelect();

  $('empty-state').hidden = period !== null;
  $('main-content').hidden = period === null;
  $('edit-period-btn').hidden = period === null;

  if (!period) {
    document.body.dataset.status = 'normal';
    return;
  }

  const expenses = getExpensesInPeriod(period);
  renderSummary(period, expenses);
  renderExpenseList(expenses);
  updateExpenseDateRange(period);
}

function renderPeriodSelect() {
  const select = $('period-select');
  select.replaceChildren();
  const periods = [...state.periods].sort((a, b) => b.start.localeCompare(a.start));
  if (periods.length === 0) {
    select.append(new Option('(未設定)', ''));
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const p of periods) {
    select.append(new Option(formatPeriod(p), p.id, false, p.id === state.selectedPeriodId));
  }
}

function renderSummary(period, expenses) {
  const spent = expenses.reduce((sum, e) => sum + e.amount, 0);
  const remaining = period.budget - spent;
  const rate = (spent / period.budget) * 100;
  const status = getStatus(rate);

  document.body.dataset.status = status;
  $('summary-period').textContent = formatPeriod(period);
  $('status-badge').textContent = STATUS_LABELS[status];
  $('budget-value').textContent = formatYen(period.budget);
  $('spent-value').textContent = formatYen(spent);

  // 超過時は「超過額」として表示する
  if (remaining < 0) {
    $('remaining-label').textContent = '超過額';
    $('remaining-value').textContent = formatYen(-remaining);
    $('remaining-value').classList.add('negative');
  } else {
    $('remaining-label').textContent = '残り金額';
    $('remaining-value').textContent = formatYen(remaining);
    $('remaining-value').classList.remove('negative');
  }

  $('rate-value').textContent = `${Math.floor(rate)}%`;
  $('progress-bar').style.width = `${Math.min(rate, 100)}%`;
  $('progress').setAttribute('aria-valuenow', String(Math.floor(rate)));
  $('progress-threshold').style.left = `${WARNING_THRESHOLD}%`;
}

function renderExpenseList(expenses) {
  const tbody = $('expense-list');
  tbody.replaceChildren();
  $('expense-empty').hidden = expenses.length > 0;
  $('expense-table').hidden = expenses.length === 0;
  $('expense-count').textContent = expenses.length > 0 ? `(${expenses.length}件)` : '';

  for (const e of expenses) {
    const tr = document.createElement('tr');
    if (e.id === editingExpenseId) tr.classList.add('editing');

    const dateTd = document.createElement('td');
    dateTd.textContent = formatDate(e.date);
    const nameTd = document.createElement('td');
    nameTd.textContent = e.name;
    const amountTd = document.createElement('td');
    amountTd.className = 'num';
    amountTd.textContent = formatYen(e.amount);

    const actionsTd = document.createElement('td');
    actionsTd.className = 'actions';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'secondary small';
    editBtn.textContent = '編集';
    editBtn.addEventListener('click', () => startEditExpense(e.id));
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'danger small';
    deleteBtn.textContent = '削除';
    deleteBtn.addEventListener('click', () => deleteExpense(e.id));
    actionsTd.append(editBtn, deleteBtn);

    tr.append(dateTd, nameTd, amountTd, actionsTd);
    tbody.append(tr);
  }
}

// 購入日の入力範囲を選択中の期間内に制限する
function updateExpenseDateRange(period) {
  const dateInput = $('expense-date');
  dateInput.min = period.start;
  dateInput.max = period.end;
  if (!dateInput.value || dateInput.value < period.start || dateInput.value > period.end) {
    const today = todayString();
    dateInput.value = today >= period.start && today <= period.end ? today : period.start;
  }
}

// ===== 支出(F-03, F-05) =====
function validateExpense(name, amount, date, period) {
  const errors = [];
  if (name === '') errors.push('品名を入力してください。');
  else if (name.length > NAME_MAX_LENGTH) errors.push(`品名は${NAME_MAX_LENGTH}文字以内で入力してください。`);
  if (Number.isNaN(amount)) errors.push('金額を整数で入力してください。');
  else if (amount < 1) errors.push('金額は1円以上で入力してください。');
  if (!date) errors.push('購入日を入力してください。');
  else if (date < period.start || date > period.end) {
    errors.push(`購入日は選択中の期間(${formatPeriod(period)})内で入力してください。`);
  }
  return errors;
}

function handleExpenseSubmit(event) {
  event.preventDefault();
  const period = getSelectedPeriod();
  const name = $('expense-name').value.trim();
  const amount = parseAmount($('expense-amount').value);
  const date = $('expense-date').value;

  const errors = validateExpense(name, amount, date, period);
  if (errors.length > 0) {
    $('expense-error').textContent = errors.join('\n');
    return;
  }

  if (editingExpenseId) {
    const target = state.expenses.find((e) => e.id === editingExpenseId);
    Object.assign(target, { name, amount, date });
  } else {
    state.expenses.push({ id: newId(), name, amount, date, createdAt: Date.now() });
  }
  saveState();
  resetExpenseForm();
  render();
  $('expense-name').focus();
}

function startEditExpense(id) {
  const e = state.expenses.find((x) => x.id === id);
  editingExpenseId = id;
  $('expense-name').value = e.name;
  $('expense-amount').value = e.amount;
  $('expense-date').value = e.date;
  $('expense-form-title').textContent = '支出を編集';
  $('expense-submit').textContent = '更新';
  $('expense-cancel').hidden = false;
  $('expense-error').textContent = '';
  render();
  $('expense-name').focus();
}

function resetExpenseForm() {
  editingExpenseId = null;
  $('expense-name').value = '';
  $('expense-amount').value = '';
  $('expense-form-title').textContent = '支出を登録';
  $('expense-submit').textContent = '登録';
  $('expense-cancel').hidden = true;
  $('expense-error').textContent = '';
}

function deleteExpense(id) {
  const e = state.expenses.find((x) => x.id === id);
  if (!confirm(`「${e.name}」(${formatYen(e.amount)})を削除しますか?`)) return;
  state.expenses = state.expenses.filter((x) => x.id !== id);
  if (editingExpenseId === id) resetExpenseForm();
  saveState();
  render();
}

// ===== 期間(F-01, F-02) =====
function openPeriodDialog(periodId) {
  editingPeriodId = periodId;
  const period = state.periods.find((p) => p.id === periodId);
  $('period-dialog-title').textContent = period ? '期間を編集' : '新しい期間を設定';
  $('period-start').value = period ? period.start : '';
  $('period-end').value = period ? period.end : '';
  $('period-budget').value = period ? period.budget : '';
  $('period-error').textContent = '';
  $('period-dialog').showModal();
}

function validatePeriod(start, end, budget) {
  const errors = [];
  if (!start) errors.push('開始日を入力してください。');
  if (!end) errors.push('締め日を入力してください。');
  if (start && end && end < start) errors.push('締め日は開始日以降の日付にしてください。');
  if (Number.isNaN(budget)) errors.push('上限金額を整数で入力してください。');
  else if (budget < 1) errors.push('上限金額は1円以上で入力してください。');
  if (errors.length > 0) return errors;

  // 期間同士の日付は重複させない
  const overlap = state.periods.find(
    (p) => p.id !== editingPeriodId && start <= p.end && end >= p.start
  );
  if (overlap) errors.push(`既存の期間(${formatPeriod(overlap)})と日付が重なっています。`);

  // 編集時: 日付を変えたことで期間外になる支出がないか
  const current = state.periods.find((p) => p.id === editingPeriodId);
  if (current) {
    const orphaned = getExpensesInPeriod(current).filter((e) => e.date < start || e.date > end);
    if (orphaned.length > 0) {
      errors.push(`新しい日付の範囲外になる支出が${orphaned.length}件あります。先に支出を修正・削除してください。`);
    }
  }
  return errors;
}

function handlePeriodSubmit(event) {
  event.preventDefault();
  const start = $('period-start').value;
  const end = $('period-end').value;
  const budget = parseAmount($('period-budget').value);

  const errors = validatePeriod(start, end, budget);
  if (errors.length > 0) {
    $('period-error').textContent = errors.join('\n');
    return;
  }

  if (editingPeriodId) {
    const target = state.periods.find((p) => p.id === editingPeriodId);
    Object.assign(target, { start, end, budget });
  } else {
    const id = newId();
    state.periods.push({ id, start, end, budget });
    state.selectedPeriodId = id;
  }
  saveState();
  $('period-dialog').close();
  resetExpenseForm();
  render();
}

// ===== イベント登録 =====
$('expense-form').addEventListener('submit', handleExpenseSubmit);
$('expense-cancel').addEventListener('click', () => { resetExpenseForm(); render(); });
$('period-form').addEventListener('submit', handlePeriodSubmit);
$('period-cancel').addEventListener('click', () => $('period-dialog').close());
$('new-period-btn').addEventListener('click', () => openPeriodDialog(null));
$('empty-new-period-btn').addEventListener('click', () => openPeriodDialog(null));
$('edit-period-btn').addEventListener('click', () => openPeriodDialog(state.selectedPeriodId));
$('period-select').addEventListener('change', (event) => {
  state.selectedPeriodId = event.target.value;
  saveState();
  resetExpenseForm();
  $('expense-date').value = '';
  render();
});
$('reset-btn').addEventListener('click', () => {
  if (!confirm('すべての期間と支出を消去します。よろしいですか?')) return;
  state = { periods: [], expenses: [], selectedPeriodId: null };
  saveState();
  resetExpenseForm();
  render();
});

render();
