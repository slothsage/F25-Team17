import requests
import base64
from django.core.cache import cache
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class EbayService:
    """Service for interacting with eBay Browse API"""
    
    def __init__(self):
        self.client_id = getattr(
            settings, 
            'EBAY_CLIENT_ID', 
            'JacobRob-F25Team1-SBX-2df8ae938-510a37dd'
        )
        self.client_secret = getattr(
            settings, 
            'EBAY_CLIENT_SECRET', 
            'SBX-df8ae938df8a-57b0-43e2-a63b-f447'
        )
        self.is_sandbox = getattr(settings, 'EBAY_SANDBOX', True)
        
        self.base_url = (
            'https://api.sandbox.ebay.com' if self.is_sandbox 
            else 'https://api.ebay.com'
        )
    
    def _get_base64_auth(self):
        """Generate Base64 authorization header"""
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        return base64.b64encode(auth_bytes).decode('utf-8')
    
    def get_access_token(self):
        """Get or refresh eBay access token (cached)"""
        token = cache.get('ebay_access_token')
        if token:
            return token
        
        logger.info('Refreshing eBay access token...')
        
        url = f"{self.base_url}/identity/v1/oauth2/token"
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {self._get_base64_auth()}'
        }
        
        data = {
            'grant_type': 'client_credentials',
            'scope': 'https://api.ebay.com/oauth/api_scope'
        }
        
        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            
            token_data = response.json()
            access_token = token_data['access_token']
            expires_in = token_data['expires_in']
            
            cache.set('ebay_access_token', access_token, expires_in - 300)
            
            logger.info('eBay token refreshed successfully')
            return access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Error getting eBay token: {e}')
            raise Exception(f"Failed to authenticate with eBay: {str(e)}")
    
    def search_products(self, query, limit=20, offset=0, category_ids=None):
        """Search for products on eBay"""
        token = self.get_access_token()
        
        url = f"{self.base_url}/buy/browse/v1/item_summary/search"
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        params = {
            'q': query,
            'limit': min(limit, 200),  
            'offset': offset
        }
        
        if category_ids:
            params['category_ids'] = category_ids
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Error searching products: {e}')
            raise Exception(f"Failed to search eBay products: {str(e)}")
    
    def get_product_details(self, item_id):
        """Get detailed information about a specific product"""
        token = self.get_access_token()
        
        url = f"{self.base_url}/buy/browse/v1/item/{item_id}"
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Error getting product details: {e}')
            raise Exception(f"Failed to get product details: {str(e)}")
    
    def format_product(self, ebay_item):
        """Format eBay product data for our system"""
        try:
            price_value = float(ebay_item.get('price', {}).get('value', 0))
        except (ValueError, TypeError):
            price_value = 0.0
        
        # Get image URL
        image_url = ''
        if ebay_item.get('image'):
            image_url = ebay_item['image'].get('imageUrl', '')
        elif ebay_item.get('thumbnailImages') and len(ebay_item['thumbnailImages']) > 0:
            image_url = ebay_item['thumbnailImages'][0].get('imageUrl', '')
        
        return {
            'ebay_item_id': ebay_item.get('itemId', ''),
            'name': ebay_item.get('title', 'Unknown Product'),
            'price_usd': price_value,
            'price_points': int(price_value * 100),  
            'description': ebay_item.get('shortDescription', ebay_item.get('title', '')),
            'image_url': image_url,
            'category': (
                ebay_item.get('categories', [{}])[0].get('categoryName', 'Uncategorized')
                if ebay_item.get('categories') else 'Uncategorized'
            ),
            'condition': ebay_item.get('condition', 'Unknown'),
            'is_available': ebay_item.get('availableQuantity', 0) > 0,
            'ebay_url': ebay_item.get('itemWebUrl', '')
        }


ebay_service = EbayService()