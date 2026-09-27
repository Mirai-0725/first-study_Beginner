from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    CATEGORY_COLORS,
    UNCATEGORIZED_COLOR,
    UNCATEGORIZED_LABEL,
    BudgetSummary,
    Category,
    Expense,
    Period,
)


def create_period(budget=10000):
    return Period.objects.create(start_date=date(2026, 4, 25), end_date=date(2026, 5, 24), budget=budget)


def add_expense(period, amount, category=None, name='買い物'):
    return Expense.objects.create(
        period=period, name=name, amount=amount, purchased_on=date(2026, 5, 1), category=category
    )


class CategoryModelTests(TestCase):
    def test_creates_category_with_first_color(self):
        category = Category.get_or_create_by_name('食費')
        self.assertEqual(category.name, '食費')
        self.assertEqual(category.color, CATEGORY_COLORS[0])

    def test_reuses_existing_category(self):
        first = Category.get_or_create_by_name('食費')
        second = Category.get_or_create_by_name('  食費  ')  # 前後の空白は無視する
        self.assertEqual(first, second)
        self.assertEqual(Category.objects.count(), 1)

    def test_assigns_colors_in_order_and_cycles(self):
        categories = [Category.get_or_create_by_name(f'カテゴリ{i}') for i in range(len(CATEGORY_COLORS) + 1)]
        self.assertEqual([c.color for c in categories[:len(CATEGORY_COLORS)]], CATEGORY_COLORS)
        self.assertEqual(categories[-1].color, CATEGORY_COLORS[0])  # 使い切ったら最初の色に戻る

    def test_names_are_compared_strictly(self):
        # MySQL の標準の照合順序では同じとみなされる名前も、別のカテゴリとして扱う
        pairs = [('バス', 'パス'), ('はし', 'ハシ'), ('Food', 'food')]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(Category.get_or_create_by_name(a), Category.get_or_create_by_name(b))

    def test_invalid_color_is_rejected(self):
        with self.assertRaises(ValidationError) as cm:
            Category(name='食費', color='red; background: url(x)').full_clean()
        self.assertIn('color', cm.exception.message_dict)

    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValidationError) as cm:
            Category(name='   ', color='#3b82f6').full_clean()
        self.assertIn('name', cm.exception.message_dict)

    def test_name_up_to_20_characters(self):
        Category(name='あ' * 20, color='#3b82f6').full_clean()
        with self.assertRaises(ValidationError):
            Category(name='あ' * 21, color='#3b82f6').full_clean()

    def test_deleting_category_keeps_expenses_as_uncategorized(self):
        period = create_period()
        category = Category.get_or_create_by_name('食費')
        expense = add_expense(period, 100, category)
        category.delete()
        expense.refresh_from_db()
        self.assertIsNone(expense.category)


class CategorySegmentTests(TestCase):
    def setUp(self):
        self.period = create_period(budget=10000)
        self.food = Category.get_or_create_by_name('食費')
        self.daily = Category.get_or_create_by_name('日用品')

    def test_no_expenses(self):
        self.assertEqual(self.period.category_segments(), [])

    def test_totals_by_category_in_descending_order(self):
        add_expense(self.period, 1000, self.food)
        add_expense(self.period, 2000, self.food)
        add_expense(self.period, 500, self.daily)
        add_expense(self.period, 1500)  # 未分類
        segments = self.period.category_segments()
        self.assertEqual(
            [(s.name, s.color, s.amount) for s in segments],
            [
                ('食費', self.food.color, 3000),
                (UNCATEGORIZED_LABEL, UNCATEGORIZED_COLOR, 1500),
                ('日用品', self.daily.color, 500),
            ],
        )
        # バー上の長さは上限金額(10,000円)に対する割合
        self.assertEqual([s.bar_percent for s in segments], [30, 15, 5])
        # 割合は使用済み金額(5,000円)に対する割合
        self.assertEqual([s.share_percent for s in segments], [60, 30, 10])

    def test_only_counts_expenses_in_this_period(self):
        other = Period.objects.create(start_date=date(2026, 5, 25), end_date=date(2026, 6, 24), budget=10000)
        Expense.objects.create(period=other, name='別期間', amount=9000, purchased_on=date(2026, 6, 1), category=self.food)
        add_expense(self.period, 1000, self.food)
        self.assertEqual([s.amount for s in self.period.category_segments()], [1000])

    def test_bar_fills_whole_width_when_over_budget(self):
        add_expense(self.period, 12000, self.food)
        add_expense(self.period, 8000, self.daily)
        segments = self.period.category_segments()
        # 上限を超えたら、使用済み金額(20,000円)を基準にしてバーいっぱいに表示する
        self.assertEqual([s.bar_percent for s in segments], [60, 40])
        self.assertAlmostEqual(sum(s.bar_percent for s in segments), 100)


