"""A-03: データのバックアップ(CSVファイルへの書き出し・読み込み)

1つのCSVファイルに「カテゴリ」「期間」「支出」の3種類の行をまとめて保存する。

    種別,開始日,締め日,上限金額,購入日,品名,金額,カテゴリ,色
    カテゴリ,,,,,,,食費,#3b82f6
    期間,2026-09-25,2026-10-24,50000,,,,,
    支出,,,,2026-09-25,スーパーで食料品,12800,食費,

- 書き出すファイルは Excel で開いても文字化けしないよう、UTF-8(BOM付き)にする
- 読み込むと、現在のデータをすべて削除してファイルの内容に置き換える。
  ファイルに1か所でも誤りがあれば、何も変更しない(トランザクションで元に戻す)
- Excel で開いて保存し直したファイル(Shift_JIS、日付が 2026/9/25 形式、金額が 12,800 形式)も読み込める
"""
import csv
import io
from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Category, Expense, Period

HEADER = ['種別', '開始日', '締め日', '上限金額', '購入日', '品名', '金額', 'カテゴリ', '色']
TYPE_CATEGORY = 'カテゴリ'
TYPE_PERIOD = '期間'
TYPE_EXPENSE = '支出'

MAX_ERRORS = 20

# Excel で開いたときに数式として実行されないよう、これらの文字で始まる文字列は先頭に ' を付けて書き出す
# (読み込むときに取り除く)
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _escape(value):
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def _unescape(value):
    return value[1:] if value.startswith("'") and value[1:].startswith(FORMULA_PREFIXES) else value


# ===== 書き出し =====

