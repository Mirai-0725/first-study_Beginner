from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from .models import BudgetStatus, Expense, Period


class DatabaseConnectionTests(TestCase):
    """開発環境のセットアップ確認用。MySQL に接続できていることを確かめる。"""

    def test_uses_mysql(self):
        self.assertEqual(connection.vendor, 'mysql')

    def test_can_query_database(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            self.assertEqual(cursor.fetchone(), (1,))


def create_period(start=date(2026, 4, 25), end=date(2026, 5, 24), budget=50000):
    return Period.objects.create(start_date=start, end_date=end, budget=budget)


class PeriodValidationTests(TestCase):
    """F-01, F-02: 期間の入力チェック"""

    def test_valid_period(self):
        period = Period(start_date=date(2026, 4, 25), end_date=date(2026, 5, 24), budget=50000)
        period.full_clean()  # 例外が出なければOK

    def test_start_and_end_on_same_day_is_valid(self):
        Period(start_date=date(2026, 5, 1), end_date=date(2026, 5, 1), budget=1000).full_clean()

    def test_end_date_before_start_date_is_invalid(self):
        period = Period(start_date=date(2026, 5, 24), end_date=date(2026, 4, 25), budget=50000)
        with self.assertRaises(ValidationError) as cm:
            period.full_clean()
        self.assertIn('end_date', cm.exception.message_dict)

    def test_budget_must_be_at_least_1(self):
        period = Period(start_date=date(2026, 4, 25), end_date=date(2026, 5, 24), budget=0)
        with self.assertRaises(ValidationError) as cm:
            period.full_clean()
        self.assertIn('budget', cm.exception.message_dict)

    def test_required_fields(self):
        with self.assertRaises(ValidationError) as cm:
            Period().full_clean()
        self.assertEqual(set(cm.exception.message_dict), {'start_date', 'end_date', 'budget'})

    def test_overlapping_period_is_invalid(self):
        create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        # 既存期間の締め日と同じ日から始まる → 1日重なる
        period = Period(start_date=date(2026, 5, 24), end_date=date(2026, 6, 24), budget=50000)
        with self.assertRaisesMessage(ValidationError, '日付が重なっています'):
            period.full_clean()

    def test_period_inside_existing_period_is_invalid(self):
        create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        period = Period(start_date=date(2026, 5, 1), end_date=date(2026, 5, 10), budget=50000)
        with self.assertRaisesMessage(ValidationError, '日付が重なっています'):
            period.full_clean()

    def test_adjacent_period_is_valid(self):
        create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        Period(start_date=date(2026, 5, 25), end_date=date(2026, 6, 24), budget=50000).full_clean()

    def test_editing_period_does_not_overlap_with_itself(self):
        period = create_period()
        period.budget = 60000
        period.full_clean()

    def test_cannot_change_dates_if_expenses_fall_outside(self):
        period = create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        Expense.objects.create(period=period, name='牛乳', amount=250, purchased_on=date(2026, 4, 26))
        period.start_date = date(2026, 5, 1)
        with self.assertRaisesMessage(ValidationError, '範囲外になる支出が1件あります'):
            period.full_clean()

    def test_can_change_dates_if_expenses_stay_inside(self):
        period = create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        Expense.objects.create(period=period, name='牛乳', amount=250, purchased_on=date(2026, 5, 1))
        period.start_date = date(2026, 5, 1)
        period.full_clean()


class PeriodDatabaseConstraintTests(TestCase):
    """入力チェックを通さずに保存した場合でも、DBの制約で不正な値を防げること"""

    def test_end_date_before_start_date_is_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            create_period(start=date(2026, 5, 24), end=date(2026, 4, 25))

    def test_budget_zero_is_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            create_period(budget=0)


class ExpenseValidationTests(TestCase):
    """F-03, F-05: 支出の入力チェック"""

    def setUp(self):
        self.period = create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))

    def build(self, **kwargs):
        values = {'period': self.period, 'name': '牛乳', 'amount': 250, 'purchased_on': date(2026, 5, 1)}
        values.update(kwargs)
        return Expense(**values)

    def test_valid_expense(self):
        self.build().full_clean()

    def test_name_up_to_50_characters_is_valid(self):
        self.build(name='あ' * 50).full_clean()

    def test_name_over_50_characters_is_invalid(self):
        with self.assertRaises(ValidationError) as cm:
            self.build(name='あ' * 51).full_clean()
        self.assertIn('name', cm.exception.message_dict)

    def test_blank_name_is_invalid(self):
        for name in ['', '   ']:
            with self.subTest(name=name), self.assertRaises(ValidationError) as cm:
                self.build(name=name).full_clean()
            self.assertIn('name', cm.exception.message_dict)

    def test_name_is_stripped(self):
        expense = self.build(name='  牛乳  ')
        expense.full_clean()
        self.assertEqual(expense.name, '牛乳')

    def test_amount_must_be_at_least_1(self):
        with self.assertRaises(ValidationError) as cm:
            self.build(amount=0).full_clean()
        self.assertIn('amount', cm.exception.message_dict)

    def test_purchase_date_on_period_boundaries_is_valid(self):
        self.build(purchased_on=date(2026, 4, 25)).full_clean()
        self.build(purchased_on=date(2026, 5, 24)).full_clean()

    def test_purchase_date_outside_period_is_invalid(self):
        for purchased_on in [date(2026, 4, 24), date(2026, 5, 25)]:
            with self.subTest(purchased_on=purchased_on), self.assertRaises(ValidationError) as cm:
                self.build(purchased_on=purchased_on).full_clean()
            self.assertIn('purchased_on', cm.exception.message_dict)

    def test_purchase_date_defaults_to_today(self):
        expense = Expense(period=self.period, name='牛乳', amount=250)
        # 日本時間(settings.TIME_ZONE)の今日の日付になること
        self.assertEqual(expense.purchased_on, timezone.localdate())

    def test_amount_zero_is_rejected_by_db(self):
        with self.assertRaises(IntegrityError):
            Expense.objects.create(period=self.period, name='牛乳', amount=0, purchased_on=date(2026, 5, 1))

    def test_period_with_expenses_cannot_be_deleted(self):
        Expense.objects.create(period=self.period, name='牛乳', amount=250, purchased_on=date(2026, 5, 1))
        with self.assertRaises(ProtectedError):
            self.period.delete()

    def test_expenses_are_ordered_by_newest_purchase_date(self):
        old = Expense.objects.create(period=self.period, name='古い', amount=100, purchased_on=date(2026, 4, 30))
        new = Expense.objects.create(period=self.period, name='新しい', amount=100, purchased_on=date(2026, 5, 2))
        same_day_later = Expense.objects.create(
            period=self.period, name='同日・後から登録', amount=100, purchased_on=date(2026, 5, 2)
        )
        self.assertEqual(list(self.period.expenses.all()), [same_day_later, new, old])

    def test_japanese_and_emoji_can_be_saved(self):
        expense = Expense.objects.create(period=self.period, name='ケーキ🍰', amount=500, purchased_on=date(2026, 5, 1))
        expense.refresh_from_db()
        self.assertEqual(expense.name, 'ケーキ🍰')


