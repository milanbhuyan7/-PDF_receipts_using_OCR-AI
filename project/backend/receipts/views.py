import os
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.http import Http404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from .models import ReceiptFile, Receipt, ReceiptItem
from .serializers import ReceiptFileSerializer, ReceiptSerializer, FileUploadSerializer
from .utils import validate_pdf, extract_text_from_pdf, parse_receipt_text

logger = logging.getLogger(__name__)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def upload_receipt(request):
    """Upload a receipt file (PDF format only)."""
    try:
        serializer = FileUploadSerializer(data=request.data)
        if serializer.is_valid():
            uploaded_file = serializer.validated_data['file']
            
            # Create unique filename to avoid conflicts
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{uploaded_file.name}"
            file_path = default_storage.save(f'receipts/{filename}', ContentFile(uploaded_file.read()))
            
            # Create receipt file record
            receipt_file = ReceiptFile.objects.create(
                file_name=uploaded_file.name,
                file_path=file_path,
                is_valid=False,
                is_processed=False
            )
            
            return Response({
                'message': 'File uploaded successfully',
                'file_id': receipt_file.id,
                'file_name': receipt_file.file_name
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return Response({
            'error': 'Failed to upload file',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def validate_receipt(request):
    """Validate whether the uploaded file is a valid PDF."""
    try:
        file_id = request.data.get('file_id')
        if not file_id:
            return Response({
                'error': 'file_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            receipt_file = ReceiptFile.objects.get(id=file_id)
        except ReceiptFile.DoesNotExist:
            return Response({
                'error': 'Receipt file not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Validate PDF
        full_path = os.path.join(settings.MEDIA_ROOT, receipt_file.file_path)
        is_valid, error_message = validate_pdf(full_path)
        
        # Update receipt file record
        receipt_file.is_valid = is_valid
        receipt_file.invalid_reason = error_message if not is_valid else None
        receipt_file.save()
        
        return Response({
            'file_id': receipt_file.id,
            'is_valid': is_valid,
            'message': 'PDF is valid' if is_valid else f'PDF is invalid: {error_message}'
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error validating file: {str(e)}")
        return Response({
            'error': 'Failed to validate file',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def process_receipt(request):
    """Extract receipt details using OCR/AI."""
    try:
        file_id = request.data.get('file_id')
        if not file_id:
            return Response({
                'error': 'file_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            receipt_file = ReceiptFile.objects.get(id=file_id)
        except ReceiptFile.DoesNotExist:
            return Response({
                'error': 'Receipt file not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        if not receipt_file.is_valid:
            return Response({
                'error': 'File is not valid for processing',
                'reason': receipt_file.invalid_reason
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Extract text from PDF
        full_path = os.path.join(settings.MEDIA_ROOT, receipt_file.file_path)
        extracted_text = extract_text_from_pdf(full_path)
        
        if not extracted_text:
            return Response({
                'error': 'Failed to extract text from PDF'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Parse receipt information
        receipt_data = parse_receipt_text(extracted_text)
        
        # Create receipt record
        receipt = Receipt.objects.create(
            purchased_at=receipt_data.get('purchased_at'),
            merchant_name=receipt_data.get('merchant_name', ''),
            total_amount=receipt_data.get('total_amount'),
            subtotal=receipt_data.get('subtotal'),
            tax_amount=receipt_data.get('tax_amount'),
            tip_amount=receipt_data.get('tip_amount'),
            payment_method=receipt_data.get('payment_method', ''),
            receipt_number=receipt_data.get('receipt_number', ''),
            cashier=receipt_data.get('cashier', ''),
            raw_text=extracted_text,
            file_path=receipt_file.file_path,
            receipt_file=receipt_file
        )
        
        # Create receipt items
        for item_data in receipt_data.get('items', []):
            ReceiptItem.objects.create(
                receipt=receipt,
                item_name=item_data.get('name', ''),
                quantity=item_data.get('quantity', 1),
                unit_price=item_data.get('unit_price'),
                total_price=item_data.get('total_price')
            )
        
        # Mark as processed
        receipt_file.is_processed = True
        receipt_file.save()
        
        # Serialize and return the receipt
        serializer = ReceiptSerializer(receipt)
        return Response({
            'message': 'Receipt processed successfully',
            'receipt': serializer.data
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error processing receipt: {str(e)}")
        return Response({
            'error': 'Failed to process receipt',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def list_receipts(request):
    """List all receipts stored in the database."""
    try:
        receipts = Receipt.objects.all()
        serializer = ReceiptSerializer(receipts, many=True)
        return Response({
            'receipts': serializer.data,
            'count': len(serializer.data)
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error listing receipts: {str(e)}")
        return Response({
            'error': 'Failed to list receipts',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_receipt(request, receipt_id):
    """Retrieve details of a specific receipt by its ID."""
    try:
        try:
            receipt = Receipt.objects.get(id=receipt_id)
        except Receipt.DoesNotExist:
            return Response({
                'error': 'Receipt not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = ReceiptSerializer(receipt)
        return Response({
            'receipt': serializer.data
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error retrieving receipt: {str(e)}")
        return Response({
            'error': 'Failed to retrieve receipt',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def list_receipt_files(request):
    """List all receipt files."""
    try:
        receipt_files = ReceiptFile.objects.all()
        serializer = ReceiptFileSerializer(receipt_files, many=True)
        return Response({
            'receipt_files': serializer.data,
            'count': len(serializer.data)
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error listing receipt files: {str(e)}")
        return Response({
            'error': 'Failed to list receipt files',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def health_check(request):
    """Health check endpoint."""
    return Response({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }, status=status.HTTP_200_OK)