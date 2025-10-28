from django.test import TestCase

# Create your tests here.

from django.test import TestCase
from .models import PointsConfig
from .utils import get_points_per_usd

class PointsConfigTests(TestCase):
    def test_default_and_update(self):
        self.assertEqual(get_points_per_usd(), 100)
        cfg = PointsConfig.get_solo()
        cfg.points_per_usd = 250
        cfg.save()
        self.assertEqual(get_points_per_usd(), 250)