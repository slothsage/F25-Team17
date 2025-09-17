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