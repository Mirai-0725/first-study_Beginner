from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BudgetSummary, Expense, Period
from .templatetags.budget_extras import yen


def create_period(start=date(2026, 4, 25), end=date(2026, 5, 24), budget=10000):
    return Period.objects.create(start_date=start, end_date=end, budget=budget)


def add_expense(period, amount=1000, name='買い物', purchased_on=None):
    return Expense.objects.create(
        period=period, name=name, amount=amount, purchased_on=purchased_on or period.start_date
    )


class IndexViewTests(TestCase):
    def test_shows_empty_state_when_no_period(self):
        response = self.client.get(reverse('budget:index'))
        self.assertContains(response, 'はじめに期間を設定してください')

    def test_redirects_to_period_containing_today(self):
        today = timezone.localdate()
        current = create_period(start=today - timedelta(days=3), end=today + timedelta(days=3))
        create_period(start=today + timedelta(days=10), end=today + timedelta(days=20))  # 未来の期間
        response = self.client.get(reverse('budget:index'))
        self.assertRedirects(response, current.get_absolute_url())

    def test_redirects_to_latest_period_when_none_contains_today(self):
        create_period(start=date(2020, 1, 1), end=date(2020, 1, 31))
        latest = create_period(start=date(2020, 2, 1), end=date(2020, 2, 29))
        response = self.client.get(reverse('budget:index'))
        self.assertRedirects(response, latest.get_absolute_url())

    def test_period_selector_redirects_to_selected_period(self):
        period = create_period()
        response = self.client.get(reverse('budget:index'), {'period': period.pk})
        self.assertRedirects(response, period.get_absolute_url())


class PeriodDetailViewTests(TestCase):
    def setUp(self):
        self.period = create_period(budget=10000)
        self.url = self.period.get_absolute_url()

    def test_shows_summary(self):
        add_expense(self.period, amount=3000)
        add_expense(self.period, amount=1500)
        response = self.client.get(self.url)
        self.assertContains(response, '2026/04/25〜2026/05/24')
        self.assertContains(response, '¥10,000')  # 上限金額
        self.assertContains(response, '¥4,500')   # 使用済み金額
        self.assertContains(response, '¥5,500')   # 残り金額
        self.assertContains(response, '45%')

    def test_background_status_normal(self):
        add_expense(self.period, amount=7999)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-status="normal"')
        self.assertContains(response, '予算内')
        # 79.99% は切り捨てて 79% と表示する(80% と表示しない)
        self.assertContains(response, '79%')

    def test_background_status_warning(self):
        add_expense(self.period, amount=8000)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-status="warning"')
        self.assertContains(response, '上限に近づいています')

    def test_background_status_over_shows_over_amount(self):
        add_expense(self.period, amount=12000)
        response = self.client.get(self.url)
        self.assertContains(response, 'data-status="over"')
        self.assertContains(response, '上限を超えました')
        self.assertContains(response, '超過額')
        self.assertContains(response, '¥2,000')
        self.assertNotContains(response, '残り金額')

    def test_lists_only_expenses_in_this_period(self):
        other = create_period(start=date(2026, 5, 25), end=date(2026, 6, 24))
        add_expense(self.period, name='牛乳')
        add_expense(other, name='別期間の買い物')
        response = self.client.get(self.url)
        self.assertContains(response, '牛乳')
        self.assertNotContains(response, '別期間の買い物')

    def test_shows_empty_message_when_no_expenses(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'この期間の支出はまだありません')

    def test_purchase_date_input_is_limited_to_period(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'min="2026-04-25"')
        self.assertContains(response, 'max="2026-05-24"')

    def test_purchase_date_defaults_to_period_start_when_today_is_outside(self):
        # 過去の期間を表示している場合、当日は期間外なので開始日が初期値になる
        response = self.client.get(self.url)
        self.assertEqual(response.context['form'].initial['purchased_on'], date(2026, 4, 25))

    def test_purchase_date_defaults_to_today_when_inside_period(self):
        today = timezone.localdate()
        period = create_period(start=today - timedelta(days=1), end=today + timedelta(days=1))
        response = self.client.get(period.get_absolute_url())
        self.assertEqual(response.context['form'].initial['purchased_on'], today)

    def test_not_found(self):
        response = self.client.get(reverse('budget:period_detail', args=[9999]))
        self.assertEqual(response.status_code, 404)


