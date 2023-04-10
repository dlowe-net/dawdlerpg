import csv
import io
import json
import os
import time

from xml.dom import minidom

from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.views import generic, View
from django.views.decorators.vary import vary_on_headers

from PIL import Image, ImageDraw

from .models import Player, Item, Quest
from project.settings import BASE_DIR

class FrontView(generic.TemplateView):
    template_name = "dawdle/front.html"


class AboutView(generic.TemplateView):
    template_name = "dawdle/about.html"


class MapView(View):

    def _colorplayer(self, player, questors):
        if player.name in questors:
            return (0x00, 0xff, 0xe9), (0x80, 0xbb, 0xff)
        if player.online:
            return (0x00, 0x1e, 0xe9), (0x80, 0xbb, 0xff)
        return (0xaa, 0xaa, 0xaa), (0xee, 0xee, 0xee)


    def get(self, request, *args, **kwargs):
        base_map = Image.open(os.path.join(BASE_DIR, "dawdle/static/dawdle/map.png"))
        full_map = base_map.copy()
        draw = ImageDraw.Draw(full_map)

        questors = []
        q = Quest.objects.get()
        if q and q.mode != 0:
            questors = [q.p1, q.p2, q.p3, q.p4]

        if 'player' in kwargs:
            pquery = Player.objects.filter(name=kwargs['player'])
            dotsize = 5
        elif 'quest' in kwargs and questors:
            pquery = Player.objects.filter(name__in=questors)
        else:
            pquery = Player.objects
            dotsize = 3

        if q and q.mode == 2:
            if q.stage == 1:
                draw.ellipse([q.dest1x-dotsize, q.dest1y-dotsize, q.dest1x+dotsize, q.dest1y+dotsize], fill=(0xff, 0xff, 0x00))
            else:
                draw.ellipse([q.dest2x-dotsize, q.dest2y-dotsize, q.dest2x+dotsize, q.dest2y+dotsize], fill=(0xff, 0xff, 0x00))

        for p in pquery.all():
            fillcolor, strokecolor = self._colorplayer(p, questors)
            draw.ellipse([p.posx-dotsize, p.posy-dotsize, p.posx+dotsize, p.posy+dotsize],
                         outline=strokecolor,
                         fill=fillcolor)

        map_bytes = io.BytesIO()
        full_map.save(map_bytes, format="png")
        return HttpResponse(map_bytes.getvalue(), content_type='image/png')


class PlayerListView(generic.ListView):
    model = Player
    queryset = Player.objects.order_by('-level', 'nextlvl')


class PlayerDetailView(generic.DetailView):
    model = Player


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p = self.object
        context['total_penalties'] = sum([p.penkick, p.penpart, p.penquit, p.pendropped, p.pennick, p.penmessage, p.penlogout, p.penquest])
        context['total_items'] = p.item_set.aggregate(Sum('level'))['level__sum']
        return context


class PlayerDumpView(generic.ListView):

    @vary_on_headers('Accept')
    def get(self, request, *args, **kwargs):
        response = HttpResponse()
        plist = []
        for p in Player.objects.all():
            plist.append({
                "name": p.name,
                "cclass": p.cclass,
                "idled": p.idled,
                "level": p.level,
                "nick": p.nick,
                "userhost": p.userhost,
                "email": p.email,
            })
        if request.accepts('text/plain') or request.accepts('text/csv'):
            response.content_type = 'text/csv'
            writer = csv.DictWriter(response, ('name', 'cclass', 'idled', 'level', 'nick', 'userhost', 'email'))
            writer.writeheader()
            for p in plist:
                writer.writerow(p)
        elif request.accepts('application/json'):
            response.content_type = 'application/json'
            json.dump(plist, response, separators=(',',':'))
        elif request.accepts('application/xml'):
            response.content_type = 'application/xml'
            root = minidom.Document()
            players_el = root.createElement('players')
            root.appendChild(players_el)
            for p in plist:
                el = root.createElement('player')
                for k,v in p.items():
                    el.setAttribute(k, str(v))
                players_el.appendChild(el)
            root.writexml(response)
        return response


class QuestView(generic.TemplateView):
    template_name = "dawdle/quest.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            quest = Quest.objects.get()
            questors = Player.objects.filter(name__in=[quest.p1,quest.p2,quest.p3,quest.p4]).all()
            context['quest'] = quest
            context['questors'] = questors
            context['qtime_remaining'] = quest.qtime - time.time()
        except Quest.DoesNotExist:
            context['quest'] = None
        return context
