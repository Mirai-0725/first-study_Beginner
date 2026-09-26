'use strict';

// 期間のプルダウンを切り替えたら、すぐにその期間を表示する
document.querySelectorAll('select[data-auto-submit]').forEach((select) => {
  select.addEventListener('change', () => select.form.submit());
});

// 削除などの取り消せない操作の前に確認ダイアログを表示する
document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});
