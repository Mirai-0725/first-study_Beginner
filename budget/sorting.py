"""支出一覧の並び替え

画面の見出し(購入日・カテゴリ・金額)をクリックすると、その項目で並び替える。
同じ見出しをもう一度クリックすると、昇順・降順が切り替わる。
選んだ並び順はセッションに記憶し、支出の登録後など別の画面から戻ってきても保つ。
"""
from dataclasses import dataclass

from django.db.models import F

SESSION_KEY = 'expense_sort'

ASC = 'asc'
DESC = 'desc'

# 並び替えの項目: キー → (見出しの表示名, 初めてクリックしたときの向き)
SORT_FIELDS = {
    'date': ('購入日', DESC),       # 新しい順
    'category': ('カテゴリ', ASC),  # 名前順
    'amount': ('金額', DESC),       # 大きい順
}
DEFAULT_SORT = ('date', DESC)

# 同じ値が並んだときは、購入日の新しい順(同じ日は後から登録した順)にする
TIEBREAKER = ['-purchased_on', '-created_at']


@dataclass(frozen=True)
class SortHeader:
    """一覧の見出し1つ分(リンク先や、現在の並び順かどうか)"""

    key: str
    label: str
    active: bool
    order: str  # active のときの現在の向き
    next_order: str  # クリックしたときの向き

    @property
    def query(self):
        return f'?sort={self.key}&order={self.next_order}'

    @property
    def aria_sort(self):
        if not self.active:
            return 'none'
        return 'ascending' if self.order == ASC else 'descending'


def get_sort(request):
    """リクエスト(なければセッション)から、現在の並び順 (キー, 向き) を取得する"""
    sort = request.GET.get('sort')
    order = request.GET.get('order')
    if sort in SORT_FIELDS and order in (ASC, DESC):
        request.session[SESSION_KEY] = [sort, order]
        return sort, order

    saved = request.session.get(SESSION_KEY)
    if saved and len(saved) == 2 and saved[0] in SORT_FIELDS and saved[1] in (ASC, DESC):
        return tuple(saved)
    return DEFAULT_SORT


def order_by_args(sort, order):
    """QuerySet.order_by() に渡す並び順"""
    if sort == 'date':
        return ['purchased_on', 'created_at'] if order == ASC else TIEBREAKER
    if sort == 'amount':
        return ['amount' if order == ASC else '-amount', *TIEBREAKER]
    if sort == 'category':
        # 未分類(カテゴリなし)は、昇順・降順のどちらでも最後にする
        name = F('category__name')
        return [name.asc(nulls_last=True) if order == ASC else name.desc(nulls_last=True), *TIEBREAKER]
    raise ValueError(f'unknown sort: {sort}')


def sort_headers(sort, order):
    """画面の見出しに表示する情報(キーごと)"""
    headers = {}
    for key, (label, first_order) in SORT_FIELDS.items():
        active = key == sort
        if active:
            next_order = ASC if order == DESC else DESC
        else:
            next_order = first_order
        headers[key] = SortHeader(key=key, label=label, active=active, order=order, next_order=next_order)
    return headers
