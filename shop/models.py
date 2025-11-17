from pyclbr import Class
from django.db import models
from django.conf import settings
from django.core.cache import cache
from datetime import date, timedelta

POINTS_CACHE_KEY = "points_per_usd:v1"

class PointsConfig(models.Model):
    points_per_usd = models.PositiveIntegerField(default=100, help_text="How many points per $1")
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Points Configuration"
        verbose_name_plural = "Points Configuration"

    def __str__(self):
        return f"{self.points_per_usd} points / USD"
    
    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"points_per_usd": 100})
        return obj
    
    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(POINTS_CACHE_KEY)

class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]
    sponsor_name = models.CharField(max_length=200, blank=True)  
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    points_spent = models.IntegerField(default=0)
    placed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # shipping + ETA
    ship_name = models.CharField(max_length=200, blank=True)
    ship_line1 = models.CharField(max_length=200, blank=True)
    ship_line2 = models.CharField(max_length=200, blank=True)
    ship_city = models.CharField(max_length=100, blank=True)
    ship_state = models.CharField(max_length=100, blank=True)
    ship_postal = models.CharField(max_length=20, blank=True)
    ship_country = models.CharField(max_length=2, default="US")
    expected_delivery_date = models.DateField(null=True, blank=True)

    def can_mark_received(self):
        return self.status in ("shipped", "delivered") and self.status != "cancelled"
    
    def estimate_delivery_date(self) -> date:
        days = 0
        d = date.today()
        while days < 5:
            d += timedelta(days=1)
            if d.weekday() < 5:  
                days += 1
        return d

    def __str__(self):
        return f"Order#{self.id} ({self.status})"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    quantity = models.IntegerField(default=1)

    def line_points(self):
        return self.points_each * self.quantity

class CartItem(models.Model):
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    quantity = models.IntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

class Wishlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlists",
    )
    name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "name")] # one name per user

    def __str__(self):
        return f"{self.name} (by {self.user})"

class WishListItem(models.Model):
    wishlist = models.ForeignKey(
        Wishlist, on_delete=models.CASCADE, related_name="items"
    )

    # API integration fields (still don't know what is available)
    product_id = models.CharField(max_length=130, blank=True) #Ebay item ID
    product_url = models.CharField(max_length=1000, blank=True) #URL
    thumb_url = models.CharField(max_length=1000, blank=True) #Image URL
    
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    quantity = models.IntegerField(default=1) #multiples allowed
    added_at = models.DateTimeField(auto_now=True)

    def line_points(self):
        return self.points_each * max(1, self.quantity)
    

class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )

    # external/catalog fields 
    product_id = models.CharField(max_length=130)         
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    product_url = models.CharField(max_length=1000, blank=True)
    thumb_url = models.CharField(max_length=1000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("user", "product_id"),)  # prevent dupes per user
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} ❤️ {self.name_snapshot or self.product_id}"