from datetime import date

from django.test import TestCase

from .models import Category, Expense, Period


class ExpenseSortTests(TestCase):
    def setUp(self):
        self.period = Period.objects.create(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), budget=100000)
        self.url = self.period.get_absolute_url()
        food = Category.get_or_create_by_name('食費')
        daily = Category.get_or_create_by_name('日用品')
        # (品名, 金額, 購入日, カテゴリ) ※ 登録順も並び順の判定に使う
        for name, amount, day, category in [
            ('A', 300, 1, food),
            ('B', 1000, 3, None),
            ('C', 300, 2, daily),
            ('D', 50, 3, food),
        ]:
            Expense.objects.create(
                period=self.period, name=name, amount=amount, purchased_on=date(2026, 5, day), category=category
            )

    def names(self, response):
        return [e.name for e in response.context['expenses']]

    def test_default_is_newest_purchase_date_first(self):
        # 同じ日は後から登録したものが上
        self.assertEqual(self.names(self.client.get(self.url)), ['D', 'B', 'C', 'A'])

    def test_sort_by_date_ascending(self):
        self.assertEqual(self.names(self.client.get(self.url, {'sort': 'date', 'order': 'asc'})), ['A', 'C', 'B', 'D'])

    def test_sort_by_amount(self):
        # 同じ金額(A と C)は購入日の新しい順
        self.assertEqual(self.names(self.client.get(self.url, {'sort': 'amount', 'order': 'desc'})), ['B', 'C', 'A', 'D'])
        self.assertEqual(self.names(self.client.get(self.url, {'sort': 'amount', 'order': 'asc'})), ['D', 'C', 'A', 'B'])

    def test_sort_by_category_puts_uncategorized_last(self):
        # カテゴリ名は文字コード順(日用品 < 食費)。未分類(B)は昇順・降順のどちらでも最後
        self.assertEqual(self.names(self.client.get(self.url, {'sort': 'category', 'order': 'asc'})), ['C', 'D', 'A', 'B'])
        self.assertEqual(self.names(self.client.get(self.url, {'sort': 'category', 'order': 'desc'})), ['D', 'A', 'C', 'B'])

    def test_sort_is_remembered_after_adding_expense(self):
        self.client.get(self.url, {'sort': 'amount', 'order': 'asc'})
        self.client.post(self.url, {'name': 'E', 'category_name': '', 'amount': '10', 'purchased_on': '2026-05-04'})
        response = self.client.get(self.url)  # 登録後のリダイレクト先(並び順の指定なし)
        self.assertEqual(self.names(response), ['E', 'D', 'C', 'A', 'B'])

    def test_sort_is_kept_on_edit_page(self):
        self.client.get(self.url, {'sort': 'amount', 'order': 'desc'})
        expense = Expense.objects.get(name='A')
        response = self.client.get(f'/expenses/{expense.pk}/edit/')
        self.assertEqual(self.names(response), ['B', 'C', 'A', 'D'])

    def test_invalid_parameters_are_ignored(self):
        for params in [{'sort': 'name', 'order': 'asc'}, {'sort': 'amount', 'order': 'up'}, {'sort': 'amount'}]:
            with self.subTest(params=params):
                self.assertEqual(self.names(self.client.get(self.url, params)), ['D', 'B', 'C', 'A'])

    def test_header_links_toggle_order(self):
        response = self.client.get(self.url, {'sort': 'amount', 'order': 'desc'})
        headers = response.context['sort_headers']
        # 現在の項目はクリックで向きが反転し、ほかの項目は既定の向きになる
        self.assertEqual(headers['amount'].query, '?sort=amount&order=asc')
        self.assertEqual(headers['date'].query, '?sort=date&order=desc')
        self.assertEqual(headers['category'].query, '?sort=category&order=asc')
        self.assertContains(response, 'aria-sort="descending"')
        self.assertContains(response, f'href="{self.url}?sort=amount&amp;order=asc"')
