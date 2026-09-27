from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import backup, sorting
from .forms import BackupImportForm, ExpenseForm, PeriodForm
from .models import WARNING_THRESHOLD_PERCENT, BudgetSummary, Category, Expense, Period

# W-04: 支出の入力欄の下に、ボタンとして表示するカテゴリの数
FREQUENT_CATEGORY_COUNT = 8


def index(request):
    """トップ画面。表示する期間を選んで、その期間の画面へ移動する"""
    # 期間のプルダウンで選ばれた場合
    selected = request.GET.get('period', '')
    if selected.isdigit():
        return redirect('budget:period_detail', pk=int(selected))

    # 今日を含む期間があればそれを、なければ開始日が最も新しい期間を表示する
    today = timezone.localdate()
    period = (
        Period.objects.filter(start_date__lte=today, end_date__gte=today).first()
        or Period.objects.first()
    )
    if period is None:
        return render(request, 'budget/empty.html')
    return redirect(period)


def _render_period_page(request, period, form, editing_expense=None):
    """メイン画面(予算状況・支出の入力・支出の一覧)を表示する"""
    categories = Category.objects.annotate(usage_count=Count('expenses'))
    sort, order = sorting.get_sort(request)
    return render(request, 'budget/period_detail.html', {
        'period': period,
        'periods': Period.objects.all(),
        'summary': period.summary(),
        'segments': period.category_segments(),
        'expenses': period.expenses.select_related('category').order_by(*sorting.order_by_args(sort, order)),
        'sort_headers': sorting.sort_headers(sort, order),
        'timing': period.timing(),
        'form': form,
        'editing_expense': editing_expense,
        'warning_threshold': WARNING_THRESHOLD_PERCENT,
        # W-04: 入力候補(すべてのカテゴリ)と、よく使うカテゴリのボタン(使用回数の多い順)
        'categories': categories.order_by('name'),
        'frequent_categories': categories.order_by('-usage_count', 'name')[:FREQUENT_CATEGORY_COUNT],
    })


def period_detail(request, pk):
    """F-03, F-04, F-06, F-07: メイン画面。POST のときは支出を登録する"""
    period = get_object_or_404(Period, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, period=period)
        if form.is_valid():
            expense = form.save()
            messages.success(request, f'「{expense.name}」を登録しました。')
            return redirect(period)
    else:
        form = ExpenseForm(period=period)
    return _render_period_page(request, period, form)


def period_list(request):
    """W-01: 期間の一覧。すべての期間の予算状況を見比べ、過去の期間も開けるようにする"""
    today = timezone.localdate()
    # 使用済み金額は期間ごとに1回の問い合わせでまとめて集計する(支出がない期間は 0)。
    # 集計を含む問い合わせではモデルの既定の並び順が使われないため、並び順を明示する
    periods = Period.objects.annotate(spent=Coalesce(Sum('expenses__amount'), 0)).order_by('-start_date')
    rows = [
        {
            'period': period,
            'summary': BudgetSummary(budget=period.budget, spent=period.spent),
            'timing': period.timing(today),
        }
        for period in periods
    ]
    return render(request, 'budget/period_list.html', {'rows': rows})


def period_create(request):
    """F-01, F-02: 期間の作成"""
    form = PeriodForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        period = form.save()
        messages.success(request, f'期間({period})を作成しました。')
        return redirect(period)
    return render(request, 'budget/period_form.html', {'form': form, 'period': None})


def period_edit(request, pk):
    """F-01, F-02: 期間の編集"""
    period = get_object_or_404(Period, pk=pk)
    form = PeriodForm(request.POST or None, instance=period)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '期間を更新しました。')
        return redirect(period)
    return render(request, 'budget/period_form.html', {'form': form, 'period': period})


def expense_edit(request, pk):
    """F-05: 支出の編集。メイン画面の入力欄を編集モードにして表示する"""
    expense = get_object_or_404(Expense.objects.select_related('period'), pk=pk)
    period = expense.period
    form = ExpenseForm(request.POST or None, instance=expense, period=period)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'「{expense.name}」を更新しました。')
        return redirect(period)
    return _render_period_page(request, period, form, editing_expense=expense)


def backup_page(request, form=None, errors=None, status=200):
    """A-03: バックアップ画面(書き出し・読み込み)"""
    return render(request, 'budget/backup.html', {
        'form': form or BackupImportForm(),
        'errors': errors or [],
        'counts': {
            'categories': Category.objects.count(),
            'periods': Period.objects.count(),
            'expenses': Expense.objects.count(),
        },
    }, status=status)


def backup_export(request):
    """A-03: すべてのデータをCSVファイルとしてダウンロードする"""
    response = HttpResponse(backup.export_bytes(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{backup.filename()}"'
    return response


@require_POST
def backup_import(request):
    """A-03: CSVファイルを読み込み、現在のデータを置き換える"""
    form = BackupImportForm(request.POST, request.FILES)
    if not form.is_valid():
        return backup_page(request, form=form, status=400)
    try:
        result = backup.import_bytes(form.cleaned_data['file'].read())
    except backup.BackupError as e:
        return backup_page(request, form=form, errors=e.errors, status=400)
    messages.success(
        request,
        f'バックアップを読み込みました(カテゴリ {result.categories}件・期間 {result.periods}件・支出 {result.expenses}件)。',
    )
    return redirect('budget:index')


@require_POST
def expense_delete(request, pk):
    """F-05: 支出の削除"""
    expense = get_object_or_404(Expense.objects.select_related('period'), pk=pk)
    period = expense.period
    expense.delete()
    messages.success(request, f'「{expense.name}」を削除しました。')
    return redirect(period)
