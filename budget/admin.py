from django.contrib import admin

from .models import Category, Expense, Period


class ExpenseInline(admin.TabularInline):
    model = Expense
    extra = 0
    fields = ['purchased_on', 'name', 'category', 'amount']


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'budget', 'spent_amount', 'remaining_amount', 'status']
    inlines = [ExpenseInline]

    @admin.display(description='使用済み金額')
    def spent_amount(self, obj):
        return obj.spent_amount

    @admin.display(description='残り金額')
    def remaining_amount(self, obj):
        return obj.remaining_amount

    @admin.display(description='状態')
    def status(self, obj):
        return obj.status.label


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'color', 'created_at']
    search_fields = ['name']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['purchased_on', 'name', 'category', 'amount', 'period']
    list_filter = ['period', 'category']
    search_fields = ['name']
