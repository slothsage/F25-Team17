from pyclbr import Class
from django.db import models
from django.conf import settings
# Create your models here.


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]
    sponsor_name = models.CharField(max_length=200, blank=True)  # demo-only
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    points_spent = models.IntegerField(default=0)
    placed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def can_mark_received(self):
        return self.status in ("shipped", "delivered") and self.status != "cancelled"

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
    product_url = models.URLField(blank=True) #URL
    thumb_url = models.URLField(blank=True) #Image URL
    
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    quantity = models.IntegerField(default=1) #multiples allowed
    added_at = models.DateTimeField(auto_now=True)

    def line_points(self):
        return self.points_each * max(1, self.quantity)