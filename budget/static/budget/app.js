'use strict';

// 期間のプルダウンを切り替えたら、すぐにその期間を表示する
document.querySelectorAll('select[data-auto-submit]').forEach((select) => {
  select.addEventListener('change', () => select.form.submit());
});

// W-04: よく使うカテゴリのボタンを押したら、カテゴリの入力欄に入れる
const categoryInput = document.getElementById('id_category_name');
const categoryChips = document.querySelectorAll('.category-chip');

function highlightSelectedChip() {
  categoryChips.forEach((chip) => {
    chip.classList.toggle('selected', categoryInput && chip.dataset.category === categoryInput.value.trim());
  });
}

if (categoryInput) {
  categoryChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      categoryInput.value = chip.dataset.category;
      highlightSelectedChip();
    });
  });
  categoryInput.addEventListener('input', highlightSelectedChip);
  highlightSelectedChip();
}

// 削除などの取り消せない操作の前に確認ダイアログを表示する
document.querySelectorAll('form[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});
