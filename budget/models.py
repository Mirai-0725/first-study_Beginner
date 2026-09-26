from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

# F-07: 警告に切り替わる使用率(%)。要件の初期値 80%
WARNING_THRESHOLD_PERCENT = 80


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

    @property
    def status(self):
        """F-07: 使用率に応じた状態。小数の誤差が出ないよう整数で比較する"""
        if self.spent > self.budget:
            return BudgetStatus.OVER
        if self.spent * 100 >= self.budget * WARNING_THRESHOLD_PERCENT:
            return BudgetStatus.WARNING
        return BudgetStatus.NORMAL


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
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError({'name': '品名を入力してください。'})

        # 購入日は所属する期間内の日付に限る
        if self.period_id and self.purchased_on and not self.period.contains(self.purchased_on):
            raise ValidationError(
                {'purchased_on': f'購入日は期間({self.period})内の日付にしてください。'}
            )