class CategoryViewTests(TestCase):
    def setUp(self):
        self.period = create_period()
        self.url = self.period.get_absolute_url()

    def post_expense(self, category_name, url=None, **extra):
        data = {'name': '牛乳', 'category_name': category_name, 'amount': '250', 'purchased_on': '2026-05-01'}
        data.update(extra)
        return self.client.post(url or self.url, data)

    def test_new_category_is_created_and_remembered(self):
        self.post_expense('食費')
        expense = Expense.objects.get()
        self.assertEqual(expense.category.name, '食費')
        # 次に画面を開いたとき、入力候補とボタンに表示される
        response = self.client.get(self.url)
        self.assertContains(response, '<option value="食費">', html=False)
        self.assertContains(response, 'data-category="食費"')

    def test_existing_category_is_reused(self):
        self.post_expense('食費')
        self.post_expense(' 食費 ')
        self.assertEqual(Category.objects.count(), 1)
        self.assertEqual(Expense.objects.filter(category__name='食費').count(), 2)

    def test_category_is_optional(self):
        self.post_expense('')
        self.assertIsNone(Expense.objects.get().category)
        self.assertFalse(Category.objects.exists())
        self.assertContains(self.client.get(self.url), '未分類')

    def test_category_name_over_20_characters_is_rejected(self):
        response = self.post_expense('あ' * 21)
        self.assertIn('category_name', response.context['form'].errors)
        self.assertFalse(Expense.objects.exists())

    def test_invalid_expense_does_not_create_category(self):
        self.post_expense('食費', amount='0')
        self.assertFalse(Category.objects.exists())

    def test_edit_shows_current_category_and_can_change_it(self):
        self.post_expense('食費')
        expense = Expense.objects.get()
        edit_url = f'/expenses/{expense.pk}/edit/'
        self.assertContains(self.client.get(edit_url), 'value="食費"')

        self.post_expense('日用品', url=edit_url)
        expense.refresh_from_db()
        self.assertEqual(expense.category.name, '日用品')

        self.post_expense('', url=edit_url)
        expense.refresh_from_db()
        self.assertIsNone(expense.category)

    def test_frequent_categories_are_ordered_by_usage(self):
        for name in ['日用品', '食費', '食費', '交通費', '食費', '日用品']:
            self.post_expense(name)
        response = self.client.get(self.url)
        names = [c.name for c in response.context['frequent_categories']]
        self.assertEqual(names, ['食費', '日用品', '交通費'])

    def test_shows_legend_and_colored_segments(self):
        self.post_expense('食費', amount='3000')
        food = Category.objects.get(name='食費')
        response = self.client.get(self.url)
        self.assertContains(response, f'background-color: {food.color}')
        self.assertContains(response, '¥3,000(100%)')

    def test_number_of_queries_does_not_grow_with_expenses(self):
        food = Category.get_or_create_by_name('食費')
        add_expense(self.period, 100, food)
        with self.assertNumQueries(7) as ctx:
            self.client.get(self.url)
        for i in range(10):
            add_expense(self.period, 100, Category.get_or_create_by_name(f'カテゴリ{i}'))
        with self.assertNumQueries(len(ctx.captured_queries)):
            self.client.get(self.url)


class BudgetSummaryBarTests(TestCase):
    def test_lines_within_budget(self):
        summary = BudgetSummary(budget=10000, spent=5000)
        self.assertEqual(summary.warning_line_percent, 80)
        self.assertEqual(summary.budget_line_percent, 100)

    def test_lines_move_left_when_over_budget(self):
        summary = BudgetSummary(budget=10000, spent=20000)
        self.assertEqual(summary.warning_line_percent, 40)
        self.assertEqual(summary.budget_line_percent, 50)
