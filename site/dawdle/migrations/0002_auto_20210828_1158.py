# Generated by Django 3.2.6 on 2021-08-28 11:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dawdle', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='idled',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='level',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='nextlvl',
            field=models.IntegerField(default=600),
        ),
        migrations.AlterField(
            model_name='player',
            name='pendropped',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penkick',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penlogout',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penmessage',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='pennick',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penpart',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penquest',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='player',
            name='penquit',
            field=models.IntegerField(default=0),
        ),
    ]