class ExpenseCreateViewTests(TestCase):
    def setUp(self):
        self.period = create_period()
        self.url = self.period.get_absolute_url()

    def post(self, **data):
        values = {'name': '牛乳', 'amount': '250', 'purchased_on': '2026-05-01'}
        values.update(data)
        return self.client.post(self.url, values, follow=True)

    def test_creates_expense(self):
        response = self.post()
        self.assertRedirects(response, self.url)
        expense = Expense.objects.get()
        self.assertEqual((expense.period, expense.name, expense.amount), (self.period, '牛乳', 250))
        self.assertContains(response, '「牛乳」を登録しました')

    def test_invalid_input_shows_errors_and_does_not_save(self):
        cases = {
            'name': {'name': ''},
            'amount': {'amount': '0'},
            'purchased_on': {'purchased_on': '2026-05-25'},  # 期間外
        }
        for field, data in cases.items():
            with self.subTest(field=field):
                response = self.post(**data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertFalse(Expense.objects.exists())

    def test_blank_name_shows_only_one_error(self):
        # 空文字・空白のみのどちらでも、品名のエラーは1つだけ表示されること
        for name in ['', '   ']:
            with self.subTest(name=name):
                response = self.post(name=name)
                self.assertEqual(len(response.context['form'].errors['name']), 1)
                self.assertFalse(Expense.objects.exists())

    def test_non_integer_amount_is_rejected(self):
        response = self.post(amount='12.5')
        self.assertIn('amount', response.context['form'].errors)
        self.assertFalse(Expense.objects.exists())


class ExpenseEditViewTests(TestCase):
    def setUp(self):
        self.period = create_period()
        self.expense = add_expense(self.period, name='牛乳', amount=250, purchased_on=date(2026, 5, 1))
        self.url = reverse('budget:expense_edit', args=[self.expense.pk])

    def test_shows_form_with_current_values(self):
        response = self.client.get(self.url)
        self.assertContains(response, '支出を編集')
        self.assertContains(response, 'value="牛乳"')
        self.assertContains(response, 'class="editing"')

    def test_updates_expense(self):
        response = self.client.post(
            self.url, {'name': '豆乳', 'amount': '300', 'purchased_on': '2026-05-02'}, follow=True
        )
        self.assertRedirects(response, self.period.get_absolute_url())
        self.expense.refresh_from_db()
        self.assertEqual((self.expense.name, self.expense.amount), ('豆乳', 300))

    def test_invalid_update_is_not_saved(self):
        response = self.client.post(self.url, {'name': '豆乳', 'amount': '-1', 'purchased_on': '2026-05-02'})
        self.assertIn('amount', response.context['form'].errors)
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.amount, 250)


class ExpenseDeleteViewTests(TestCase):
    def setUp(self):
        self.period = create_period()
        self.expense = add_expense(self.period, name='牛乳')
        self.url = reverse('budget:expense_delete', args=[self.expense.pk])

    def test_deletes_expense(self):
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, self.period.get_absolute_url())
        self.assertFalse(Expense.objects.exists())
        self.assertContains(response, '「牛乳」を削除しました')

    def test_get_request_does_not_delete(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Expense.objects.exists())


class PeriodFormViewTests(TestCase):
    def test_creates_period_and_shows_it(self):
        response = self.client.post(
            reverse('budget:period_create'),
            {'start_date': '2026-04-25', 'end_date': '2026-05-24', 'budget': '50000'},
            follow=True,
        )
        period = Period.objects.get()
        self.assertRedirects(response, period.get_absolute_url())
        self.assertEqual(period.budget, 50000)

    def test_invalid_period_shows_errors(self):
        response = self.client.post(
            reverse('budget:period_create'),
            {'start_date': '2026-05-24', 'end_date': '2026-04-25', 'budget': '50000'},
        )
        self.assertContains(response, '締め日は開始日以降の日付にしてください。')
        self.assertFalse(Period.objects.exists())

    def test_overlapping_period_shows_error(self):
        create_period(start=date(2026, 4, 25), end=date(2026, 5, 24))
        response = self.client.post(
            reverse('budget:period_create'),
            {'start_date': '2026-05-01', 'end_date': '2026-05-31', 'budget': '50000'},
        )
        self.assertContains(response, '日付が重なっています')
        self.assertEqual(Period.objects.count(), 1)

    def test_edits_period(self):
        period = create_period(budget=10000)
        response = self.client.post(
            reverse('budget:period_edit', args=[period.pk]),
            {'start_date': '2026-04-25', 'end_date': '2026-05-24', 'budget': '20000'},
            follow=True,
        )
        self.assertRedirects(response, period.get_absolute_url())
        period.refresh_from_db()
        self.assertEqual(period.budget, 20000)

    def test_edit_form_shows_current_dates(self):
        period = create_period()
        response = self.client.get(reverse('budget:period_edit', args=[period.pk]))
        self.assertContains(response, 'value="2026-04-25"')
        self.assertContains(response, 'value="2026-05-24"')

    def test_cannot_change_dates_if_expenses_fall_outside(self):
        period = create_period()
        add_expense(period, purchased_on=date(2026, 4, 26))
        response = self.client.post(
            reverse('budget:period_edit', args=[period.pk]),
            {'start_date': '2026-05-01', 'end_date': '2026-05-24', 'budget': '10000'},
        )
        self.assertContains(response, '範囲外になる支出が1件あります')
        period.refresh_from_db()
        self.assertEqual(period.start_date, date(2026, 4, 25))


class YenFilterTests(TestCase):
    def test_formats_amount(self):
        self.assertEqual(yen(0), '¥0')
        self.assertEqual(yen(12345), '¥12,345')
        self.assertEqual(yen(-500), '-¥500')


class BudgetSummaryDisplayTests(TestCase):
    def test_usage_percent_is_floored(self):
        self.assertEqual(BudgetSummary(budget=10000, spent=7999).usage_percent, 79)
        self.assertEqual(BudgetSummary(budget=3, spent=1).usage_percent, 33)

    def test_progress_percent_is_capped_at_100(self):
        self.assertEqual(BudgetSummary(budget=10000, spent=15000).progress_percent, 100)

    def test_over_amount(self):
        self.assertEqual(BudgetSummary(budget=10000, spent=9000).over_amount, 0)
        self.assertEqual(BudgetSummary(budget=10000, spent=12000).over_amount, 2000)
