from django.db import models

class AlignmentChoices(models.TextChoices):
    GOOD = "g"
    NEUTRAL = "n"
    EVIL = "e"


class Player(models.Model):
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


class Ally(models.Model):
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    slot = models.CharField(max_length=10)      # mount, sidekick, henchman
    name = models.CharField(max_length=50) # player selectable name - may be empty
    baseclass = models.CharField(max_length=30) # lizard
    fullclass = models.CharField(max_length=30) # sparkly lizard of the beyond
    alignment = models.CharField(
        max_length=1,
        choices=AlignmentChoices.choices,
        default=AlignmentChoices.NEUTRAL
    )
    level = models.IntegerField(default=0)
    nextlvl = models.IntegerField(default=600)


class Item(models.Model):
    class Meta:
        # We use this constraint for the sqlite3 REPLACE command
        constraints = [models.UniqueConstraint(name="unique_item_owner_slot", fields=["owner", "slot"])]
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    slot = models.CharField(max_length=10)
    name = models.CharField(max_length=50)
    level = models.IntegerField()


class History(models.Model):
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    time = models.DateTimeField(auto_now_add=True)
    text = models.CharField(max_length=400)


class Quest(models.Model):
    mode = models.IntegerField(default=0)
    p1 = models.CharField(max_length=50)
    p2 = models.CharField(max_length=50)
    p3 = models.CharField(max_length=50)
    p4 = models.CharField(max_length=50)
    text = models.CharField(max_length=400)
    qtime = models.IntegerField(default=0)
    stage = models.IntegerField(default=0)
    dest1x = models.IntegerField(default=0)
    dest1y = models.IntegerField(default=0)
    dest2x = models.IntegerField(default=0)
    dest2y = models.IntegerField(default=0)
