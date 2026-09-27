from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

# F-07: 警告に切り替わる使用率(%)。要件の初期値 80%
WARNING_THRESHOLD_PERCENT = 80

# W-04: カテゴリに順番に割り当てる色。警告・超過の背景色(赤系)と見分けやすい色にしている
CATEGORY_COLORS = [
    '#3b82f6',  # 青
    '#22c55e',  # 緑
    '#f59e0b',  # 黄
    '#a855f7',  # 紫
    '#14b8a6',  # 青緑
    '#ec4899',  # ピンク
    '#6366f1',  # 藍
    '#84cc16',  # 黄緑
    '#0ea5e9',  # 水色
    '#f97316',  # オレンジ
    '#78716c',  # 茶
    '#eab308',  # 山吹
]
UNCATEGORIZED_LABEL = '未分類'
UNCATEGORIZED_COLOR = '#9ca3af'

# A-02: 上限金額を超えたときのメッセージ。(超過額が上限金額の何%以下か, メッセージ) を小さい順に並べる。
# 最後の要素(None)は、それより多く超えた場合
OVER_BUDGET_MESSAGES = [
    (5, 'ちょっとだけ超えちゃった…で済むと思っていますか?「誤差です」は通用しませんよ。'),
    (20, '上限金額って、ただの飾りだと思ってました?'),
    (50, '予算を立てた意味、ありました?財布が静かに泣いています。'),
    (100, 'もはや予算は「目安」ですらありませんね。来月の自分に謝ってください。'),
    (None, '上限の2倍超え!ここまで来ると逆に清々しいです。家計簿をつける前に、まず財布を封印しましょう。'),
]


class BudgetStatus(models.TextChoices):
    """F-07: 使用率に応じた予算の状態"""

    NORMAL = 'normal', '予算内'
    WARNING = 'warning', '上限に近づいています'
    OVER = 'over', '上限を超えました'


@dataclass(frozen=True)
class BudgetSummary:
    """F-06: ある時点の予算状況。使用済み金額を1回だけ集計し、そこから各値を計算する"""

    budget: int
    spent: int

    @property
    def remaining(self):
        """残り金額(上限金額 − 使用済み金額)。上限を超えた場合はマイナスになる"""
        return self.budget - self.spent

    @property
    def over_amount(self):
        """超過額。上限を超えていなければ 0"""
        return max(self.spent - self.budget, 0)

    @property
    def over_message(self):
        """A-02: 上限を超えた度合いに応じたメッセージ。上限を超えていなければ空文字"""
        if not self.over_amount:
            return ''
        for limit_percent, message in OVER_BUDGET_MESSAGES:
            # 小数の誤差が出ないよう整数で比較する(超過額 ÷ 上限金額 ≦ limit_percent %)
            if limit_percent is None or self.over_amount * 100 <= self.budget * limit_percent:
                return message
        return ''

    @property
    def usage_rate(self):
        """使用率(%)"""
        return self.spent * 100 / self.budget

    @property
    def usage_percent(self):
        """画面表示用の使用率(%)。小数点以下は切り捨てる(79.99% を 80% と表示しないため)"""
        return self.spent * 100 // self.budget

    @property
    def progress_percent(self):
        """プログレスバーの長さ(%)。100% を上限とする"""
        return min(self.usage_rate, 100)

    # ----- プログレスバーの目盛り -----
    # バー全体の長さは「上限金額」と「使用済み金額」の大きい方。上限を超えたときは、
    # バーいっぱいに支出を表示し、上限の位置に線を引く

    @property
    def bar_scale(self):
        return max(self.budget, self.spent)

    @property
    def warning_line_percent(self):
        """警告ライン(上限金額の 80%)の、バー上の位置(%)"""
        return self.budget * WARNING_THRESHOLD_PERCENT / self.bar_scale

    @property
    def budget_line_percent(self):
        """上限金額の、バー上の位置(%)。上限を超えていなければ 100"""
        return self.budget * 100 / self.bar_scale

    @property
    def status(self):
        """F-07: 使用率に応じた状態。小数の誤差が出ないよう整数で比較する"""
        if self.spent > self.budget:
            return BudgetStatus.OVER
        if self.spent * 100 >= self.budget * WARNING_THRESHOLD_PERCENT:
            return BudgetStatus.WARNING
        return BudgetStatus.NORMAL


@dataclass(frozen=True)
class CategorySegment:
    """W-04: 予算状況のプログレスバーに表示する、カテゴリ1つ分の区間"""

    name: str
    color: str
    amount: int
    bar_percent: float  # バー上の長さ(%)
    share_percent: int  # 使用済み金額に占める割合(%)。小数点以下は切り捨てる


class Category(models.Model):
    """W-04: 支出のカテゴリ。一度使ったカテゴリは記憶し、次から選べるようにする"""

    # MySQL の標準の照合順序では「バス」と「パス」、「A」と「a」が同じとみなされるため、
    # カテゴリ名は1文字ずつ厳密に比較する照合順序を使う
    name = models.CharField('カテゴリ名', max_length=20, unique=True, db_collation='utf8mb4_bin')
    color = models.CharField(
        '色',
        max_length=7,
        validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$', '色は #RRGGBB の形式で指定してください。')],
    )
    created_at = models.DateTimeField('作成日時', auto_now_add=True)

    class Meta:
        verbose_name = 'カテゴリ'
        verbose_name_plural = 'カテゴリ'
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': 'カテゴリ名を入力してください。'})

    @classmethod
    def get_or_create_by_name(cls, name):
        """カテゴリ名からカテゴリを取得する。初めて使う名前なら、次の色を割り当てて作成する"""
        name = name.strip()
        category = cls.objects.filter(name=name).first()
        if category is None:
            color = CATEGORY_COLORS[cls.objects.count() % len(CATEGORY_COLORS)]
            category = cls.objects.create(name=name, color=color)
        return category


