from django.contrib import admin
from .models import ReceiptFile, Receipt, ReceiptItem


@admin.register(ReceiptFile)
class ReceiptFileAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'is_valid', 'is_processed', 'created_at']
    list_filter = ['is_valid', 'is_processed', 'created_at']
    search_fields = ['file_name']
    readonly_fields = ['created_at', 'updated_at']


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['merchant_name', 'total_amount', 'purchased_at', 'created_at']
    list_filter = ['merchant_name', 'purchased_at', 'created_at']
    search_fields = ['merchant_name', 'receipt_number']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ReceiptItemInline]


@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ['item_name', 'quantity', 'unit_price', 'total_price', 'receipt']
    list_filter = ['receipt__merchant_name', 'created_at']
    search_fields = ['item_name']