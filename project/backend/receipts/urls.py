from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_receipt, name='upload_receipt'),
    path('validate/', views.validate_receipt, name='validate_receipt'),
    path('process/', views.process_receipt, name='process_receipt'),
    path('receipts/', views.list_receipts, name='list_receipts'),
    path('receipts/<int:receipt_id>/', views.get_receipt, name='get_receipt'),
    path('receipt-files/', views.list_receipt_files, name='list_receipt_files'),
    path('health/', views.health_check, name='health_check'),
]