class Period(models.Model):
    """予算を管理する期間(開始日〜締め日)と、その期間の上限金額"""

    start_date = models.DateField('開始日')
    end_date = models.DateField('締め日')
    budget = models.PositiveIntegerField('上限金額', validators=[MinValueValidator(1)])
    created_at = models.DateTimeField('作成日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True)

    class Meta:
        verbose_name = '期間'
        verbose_name_plural = '期間'
        ordering = ['-start_date']
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F('start_date')),
                name='period_end_date_gte_start_date',
            ),
            models.CheckConstraint(
                condition=Q(budget__gte=1),
                name='period_budget_gte_1',
            ),
        ]

    def __str__(self):
        return f'{self.start_date:%Y/%m/%d}〜{self.end_date:%Y/%m/%d}'

    def clean(self):
        # 項目単体のチェックで未入力エラーになっている場合は、組み合わせのチェックをしない
        if self.start_date is None or self.end_date is None:
            return

        if self.end_date < self.start_date:
            raise ValidationError({'end_date': '締め日は開始日以降の日付にしてください。'})

        # 期間同士の日付は重複させない
        overlapping = (
            Period.objects.filter(start_date__lte=self.end_date, end_date__gte=self.start_date)
            .exclude(pk=self.pk)
            .first()
        )
        if overlapping:
            raise ValidationError(f'既存の期間({overlapping})と日付が重なっています。')

        # 日付を変更したことで、登録済みの支出が期間外にならないようにする
        if self.pk:
            outside_count = self.expenses.filter(
                Q(purchased_on__lt=self.start_date) | Q(purchased_on__gt=self.end_date)
            ).count()
            if outside_count:
                raise ValidationError(
                    f'新しい日付の範囲外になる支出が{outside_count}件あります。'
                    '先に支出を修正・削除してください。'
                )

    def get_absolute_url(self):
        return reverse('budget:period_detail', args=[self.pk])

    def contains(self, date):
        """指定した日付がこの期間内(開始日・締め日を含む)かどうか"""
        return self.start_date <= date <= self.end_date

    # ===== F-06: 予算状況の計算 =====

    def summary(self):
        """現在の予算状況。画面表示ではこれを1回呼び、結果をまとめて使う"""
        return BudgetSummary(budget=self.budget, spent=self.spent_amount)

    def category_segments(self):
        """W-04: カテゴリ別の合計金額を、プログレスバーの区間として返す(金額の大きい順)"""
        rows = list(
            self.expenses.values('category__name', 'category__color')
            .annotate(total=Sum('amount'))
            .order_by('-total', 'category__name')
        )
        spent = sum(row['total'] for row in rows)
        scale = max(self.budget, spent)
        return [
            CategorySegment(
                name=row['category__name'] or UNCATEGORIZED_LABEL,
                color=row['category__color'] or UNCATEGORIZED_COLOR,
                amount=row['total'],
                bar_percent=row['total'] * 100 / scale,
                share_percent=row['total'] * 100 // spent,
            )
            for row in rows
        ]

    @property
    def spent_amount(self):
        """使用済み金額(期間内の支出金額の合計)"""
        return self.expenses.aggregate(total=Sum('amount'))['total'] or 0

    @property
    def remaining_amount(self):
        return self.summary().remaining

    @property
    def usage_rate(self):
        return self.summary().usage_rate

    @property
    def status(self):
        return self.summary().status


class Expense(models.Model):
    """支出1件(購入した物と金額)"""

    period = models.ForeignKey(
        Period,
        verbose_name='期間',
        on_delete=models.PROTECT,  # 支出が残っている期間は削除できないようにする
        related_name='expenses',
    )
    name = models.CharField('品名', max_length=50)
    category = models.ForeignKey(
        Category,
        verbose_name='カテゴリ',
        on_delete=models.SET_NULL,  # カテゴリを削除しても支出は残し、「未分類」として扱う
        related_name='expenses',
        null=True,
        blank=True,
    )
    amount = models.PositiveIntegerField('金額', validators=[MinValueValidator(1)])
    purchased_on = models.DateField('購入日', default=timezone.localdate)
    created_at = models.DateTimeField('作成日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True)

    class Meta:
        verbose_name = '支出'
        verbose_name_plural = '支出'
        # F-04: 購入日の新しい順。同じ日は後から登録したものを上にする
        ordering = ['-purchased_on', '-created_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=1),
                name='expense_amount_gte_1',
            ),
        ]

    def __str__(self):
        return f'{self.purchased_on:%Y/%m/%d} {self.name} ¥{self.amount:,}'

    def clean(self):
        # 品名が空白だけの場合は未入力として扱う
        # (空文字の場合は項目のチェックで必須エラーになるため、ここでは空白だけの場合のみ扱う)
        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': '品名を入力してください。'})

        # 購入日は所属する期間内の日付に限る
        if self.period_id and self.purchased_on and not self.period.contains(self.purchased_on):
            raise ValidationError(
                {'purchased_on': f'購入日は期間({self.period})内の日付にしてください。'}
            )
