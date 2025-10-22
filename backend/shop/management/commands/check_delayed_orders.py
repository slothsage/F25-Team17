from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from shop.models import Order  
from shop.utils import order_is_delayed
from accounts.notifications import on_order_delayed

TERMINAL = {"delivered", "cancelled"}

class Command(BaseCommand):
    help = "Scan open orders and send 'Order Delayed' alerts where applicable."

    def add_arguments(self, parser):
        parser.add_argument("--grace-hours", type=int, default=24,
                            help="Extra grace hours beyond promised ship-by.")

    def handle(self, *args, **opts):
        grace = opts["grace_hours"]
        now = timezone.now()

        # broad filter: orders not in terminal state (if you have a status field)
        qs = Order.objects.all()
        if hasattr(Order, "status"):
            qs = qs.exclude(status__in=TERMINAL)

        count_scanned = 0
        count_alerted = 0

        for order in qs.select_related("driver"):
            count_scanned += 1
            try:
                if order.driver and order_is_delayed(order, now=now, grace_hours=grace):
                    on_order_delayed(order)
                    count_alerted += 1
            except Exception as exc:
                # don't explode the whole run on one bad row
                self.stderr.write(f"Order {getattr(order, 'id', '?')}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Checked {count_scanned} orders, sent {count_alerted} delayed alerts."
        ))