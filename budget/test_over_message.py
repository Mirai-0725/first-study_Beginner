from datetime import date

from django.test import TestCase

from .models import OVER_BUDGET_MESSAGES, BudgetSummary, Expense, Period

MESSAGES = [message for _, message in OVER_BUDGET_MESSAGES]


class OverBudgetMessageTests(TestCase):
    def test_no_message_within_budget(self):
        for spent in [0, 8000, 10000]:  # 上限ちょうど(100%)も超過ではない
            with self.subTest(spent=spent):
                self.assertEqual(BudgetSummary(budget=10000, spent=spent).over_message, '')

    def test_message_changes_by_how_much_over(self):
        # 上限金額 10,000円。(使用済み金額, 期待するメッセージの段階) 境目の前後を確認する
        cases = [
            (10001, 0),   # 0.01% 超過
            (10500, 0),   # 5% ちょうど
            (10501, 1),   # 5% を少し超える
            (12000, 1),   # 20% ちょうど
            (12001, 2),
            (15000, 2),   # 50% ちょうど
            (15001, 3),
            (20000, 3),   # 100% ちょうど(上限の2倍)
            (20001, 4),
            (100000, 4),  # 900% 超過
        ]
        for spent, level in cases:
            with self.subTest(spent=spent):
                self.assertEqual(BudgetSummary(budget=10000, spent=spent).over_message, MESSAGES[level])

    def test_every_level_has_a_different_message(self):
        self.assertEqual(len(set(MESSAGES)), len(MESSAGES))


class OverBudgetMessageViewTests(TestCase):
    def setUp(self):
        self.period = Period.objects.create(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), budget=10000)

    def spend(self, amount):
        Expense.objects.create(period=self.period, name='買い物', amount=amount, purchased_on=date(2026, 5, 1))

    def test_message_is_shown_when_over_budget(self):
        self.spend(13000)  # 30% 超過
        response = self.client.get(self.period.get_absolute_url())
        self.assertContains(response, 'class="over-message"')
        self.assertContains(response, MESSAGES[2])

    def test_message_is_not_shown_within_budget(self):
        self.spend(9000)
        response = self.client.get(self.period.get_absolute_url())
        self.assertNotContains(response, 'class="over-message"')
