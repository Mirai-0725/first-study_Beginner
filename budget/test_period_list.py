from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Expense, Period, PeriodTiming


class PeriodTimingTests(TestCase):
    def test_timing(self):
        period = Period(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), budget=1000)
        cases = [
            (date(2026, 4, 30), PeriodTiming.FUTURE),
            (date(2026, 5, 1), PeriodTiming.CURRENT),   # 開始日
            (date(2026, 5, 31), PeriodTiming.CURRENT),  # 締め日
            (date(2026, 6, 1), PeriodTiming.PAST),
        ]
        for today, expected in cases:
            with self.subTest(today=today):
                self.assertEqual(period.timing(today), expected)


class PeriodListViewTests(TestCase):
    url = reverse('budget:period_list')

    def test_empty(self):
        response = self.client.get(self.url)
        self.assertContains(response, '期間はまだありません')

    def test_lists_all_periods_with_summary(self):
        today = timezone.localdate()
        past = Period.objects.create(start_date=today - timedelta(days=60), end_date=today - timedelta(days=31), budget=10000)
        current = Period.objects.create(start_date=today - timedelta(days=30), end_date=today + timedelta(days=5), budget=10000)
        future = Period.objects.create(start_date=today + timedelta(days=6), end_date=today + timedelta(days=36), budget=10000)
        Expense.objects.create(period=past, name='A', amount=12000, purchased_on=past.start_date)
        Expense.objects.create(period=past, name='B', amount=500, purchased_on=past.start_date)
        Expense.objects.create(period=current, name='C', amount=8500, purchased_on=current.start_date)

        response = self.client.get(self.url)
        rows = response.context['rows']
        # 開始日の新しい順
        self.assertEqual([row['period'] for row in rows], [future, current, past])
        self.assertEqual([row['summary'].spent for row in rows], [0, 8500, 12500])
        self.assertEqual([row['timing'] for row in rows], [PeriodTiming.FUTURE, PeriodTiming.CURRENT, PeriodTiming.PAST])
        self.assertEqual([row['summary'].status for row in rows], ['normal', 'warning', 'over'])
        # 各期間の画面へのリンク
        for period in [past, current, future]:
            self.assertContains(response, f'href="{period.get_absolute_url()}"')
        self.assertContains(response, '¥12,500')
        self.assertContains(response, '125%')

    def test_query_count_does_not_grow_with_periods(self):
        Period.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), budget=1000)
        with self.assertNumQueries(1) as ctx:
            self.client.get(self.url)
        for month in range(2, 8):
            period = Period.objects.create(start_date=date(2026, month, 1), end_date=date(2026, month, 28), budget=1000)
            Expense.objects.create(period=period, name='A', amount=100, purchased_on=period.start_date)
        with self.assertNumQueries(len(ctx.captured_queries)):
            self.client.get(self.url)

    def test_navigation_link_is_on_every_page(self):
        period = Period.objects.create(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), budget=1000)
        for url in [reverse('budget:index'), period.get_absolute_url(), reverse('budget:period_create')]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url, follow=True), f'href="{self.url}"')

    def test_detail_page_shows_timing_tag(self):
        past = Period.objects.create(start_date=date(2020, 1, 1), end_date=date(2020, 1, 31), budget=1000)
        self.assertContains(self.client.get(past.get_absolute_url()), 'timing-past')
