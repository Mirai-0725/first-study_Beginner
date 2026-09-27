from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from . import backup
from .models import Category, Expense, Period

HEADER = '種別,開始日,締め日,上限金額,購入日,品名,金額,カテゴリ,色'


def csv_bytes(*lines, encoding='utf-8'):
    return '\r\n'.join([HEADER, *lines]).encode(encoding)


def snapshot():
    """比較用: 現在のデータの内容(ID や作成日時は除く)"""
    return {
        'categories': [(c.name, c.color) for c in Category.objects.order_by('created_at', 'pk')],
        'periods': [(p.start_date, p.end_date, p.budget) for p in Period.objects.order_by('start_date')],
        'expenses': [
            (e.period.start_date, e.purchased_on, e.name, e.amount, e.category.name if e.category else None)
            for e in Expense.objects.select_related('period', 'category').order_by('purchased_on', 'created_at', 'pk')
        ],
    }


class BackupTestData(TestCase):
    def setUp(self):
        self.food = Category.get_or_create_by_name('食費')
        self.daily = Category.get_or_create_by_name('日用品')
        self.p1 = Period.objects.create(start_date=date(2026, 8, 25), end_date=date(2026, 9, 24), budget=50000)
        self.p2 = Period.objects.create(start_date=date(2026, 9, 25), end_date=date(2026, 10, 24), budget=40000)
        for period, name, amount, day, category in [
            (self.p1, '外食', 9000, date(2026, 8, 31), self.food),
            (self.p2, 'スーパー, 食料品', 12800, date(2026, 9, 25), self.food),  # カンマを含む品名
            (self.p2, 'ティッシュ "箱"', 398, date(2026, 9, 26), self.daily),  # ダブルクォートを含む品名
            (self.p2, '-割引の反映', 100, date(2026, 9, 26), None),  # 数式と誤解される文字で始まる品名
        ]:
            Expense.objects.create(period=period, name=name, amount=amount, purchased_on=day, category=category)
        Period.objects.create(start_date=date(2026, 10, 25), end_date=date(2026, 11, 24), budget=30000)  # 支出なし


