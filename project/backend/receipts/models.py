from django.db import models
from django.utils import timezone


class ReceiptFile(models.Model):
    """Model for storing receipt file metadata."""
    
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    is_valid = models.BooleanField(default=False)
    invalid_reason = models.TextField(blank=True, null=True)
    is_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'receipt_file'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.file_name


class Receipt(models.Model):
    """Model for storing extracted receipt information."""
    
    purchased_at = models.DateTimeField(null=True, blank=True)
    merchant_name = models.CharField(max_length=255, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    file_path = models.CharField(max_length=500)
    
    # Additional fields for comprehensive receipt data
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tip_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    receipt_number = models.CharField(max_length=100, blank=True)
    cashier = models.CharField(max_length=100, blank=True)
    
    # Raw extracted text for reference
    raw_text = models.TextField(blank=True)
    
    # Relationship to receipt file
    receipt_file = models.ForeignKey(
        ReceiptFile, 
        on_delete=models.CASCADE, 
        related_name='receipts',
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'receipt'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.merchant_name} - ${self.total_amount}"


class ReceiptItem(models.Model):
    """Model for storing individual receipt items."""
    
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='items')
    item_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'receipt_item'
        ordering = ['id']
    
    def __str__(self):
        return f"{self.item_name} - ${self.total_price}"