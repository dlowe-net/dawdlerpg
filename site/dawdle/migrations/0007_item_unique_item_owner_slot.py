# Generated by Django 3.2.6 on 2021-09-10 10:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dawdle', '0006_quest'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='item',
            constraint=models.UniqueConstraint(fields=('owner', 'slot'), name='unique_item_owner_slot'),
        ),
    ]