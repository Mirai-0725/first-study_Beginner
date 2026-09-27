from django import forms
from django.utils import timezone

from .models import Category, Expense, Period


class DateInput(forms.DateInput):
    """ブラウザの日付選択(<input type="date">)を使う入力欄"""

    input_type = 'date'

    def __init__(self, attrs=None):
        # type="date" は YYYY-MM-DD 形式の値しか表示できないため、形式を固定する
        super().__init__(attrs=attrs, format='%Y-%m-%d')


class PeriodForm(forms.ModelForm):
    """F-01, F-02: 期間(開始日・締め日・上限金額)の作成・編集"""

    class Meta:
        model = Period
        fields = ['start_date', 'end_date', 'budget']
        labels = {'budget': '上限金額(円)'}
        widgets = {
            'start_date': DateInput(),
            'end_date': DateInput(),
            'budget': forms.NumberInput(attrs={'min': 1, 'step': 1, 'placeholder': '例: 50000'}),
        }


class ExpenseForm(forms.ModelForm):
    """F-03, F-05, W-04: 支出(品名・カテゴリ・金額・購入日)の登録・編集"""

    # W-04: カテゴリは名前で入力する。初めて使う名前なら保存時にカテゴリを作成する
    # (入力候補は画面の <datalist id="category-options"> で表示する)
    category_name = forms.CharField(
        label='カテゴリ(任意)',
        max_length=Category._meta.get_field('name').max_length,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': '例: 食費',
            'autocomplete': 'off',
            'list': 'category-options',
        }),
    )

    field_order = ['name', 'category_name', 'amount', 'purchased_on']

    class Meta:
        model = Expense
        fields = ['name', 'amount', 'purchased_on']
        labels = {'amount': '金額(円)'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': '例: 牛乳', 'autocomplete': 'off'}),
            'amount': forms.NumberInput(attrs={'min': 1, 'step': 1, 'placeholder': '例: 250'}),
            'purchased_on': DateInput(),
        }

    def __init__(self, *args, period, **kwargs):
        # 新規登録のときは、選択中の期間に紐付けた支出として検証する
        if kwargs.get('instance') is None:
            kwargs['instance'] = Expense(period=period)
        super().__init__(*args, **kwargs)

        # 編集のときは、現在のカテゴリ名を入力欄に表示する
        if not self.is_bound and self.instance.category_id:
            self.initial['category_name'] = self.instance.category.name

        # 購入日は選択中の期間内に限る(ブラウザの日付選択でも範囲外を選べないようにする)
        self.fields['purchased_on'].widget.attrs.update(
            min=period.start_date.isoformat(),
            max=period.end_date.isoformat(),
        )

        # 購入日の初期値は当日。当日が期間外の場合は期間の開始日
        if not self.is_bound and self.instance.pk is None:
            today = timezone.localdate()
            self.initial['purchased_on'] = today if period.contains(today) else period.start_date

    def save(self, commit=True):
        name = self.cleaned_data['category_name']  # CharField が前後の空白を取り除いている
        self.instance.category = Category.get_or_create_by_name(name) if name else None
        return super().save(commit=commit)
