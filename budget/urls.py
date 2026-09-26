from django.urls import path

from . import views

app_name = 'budget'

urlpatterns = [
    path('', views.index, name='index'),
    path('periods/new/', views.period_create, name='period_create'),
    path('periods/<int:pk>/', views.period_detail, name='period_detail'),
    path('periods/<int:pk>/edit/', views.period_edit, name='period_edit'),
    path('expenses/<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('expenses/<int:pk>/delete/', views.expense_delete, name='expense_delete'),
]