class ExportTests(BackupTestData):
    def test_export_contains_all_data(self):
        lines = backup.export_csv().splitlines()
        self.assertEqual(lines[0], HEADER)
        self.assertEqual(lines[1], 'カテゴリ,,,,,,,食費,' + self.food.color)
        self.assertIn('期間,2026-08-25,2026-09-24,50000,,,,,', lines)
        self.assertIn('支出,,,,2026-09-25,"スーパー, 食料品",12800,食費,', lines)
        self.assertIn('支出,,,,2026-09-26,"ティッシュ ""箱""",398,日用品,', lines)
        self.assertEqual(len(lines), 1 + 2 + 3 + 4)

    def test_text_starting_with_formula_characters_is_escaped(self):
        # Excel で開いたときに数式として実行されないよう、先頭に ' を付ける
        self.assertIn("支出,,,,2026-09-26,'-割引の反映,100,,", backup.export_csv().splitlines())

    def test_download_has_bom_and_filename(self):
        response = self.client.get(reverse('budget:backup_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))  # BOM(Excel の文字化け対策)
        self.assertRegex(response['Content-Disposition'], r'attachment; filename="kakeibo-backup-\d{8}-\d{6}\.csv"')


class RoundTripTests(BackupTestData):
    def test_import_restores_exported_data(self):
        before = snapshot()
        data = backup.export_bytes()
        # 書き出した後にデータを変更・追加しても、読み込むと書き出した時点の状態に戻る
        Expense.objects.all().delete()
        Category.get_or_create_by_name('追加したカテゴリ')
        Period.objects.create(start_date=date(2027, 1, 1), end_date=date(2027, 1, 31), budget=1)

        result = backup.import_bytes(data)
        self.assertEqual((result.categories, result.periods, result.expenses), (2, 3, 4))
        self.assertEqual(snapshot(), before)
        # 読み込んだ後も、同じ内容を書き出せる
        self.assertEqual(backup.export_bytes(), data)


class ImportTests(TestCase):
    def test_excel_style_file_can_be_imported(self):
        # Excel で保存し直したファイル: Shift_JIS、BOMなし、日付は 2026/9/25 形式、金額は 12,800 形式
        data = csv_bytes(
            '期間,2026/9/25,2026/10/24,"50,000",,,,,',
            '支出,,,,2026/9/25,スーパー,"12,800",食費,',
            encoding='cp932',
        )
        result = backup.import_bytes(data)
        self.assertEqual((result.periods, result.expenses), (1, 1))
        expense = Expense.objects.get()
        self.assertEqual((expense.name, expense.amount, expense.purchased_on), ('スーパー', 12800, date(2026, 9, 25)))
        # カテゴリの行がないカテゴリは、自動で作成される
        self.assertEqual(expense.category.name, '食費')

    def test_blank_lines_are_ignored(self):
        backup.import_bytes(csv_bytes('', '期間,2026-09-25,2026-10-24,50000,,,,,', ',,,,,,,,'))
        self.assertEqual(Period.objects.count(), 1)

    def test_invalid_rows_are_reported_and_nothing_changes(self):
        Period.objects.create(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), budget=1000)
        before = snapshot()
        cases = {
            '種別': ['不明,,,,,,,,'],
            '列の数': ['期間,2026-09-25,2026-10-24,50000'],
            '日付として読み取れません': ['期間,2026-13-01,2026-10-24,50000,,,,,'],
            '整数として読み取れません': ['期間,2026-09-25,2026-10-24,abc,,,,,'],
            '締め日は開始日以降': ['期間,2026-10-24,2026-09-25,50000,,,,,'],
            '日付が重なっています': ['期間,2026-09-01,2026-09-30,1,,,,,', '期間,2026-09-15,2026-10-15,1,,,,,'],
            '含む期間がありません': ['期間,2026-09-01,2026-09-30,1,,,,,', '支出,,,,2026-10-01,A,1,,'],
            '1 以上': ['期間,2026-09-01,2026-09-30,1,,,,,', '支出,,,,2026-09-01,A,0,,'],
            '#RRGGBB': ['カテゴリ,,,,,,,食費,red'],
            '20 文字以下': ['期間,2026-09-01,2026-09-30,1,,,,,', '支出,,,,2026-09-01,A,1,' + 'あ' * 21 + ','],
        }
        for expected, lines in cases.items():
            with self.subTest(expected=expected):
                with self.assertRaises(backup.BackupError) as cm:
                    backup.import_bytes(csv_bytes(*lines))
                self.assertIn(expected, '\n'.join(cm.exception.errors))
                self.assertEqual(snapshot(), before)  # 既存のデータは変わらない

    def test_error_message_has_line_number(self):
        with self.assertRaises(backup.BackupError) as cm:
            backup.import_bytes(csv_bytes('期間,2026-09-25,2026-10-24,50000,,,,,', '支出,,,,2026-09-25,A,-5,,'))
        self.assertTrue(cm.exception.errors[0].startswith('3行目:'))

    def test_wrong_header_is_rejected(self):
        with self.assertRaises(backup.BackupError) as cm:
            backup.import_bytes('name,amount\r\n牛乳,250'.encode())
        self.assertIn('見出し', cm.exception.errors[0])

    def test_empty_file_is_rejected(self):
        with self.assertRaises(backup.BackupError):
            backup.import_bytes(b'')

    def test_too_many_errors_are_truncated(self):
        with self.assertRaises(backup.BackupError) as cm:
            backup.import_bytes(csv_bytes(*['不明,,,,,,,,'] * 50))
        self.assertEqual(len(cm.exception.errors), backup.MAX_ERRORS + 1)


class BackupViewTests(BackupTestData):
    def upload(self, data, confirm=True):
        payload = {'file': SimpleUploadedFile('backup.csv', data, content_type='text/csv')}
        if confirm:
            payload['confirm'] = 'on'
        return self.client.post(reverse('budget:backup_import'), payload)

    def test_page_shows_counts_and_links(self):
        response = self.client.get(reverse('budget:backup'))
        self.assertContains(response, 'カテゴリ 2件・期間 3件・支出 4件')
        self.assertContains(response, reverse('budget:backup_export'))
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_import_replaces_data_and_redirects(self):
        data = csv_bytes('期間,2027-01-01,2027-01-31,1000,,,,,', '支出,,,,2027-01-05,本,500,趣味,')
        response = self.upload(data)
        self.assertRedirects(response, reverse('budget:index'), fetch_redirect_response=False)
        self.assertEqual(Period.objects.count(), 1)
        self.assertEqual(list(Expense.objects.values_list('name', flat=True)), ['本'])
        self.assertEqual(list(Category.objects.values_list('name', flat=True)), ['趣味'])
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertIn('バックアップを読み込みました(カテゴリ 0件・期間 1件・支出 1件)。', messages)

    def test_confirmation_is_required(self):
        before = snapshot()
        response = self.upload(csv_bytes('期間,2027-01-01,2027-01-31,1000,,,,,'), confirm=False)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '確認のチェックを入れてください', status_code=400)
        self.assertEqual(snapshot(), before)

    def test_invalid_file_shows_errors_and_keeps_data(self):
        before = snapshot()
        response = self.upload(csv_bytes('期間,2027-01-31,2027-01-01,1000,,,,,'))
        self.assertContains(response, 'データは変更していません', status_code=400)
        self.assertContains(response, '2行目: 締め日は開始日以降の日付にしてください。', status_code=400)
        self.assertEqual(snapshot(), before)

    def test_import_requires_post(self):
        self.assertEqual(self.client.get(reverse('budget:backup_import')).status_code, 405)
