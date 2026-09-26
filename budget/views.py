from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ExpenseForm, PeriodForm
from .models import WARNING_THRESHOLD_PERCENT, Expense, Period


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
    return render(request, 'budget/period_detail.html', {
        'period': period,
        'periods': Period.objects.all(),
        'summary': period.summary(),
        'expenses': period.expenses.all(),
        'form': form,
        'editing_expense': editing_expense,
        'warning_threshold': WARNING_THRESHOLD_PERCENT,
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


@require_POST
def expense_delete(request, pk):
    """F-05: 支出の削除"""
    expense = get_object_or_404(Expense.objects.select_related('period'), pk=pk)
    period = expense.period
    expense.delete()
    messages.success(request, f'「{expense.name}」を削除しました。')
    return redirect(period)