def export_csv():
    """すべてのデータをCSV形式の文字列にして返す"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\r\n')
    writer.writerow(HEADER)
    # 読み込み直したときに同じ順番(色の割り当て順・同じ日の支出の並び順)になるよう、作成順に書き出す
    for category in Category.objects.order_by('created_at', 'pk'):
        writer.writerow([TYPE_CATEGORY, '', '', '', '', '', '', _escape(category.name), category.color])
    for period in Period.objects.order_by('start_date'):
        writer.writerow([TYPE_PERIOD, period.start_date.isoformat(), period.end_date.isoformat(), period.budget,
                         '', '', '', '', ''])
    for expense in Expense.objects.select_related('category').order_by('purchased_on', 'created_at', 'pk'):
        writer.writerow([TYPE_EXPENSE, '', '', '', expense.purchased_on.isoformat(), _escape(expense.name),
                         expense.amount, _escape(expense.category.name) if expense.category else '', ''])
    return buffer.getvalue()


def export_bytes():
    """ダウンロード用のバイト列(Excel で文字化けしないよう BOM 付きの UTF-8)"""
    return export_csv().encode('utf-8-sig')


# ===== 読み込み =====

class BackupError(Exception):
    """読み込めなかった理由(行番号付きのメッセージの一覧)"""

    def __init__(self, errors):
        super().__init__('\n'.join(errors))
        self.errors = errors


@dataclass(frozen=True)
class ImportResult:
    categories: int
    periods: int
    expenses: int


def _decode(data):
    # UTF-8(BOM の有無どちらも)で読めなければ、Excel が保存する Shift_JIS(cp932)として読む
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BackupError(['ファイルの文字コードを判別できませんでした(UTF-8 または Shift_JIS のCSVファイルを選んでください)。'])


def _parse_date(value, label):
    value = value.strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'{label}「{value}」は日付として読み取れません(例: 2026-09-25)。')


def _parse_int(value, label):
    cleaned = value.strip().replace(',', '').replace('¥', '').replace('￥', '')
    if not cleaned.isdigit():
        raise ValueError(f'{label}「{value}」は整数として読み取れません。')
    return int(cleaned)


def _messages(error):
    """ValidationError を、画面に表示する文字列の一覧にする"""
    if hasattr(error, 'message_dict'):
        return [message for messages in error.message_dict.values() for message in messages]
    return list(error.messages)


def import_bytes(data):
    """CSVファイルの内容でデータを置き換える。誤りがあれば BackupError を送出し、何も変更しない"""
    rows = list(csv.reader(io.StringIO(_decode(data))))
    if not rows or [cell.strip() for cell in rows[0]] != HEADER:
        raise BackupError(['1行目(見出し)が正しくありません。このアプリで書き出したバックアップファイルを選んでください。'])

    errors = []

    def add_error(line_no, message):
        errors.append(f'{line_no}行目: {message}')

    # BackupError が送出されると transaction.atomic() が変更をすべて取り消す
    with transaction.atomic():
        Expense.objects.all().delete()
        Period.objects.all().delete()
        Category.objects.all().delete()

        periods = []
        counts = {TYPE_CATEGORY: 0, TYPE_PERIOD: 0, TYPE_EXPENSE: 0}
        # カテゴリ → 期間 → 支出 の順に登録する(支出がカテゴリ・期間を参照するため)
        for row_type in (TYPE_CATEGORY, TYPE_PERIOD, TYPE_EXPENSE):
            for line_no, row in enumerate(rows[1:], start=2):
                if len(errors) >= MAX_ERRORS:
                    break
                if not any(cell.strip() for cell in row):
                    continue  # 空行は読み飛ばす
                if len(row) != len(HEADER):
                    if row_type == TYPE_CATEGORY:  # 同じ行のエラーを重複して出さないよう、最初の1回だけ
                        add_error(line_no, f'列の数が{len(HEADER)}列ではありません。')
                    continue
                kind = row[0].strip()
                if kind not in counts:
                    if row_type == TYPE_CATEGORY:
                        add_error(line_no, f'種別「{kind}」は「カテゴリ」「期間」「支出」のいずれかにしてください。')
                    continue
                if kind != row_type:
                    continue
                try:
                    if kind == TYPE_CATEGORY:
                        _import_category(row)
                    elif kind == TYPE_PERIOD:
                        periods.append(_import_period(row))
                    else:
                        _import_expense(row, periods)
                    counts[kind] += 1
                except ValueError as e:
                    add_error(line_no, str(e))
                except ValidationError as e:
                    for message in _messages(e):
                        add_error(line_no, message)

        if errors:
            if len(errors) >= MAX_ERRORS:
                errors = errors[:MAX_ERRORS] + [f'(誤りが多いため、最初の{MAX_ERRORS}件のみ表示しています)']
            raise BackupError(errors)

    return ImportResult(
        categories=counts[TYPE_CATEGORY], periods=counts[TYPE_PERIOD], expenses=counts[TYPE_EXPENSE]
    )


def _import_category(row):
    category = Category(name=_unescape(row[7].strip()), color=row[8].strip())
    category.full_clean()
    category.save()


def _import_period(row):
    period = Period(
        start_date=_parse_date(row[1], '開始日'),
        end_date=_parse_date(row[2], '締め日'),
        budget=_parse_int(row[3], '上限金額'),
    )
    period.full_clean()  # 締め日 ≧ 開始日、既に読み込んだ期間との重複もここで確認する
    period.save()
    return period


def _import_expense(row, periods):
    purchased_on = _parse_date(row[4], '購入日')
    # 支出がどの期間に属するかは購入日で判定する
    period = next((p for p in periods if p.contains(purchased_on)), None)
    if period is None:
        raise ValueError(f'購入日 {purchased_on:%Y/%m/%d} を含む期間がありません。')
    category_name = _unescape(row[7].strip())
    expense = Expense(
        period=period,
        name=_unescape(row[5].strip()),
        amount=_parse_int(row[6], '金額'),
        purchased_on=purchased_on,
        category=_find_or_create_category(category_name) if category_name else None,
    )
    expense.full_clean()
    expense.save()


def _find_or_create_category(name):
    """支出の行にある、カテゴリの行で定義されていないカテゴリは、次の色を割り当てて作成する"""
    category = Category.objects.filter(name=name).first()
    if category is None:
        # 保存する前に入力チェックをする(長すぎる名前などで DB のエラーにならないようにする)
        Category(name=name, color='#000000').full_clean()
        category = Category.get_or_create_by_name(name)
    return category


def filename():
    """ダウンロードするファイルの名前(例: kakeibo-backup-20260927-153000.csv)"""
    return f'kakeibo-backup-{timezone.localtime():%Y%m%d-%H%M%S}.csv'
