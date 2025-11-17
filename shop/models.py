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
    
    def can_cancel(self):
        """Check if this order can be cancelled by the driver."""
        return self.status in ("pending", "confirmed", "processing")
    
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


class SavedCart(models.Model):
    """Saved cart for later checkout - allows drivers to save cart items when they don't have enough points."""
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_carts")
    name = models.CharField(max_length=200, default="Saved Cart", help_text="Name for this saved cart")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_points = models.PositiveIntegerField(default=0, help_text="Total points for all items in this saved cart")

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Saved Cart"
        verbose_name_plural = "Saved Carts"

    def __str__(self):
        return f"{self.name} - {self.driver.username} ({self.total_points} pts)"

    def calculate_total(self):
        """Calculate and update total points for this saved cart."""
        total = sum(item.points_each * item.quantity for item in self.items.all())
        self.total_points = total
        self.save(update_fields=["total_points"])
        return total


class SavedCartItem(models.Model):
    """Individual items in a saved cart."""
    saved_cart = models.ForeignKey(SavedCart, on_delete=models.CASCADE, related_name="items")
    name_snapshot = models.CharField(max_length=255)
    points_each = models.IntegerField(default=0)
    quantity = models.IntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at"]

    def __str__(self):
        return f"{self.name_snapshot} × {self.quantity} ({self.saved_cart.name})"

    def line_points(self):
        return self.points_each * self.quantity

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


class SponsorCatalogItem(models.Model):
    """
    Items in the sponsor-only catalog that drivers cannot see.
    Sponsors can add these items to the driver catalog.
    """
    sponsor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sponsor_catalog_items"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    points_cost = models.PositiveIntegerField(default=0, help_text="Points required to purchase")
    image_url = models.URLField(max_length=1000, blank=True)
    product_url = models.URLField(max_length=1000, blank=True)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, help_text="Only active items are shown")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Sponsor Catalog Item"
        verbose_name_plural = "Sponsor Catalog Items"

    def __str__(self):
        return f"{self.name} (by {self.sponsor.username})"


class DriverCatalogItem(models.Model):
    """
    Items available in the driver catalog.
    These can come from sponsor catalogs or be added directly.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    points_cost = models.PositiveIntegerField(default=0, help_text="Points required to purchase")
    image_url = models.URLField(max_length=1000, blank=True)
    product_url = models.URLField(max_length=1000, blank=True)
    category = models.CharField(max_length=100, blank=True)
    condition = models.CharField(max_length=50, blank=True, default="New")
    is_active = models.BooleanField(default=True, help_text="Only active items are shown to drivers")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="catalog_items_added",
        help_text="Sponsor/admin who added this item"
    )
    source_sponsor_item = models.ForeignKey(
        SponsorCatalogItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="driver_catalog_items",
        help_text="Original sponsor catalog item if this was added from sponsor catalog"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Driver Catalog Item"
        verbose_name_plural = "Driver Catalog Items"

    def __str__(self):
        return f"{self.name} ({self.points_cost} pts)"