from django.db import connection
from django.test import TestCase


class DatabaseConnectionTests(TestCase):
    """開発環境のセットアップ確認用。MySQL に接続できていることを確かめる。"""

    def test_uses_mysql(self):
        self.assertEqual(connection.vendor, 'mysql')

    def test_can_query_database(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            self.assertEqual(cursor.fetchone(), (1,))
