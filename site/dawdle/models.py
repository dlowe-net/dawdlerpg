from django.db import models


class Player(models.Model):

    class AlignmentChoices(models.TextChoices):
        GOOD = "g"
        NEUTRAL = "n"
        EVIL = "e"

    name = models.CharField(primary_key=True, max_length=50)
    cclass = models.CharField(max_length=30)
    pw = models.CharField(max_length=64)
    alignment = models.CharField(
        max_length=1,
        choices=AlignmentChoices.choices,
        default=AlignmentChoices.NEUTRAL
    )
    isadmin = models.BooleanField(default=False)
    online = models.BooleanField(default=False)
    nick = models.CharField(max_length=32)
    level = models.IntegerField(default=0)
    nextlvl = models.IntegerField(default=600)
    userhost = models.CharField(max_length=255)
    posx = models.IntegerField()
    posy = models.IntegerField()
    idled = models.IntegerField(default=0)
    penmessage = models.IntegerField(default=0)
    pennick = models.IntegerField(default=0)
    penpart = models.IntegerField(default=0)
    penkick = models.IntegerField(default=0)
    penquit = models.IntegerField(default=0)
    pendropped = models.IntegerField(default=0)
    penquest = models.IntegerField(default=0)
    penlogout = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    lastlogin = models.DateTimeField(auto_now_add=True)
    

class Item(models.Model):
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    slot = models.CharField(max_length=10)
    name = models.CharField(max_length=50)
    level = models.IntegerField()


class History(models.Model):
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    event = models.CharField(max_length=400)
