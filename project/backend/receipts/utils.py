import os
import re
import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger(__name__)

# Configure Gemini API
genai.configure(api_key=settings.GEMINI_API_KEY)


def validate_pdf(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if a file is a valid PDF.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if not os.path.exists(file_path):
            return False, "File does not exist"
        
        if not file_path.lower().endswith('.pdf'):
            return False, "File is not a PDF"
        
        # Try to convert first page to check if it's a valid PDF
        try:
            images = convert_from_path(file_path, first_page=1, last_page=1)
            if not images:
                return False, "PDF contains no readable pages"
        except Exception as e:
            return False, f"Invalid PDF format: {str(e)}"
        
        return True, None
    
    except Exception as e:
        logger.error(f"Error validating PDF: {str(e)}")
        return False, f"Validation error: {str(e)}"


def extract_text_from_pdf(file_path: str) -> Optional[str]:
    """
    Extract text from a PDF file using OCR.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text or None if extraction fails
    """
    try:
        # Convert PDF to images
        images = convert_from_path(file_path, dpi=300)
        
        all_text = []
        for i, image in enumerate(images):
            try:
                # Use OCR to extract text from image
                text = pytesseract.image_to_string(image, config='--psm 6')
                all_text.append(text)
                logger.info(f"Extracted text from page {i+1}")
            except Exception as e:
                logger.error(f"Error extracting text from page {i+1}: {str(e)}")
                continue
        
        return '\n'.join(all_text) if all_text else None
    
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return None


def parse_receipt_with_gemini(raw_text: str) -> Dict:
    """
    Parse receipt text using Gemini AI to extract structured information.
    
    Args:
        raw_text: Raw OCR text from receipt
        
    Returns:
        Dictionary containing parsed receipt data
    """
    try:
        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-pro')
        
        # Create a detailed prompt for receipt parsing
        prompt = f"""
        You are an expert receipt parser. Analyze the following receipt text and extract structured information.
        Return ONLY a valid JSON object with the following structure (no additional text or formatting):

        {{
            "merchant_name": "string - name of the store/restaurant",
            "purchased_at": "string - date and time in ISO format (YYYY-MM-DDTHH:MM:SS) or null if not found",
            "total_amount": "number - total amount as decimal or null if not found",
            "subtotal": "number - subtotal amount as decimal or null if not found",
            "tax_amount": "number - tax amount as decimal or null if not found",
            "tip_amount": "number - tip amount as decimal or null if not found",
            "payment_method": "string - payment method (CASH, CREDIT, DEBIT, etc.) or empty string",
            "receipt_number": "string - receipt/transaction number or empty string",
            "cashier": "string - cashier name or empty string",
            "items": [
                {{
                    "name": "string - item name",
                    "quantity": "number - quantity as decimal (default 1)",
                    "unit_price": "number - unit price as decimal or null",
                    "total_price": "number - total price as decimal or null"
                }}
            ]
        }}

        Important guidelines:
        - Extract ALL items purchased, not just a few examples
        - For amounts, use only numbers (no currency symbols)
        - For dates, convert to ISO format if possible
        - If information is not available, use null for numbers or empty string for text
        - Be very careful with decimal numbers - ensure they are valid
        - Look for common receipt patterns like "QTY", "PRICE", "TOTAL", etc.
        - Payment methods should be uppercase (CASH, CREDIT, DEBIT, VISA, MASTERCARD, etc.)

        Receipt text to analyze:
        {raw_text}
        """
        
        # Generate response from Gemini
        response = model.generate_content(prompt)
        
        if not response.text:
            logger.error("Empty response from Gemini API")
            return get_fallback_parsing(raw_text)
        
        # Clean the response text
        response_text = response.text.strip()
        
        # Remove any markdown formatting if present
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        response_text = response_text.strip()
        
        # Parse JSON response
        try:
            parsed_data = json.loads(response_text)
            
            # Validate and clean the parsed data
            cleaned_data = validate_and_clean_gemini_response(parsed_data)
            
            logger.info("Successfully parsed receipt with Gemini AI")
            return cleaned_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON response: {str(e)}")
            logger.error(f"Response text: {response_text}")
            return get_fallback_parsing(raw_text)
    
    except Exception as e:
        logger.error(f"Error using Gemini API: {str(e)}")
        return get_fallback_parsing(raw_text)


def validate_and_clean_gemini_response(data: Dict) -> Dict:
    """
    Validate and clean the Gemini API response data.
    
    Args:
        data: Raw data from Gemini API
        
    Returns:
        Cleaned and validated data
    """
    cleaned_data = {
        'merchant_name': '',
        'purchased_at': None,
        'total_amount': None,
        'subtotal': None,
        'tax_amount': None,
        'tip_amount': None,
        'payment_method': '',
        'receipt_number': '',
        'cashier': '',
        'items': []
    }
    
    # Clean string fields
    if data.get('merchant_name'):
        cleaned_data['merchant_name'] = str(data['merchant_name']).strip()
    
    if data.get('payment_method'):
        cleaned_data['payment_method'] = str(data['payment_method']).strip().upper()
    
    if data.get('receipt_number'):
        cleaned_data['receipt_number'] = str(data['receipt_number']).strip()
    
    if data.get('cashier'):
        cleaned_data['cashier'] = str(data['cashier']).strip()
    
    # Clean date field
    if data.get('purchased_at'):
        try:
            # Try to parse and validate the date
            date_str = str(data['purchased_at']).strip()
            if date_str and date_str.lower() != 'null':
                # Try to parse as ISO format
                parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                cleaned_data['purchased_at'] = parsed_date
        except (ValueError, TypeError):
            logger.warning(f"Invalid date format: {data.get('purchased_at')}")
    
    # Clean amount fields
    amount_fields = ['total_amount', 'subtotal', 'tax_amount', 'tip_amount']
    for field in amount_fields:
        if data.get(field) is not None:
            try:
                amount = float(data[field])
                if amount >= 0:  # Ensure non-negative amounts
                    cleaned_data[field] = Decimal(str(amount))
            except (ValueError, TypeError, InvalidOperation):
                logger.warning(f"Invalid amount for {field}: {data.get(field)}")
    
    # Clean items
    if data.get('items') and isinstance(data['items'], list):
        for item in data['items']:
            if isinstance(item, dict) and item.get('name'):
                cleaned_item = {
                    'name': str(item['name']).strip(),
                    'quantity': 1,
                    'unit_price': None,
                    'total_price': None
                }
                
                # Clean quantity
                if item.get('quantity') is not None:
                    try:
                        qty = float(item['quantity'])
                        if qty > 0:
                            cleaned_item['quantity'] = Decimal(str(qty))
                    except (ValueError, TypeError, InvalidOperation):
                        pass
                
                # Clean prices
                for price_field in ['unit_price', 'total_price']:
                    if item.get(price_field) is not None:
                        try:
                            price = float(item[price_field])
                            if price >= 0:
                                cleaned_item[price_field] = Decimal(str(price))
                        except (ValueError, TypeError, InvalidOperation):
                            pass
                
                cleaned_data['items'].append(cleaned_item)
    
    return cleaned_data


def get_fallback_parsing(text: str) -> Dict:
    """
    Fallback parsing method using regex patterns when Gemini API fails.
    
    Args:
        text: Raw OCR text from receipt
        
    Returns:
        Dictionary containing parsed receipt data
    """
    logger.info("Using fallback parsing method")
    
    receipt_data = {
        'merchant_name': '',
        'purchased_at': None,
        'total_amount': None,
        'subtotal': None,
        'tax_amount': None,
        'tip_amount': None,
        'payment_method': '',
        'receipt_number': '',
        'cashier': '',
        'items': []
    }
    
    try:
        lines = text.strip().split('\n')
        lines = [line.strip() for line in lines if line.strip()]
        
        # Extract merchant name (usually first non-empty line or line with business indicators)
        merchant_name = extract_merchant_name(lines)
        if merchant_name:
            receipt_data['merchant_name'] = merchant_name
        
        # Extract date and time
        date_time = extract_date_time(text)
        if date_time:
            receipt_data['purchased_at'] = date_time
        
        # Extract amounts
        amounts = extract_amounts(text)
        receipt_data.update(amounts)
        
        # Extract payment method
        payment_method = extract_payment_method(text)
        if payment_method:
            receipt_data['payment_method'] = payment_method
        
        # Extract receipt number
        receipt_number = extract_receipt_number(text)
        if receipt_number:
            receipt_data['receipt_number'] = receipt_number
        
        # Extract cashier
        cashier = extract_cashier(text)
        if cashier:
            receipt_data['cashier'] = cashier
        
        # Extract items
        items = extract_items(lines)
        receipt_data['items'] = items
        
    except Exception as e:
        logger.error(f"Error in fallback parsing: {str(e)}")
    
    return receipt_data


def parse_receipt_text(text: str) -> Dict:
    """
    Main function to parse receipt text. First tries Gemini AI, then falls back to regex parsing.
    
    Args:
        text: Raw OCR text from receipt
        
    Returns:
        Dictionary containing parsed receipt data
    """
    # First try Gemini AI parsing
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != 'your-gemini-api-key-here':
        return parse_receipt_with_gemini(text)
    else:
        logger.warning("Gemini API key not configured, using fallback parsing")
        return get_fallback_parsing(text)


def extract_merchant_name(lines: List[str]) -> Optional[str]:
    """Extract merchant name from receipt lines."""
    # Skip very short lines and common receipt terms
    skip_terms = {'receipt', 'customer', 'copy', 'thank', 'you', 'please', 'come', 'again'}
    
    for line in lines[:5]:  # Check first 5 lines
        if len(line) > 3 and not any(term in line.lower() for term in skip_terms):
            # Check if line contains business indicators
            if any(indicator in line.lower() for indicator in ['store', 'shop', 'market', 'restaurant', 'cafe']):
                return line
            # If it's a substantial line without numbers, it's likely the merchant name
            if not re.search(r'\d+', line) and len(line) > 5:
                return line
    
    # Fallback to first substantial line
    for line in lines[:3]:
        if len(line) > 5:
            return line
    
    return None


def extract_date_time(text: str) -> Optional[datetime]:
    """Extract date and time from receipt text."""
    # Common date patterns
    date_patterns = [
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',  # MM/DD/YYYY or MM-DD-YYYY
        r'(\d{2,4}[/-]\d{1,2}[/-]\d{1,2})',  # YYYY/MM/DD or YYYY-MM-DD
        r'(\d{1,2}\s+\w+\s+\d{2,4})',        # DD Month YYYY
        r'(\w+\s+\d{1,2},?\s+\d{2,4})',      # Month DD, YYYY
    ]
    
    time_patterns = [
        r'(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)',  # HH:MM[:SS] [AM/PM]
        r'(\d{1,2}:\d{2}(?::\d{2})?)',                     # HH:MM[:SS]
    ]
    
    found_date = None
    found_time = None
    
    # Extract date
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            found_date = match.group(1)
            break
    
    # Extract time
    for pattern in time_patterns:
        match = re.search(pattern, text)
        if match:
            found_time = match.group(1)
            break
    
    # Try to parse the date and time
    if found_date:
        try:
            # Try different date formats
            for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%Y-%m-%d', '%d %B %Y', '%B %d, %Y']:
                try:
                    parsed_date = datetime.strptime(found_date, fmt)
                    if found_time:
                        # Try to parse time
                        try:
                            time_part = datetime.strptime(found_time, '%H:%M:%S').time()
                        except ValueError:
                            try:
                                time_part = datetime.strptime(found_time, '%H:%M').time()
                            except ValueError:
                                try:
                                    time_part = datetime.strptime(found_time, '%I:%M %p').time()
                                except ValueError:
                                    time_part = None
                        
                        if time_part:
                            return datetime.combine(parsed_date.date(), time_part)
                    
                    return parsed_date
                except ValueError:
                    continue
        except Exception as e:
            logger.error(f"Error parsing date: {str(e)}")
    
    return None


def extract_amounts(text: str) -> Dict:
    """Extract various amounts from receipt text."""
    amounts = {}
    
    # Patterns for different amounts
    patterns = {
        'total_amount': [
            r'total[:\s]+\$?(\d+\.?\d*)',
            r'amount[:\s]+\$?(\d+\.?\d*)',
            r'total\s+due[:\s]+\$?(\d+\.?\d*)',
        ],
        'subtotal': [
            r'subtotal[:\s]+\$?(\d+\.?\d*)',
            r'sub\s+total[:\s]+\$?(\d+\.?\d*)',
        ],
        'tax_amount': [
            r'tax[:\s]+\$?(\d+\.?\d*)',
            r'sales\s+tax[:\s]+\$?(\d+\.?\d*)',
        ],
        'tip_amount': [
            r'tip[:\s]+\$?(\d+\.?\d*)',
            r'gratuity[:\s]+\$?(\d+\.?\d*)',
        ]
    }
    
    for amount_type, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_value = Decimal(match.group(1))
                    amounts[amount_type] = amount_value
                    break
                except (ValueError, InvalidOperation):
                    continue
    
    return amounts


def extract_payment_method(text: str) -> Optional[str]:
    """Extract payment method from receipt text."""
    payment_patterns = [
        r'(credit|debit|cash|card|visa|mastercard|amex|american express)',
        r'payment\s+method[:\s]+(\w+)',
        r'paid\s+by[:\s]+(\w+)',
    ]
    
    for pattern in payment_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return None


def extract_receipt_number(text: str) -> Optional[str]:
    """Extract receipt number from text."""
    receipt_patterns = [
        r'receipt\s+#?[:\s]*(\w+)',
        r'transaction\s+#?[:\s]*(\w+)',
        r'ref\s+#?[:\s]*(\w+)',
        r'#(\d+)',
    ]
    
    for pattern in receipt_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def extract_cashier(text: str) -> Optional[str]:
    """Extract cashier name from text."""
    cashier_patterns = [
        r'cashier[:\s]+(\w+(?:\s+\w+)?)',
        r'server[:\s]+(\w+(?:\s+\w+)?)',
        r'served\s+by[:\s]+(\w+(?:\s+\w+)?)',
    ]
    
    for pattern in cashier_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def extract_items(lines: List[str]) -> List[Dict]:
    """Extract individual items from receipt lines."""
    items = []
    
    # Pattern to match item lines (item name followed by price)
    item_pattern = r'^(.+?)\s+\$?(\d+\.?\d*)$'
    
    for line in lines:
        # Skip lines that look like headers or totals
        if any(keyword in line.lower() for keyword in ['total', 'subtotal', 'tax', 'receipt', 'thank you']):
            continue
        
        match = re.match(item_pattern, line.strip())
        if match:
            item_name = match.group(1).strip()
            try:
                price = Decimal(match.group(2))
                
                # Skip if item name is too short or looks like a line item
                if len(item_name) > 2 and not item_name.isdigit():
                    items.append({
                        'name': item_name,
                        'quantity': 1,
                        'unit_price': price,
                        'total_price': price
                    })
            except (ValueError, InvalidOperation):
                continue
    
    return items