class BudgetSummaryTests(TestCase):
    """F-06, F-07: 予算状況の計算と警告状態の判定"""

    def setUp(self):
        self.period = create_period(budget=10000)

    def spend(self, amount):
        Expense.objects.create(period=self.period, name='買い物', amount=amount, purchased_on=date(2026, 5, 1))

    def test_no_expenses(self):
        self.assertEqual(self.period.spent_amount, 0)
        self.assertEqual(self.period.remaining_amount, 10000)
        self.assertEqual(self.period.usage_rate, 0)
        self.assertEqual(self.period.status, BudgetStatus.NORMAL)

    def test_sums_expenses_in_the_period_only(self):
        other = create_period(start=date(2026, 5, 25), end=date(2026, 6, 24))
        Expense.objects.create(period=other, name='別期間', amount=9999, purchased_on=date(2026, 6, 1))
        self.spend(3000)
        self.spend(1500)
        self.assertEqual(self.period.spent_amount, 4500)
        self.assertEqual(self.period.remaining_amount, 5500)
        self.assertEqual(self.period.usage_rate, 45)

    def test_remaining_amount_is_negative_when_over_budget(self):
        self.spend(12000)
        self.assertEqual(self.period.remaining_amount, -2000)
        self.assertEqual(self.period.usage_rate, 120)

    def test_status_thresholds(self):
        # (使用済み金額, 期待する状態)  上限金額は 10,000円
        cases = [
            (7999, BudgetStatus.NORMAL),    # 79.99%
            (8000, BudgetStatus.WARNING),   # 80% ちょうど
            (10000, BudgetStatus.WARNING),  # 100% ちょうど
            (10001, BudgetStatus.OVER),     # 100% 超
        ]
        for spent, expected in cases:
            with self.subTest(spent=spent):
                self.period.expenses.all().delete()
                self.spend(spent)
                self.assertEqual(self.period.status, expected)
