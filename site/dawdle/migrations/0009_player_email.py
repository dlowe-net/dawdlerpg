# Generated by Django 4.0.7 on 2023-04-10 17:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dawdle', '0008_ally'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='email',
            field=models.CharField(default='', max_length=64),
            preserve_default=False,
        ),
    ]