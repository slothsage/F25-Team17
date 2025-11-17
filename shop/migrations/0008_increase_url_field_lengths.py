# Generated manually to fix URL field length issues

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0007_order_expected_delivery_date_order_ship_city_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='favorite',
            name='product_url',
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AlterField(
            model_name='favorite',
            name='thumb_url',
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AlterField(
            model_name='wishlistitem',
            name='product_url',
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AlterField(
            model_name='wishlistitem',
            name='thumb_url',
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]

