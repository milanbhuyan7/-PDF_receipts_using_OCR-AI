from rest_framework import serializers
from .models import ReceiptFile, Receipt, ReceiptItem


class ReceiptItemSerializer(serializers.ModelSerializer):
    """Serializer for receipt items."""
    
    class Meta:
        model = ReceiptItem
        fields = ['id', 'item_name', 'quantity', 'unit_price', 'total_price']


class ReceiptSerializer(serializers.ModelSerializer):
    """Serializer for receipts."""
    
    items = ReceiptItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = Receipt
        fields = [
            'id', 'purchased_at', 'merchant_name', 'total_amount',
            'subtotal', 'tax_amount', 'tip_amount', 'payment_method',
            'receipt_number', 'cashier', 'raw_text', 'file_path',
            'items', 'created_at', 'updated_at'
        ]


class ReceiptFileSerializer(serializers.ModelSerializer):
    """Serializer for receipt files."""
    
    receipts = ReceiptSerializer(many=True, read_only=True)
    
    class Meta:
        model = ReceiptFile
        fields = [
            'id', 'file_name', 'file_path', 'is_valid', 'invalid_reason',
            'is_processed', 'created_at', 'updated_at', 'receipts'
        ]


class FileUploadSerializer(serializers.Serializer):
    """Serializer for file uploads."""
    
    file = serializers.FileField()
    
    def validate_file(self, value):
        """Validate that the uploaded file is a PDF."""
        if not value.name.lower().endswith('.pdf'):
            raise serializers.ValidationError("Only PDF files are allowed.")
        
        # Check file size (10MB limit)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File size cannot exceed 10MB.")
        
        return value