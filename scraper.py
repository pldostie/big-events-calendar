#!/usr/bin/env python3
"""
Big Events Calendar Scraper v3
================================
  F1 / Tennis (Grand Slams) / UFC / NFL Bears / NBA / NHL Canadiens /
  Rocket League RLCS / FIFA World Cup 2026 / Ubisoft releases / AAA Games

Rules:
  - Event TITLES always contain participant/team names (never just city)
  - UFC title = "UFC ### -- Fighter A vs Fighter B"
  - NHL/NFL = "Team A vs Team B" or "Team A @ Team B"
  - Tennis QF/SF/Final = "Player A vs Player B" when known
  - World Cup = "Country A vs Country B" with kickoff time

Output: big_events.ics  (GitHub Actions runs daily at 05:00 UTC)
"""

import re, sys, uuid, time, requests
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from icalendar import Calendar, Event
from dataclasses import dataclass
from typing import Optional

UTC  = ZoneInfo("UTC")
ET   = ZoneInfo("America/New_York")
TODAY = date.today()
YEAR  = TODAY.year

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

SPORT_TAG = {
    "F1":"F1","Tennis":"Tennis","UFC":"UFC","NFL":"NFL","NBA":"NBA",
    "NHL":"NHL","Rocket League":"RL","World Cup":"WC",
    "Ubisoft":"Ubisoft","AAA Games":"Game",
}

MONTHS = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,
    "june":6,"july":7,"august":8,"september":9,
    "october":10,"november":11,"december":12,
}

NHL_TEAMS = {
    "ANA":"Anaheim Ducks","BOS":"Boston Bruins","BUF":"Buffalo Sabres",
    "CGY":"Calgary Flames","CAR":"Carolina Hurricanes","CHI":"Chicago Blackhawks",
    "COL":"Colorado Avalanche","CBJ":"Columbus Blue Jackets","DAL":"Dallas Stars",
    "DET":"Detroit Red Wings","EDM":"Edmonton Oilers","FLA":"Florida Panthers",
    "LAK":"Los Angeles Kings","MIN":"Minnesota Wild","NSH":"Nashville Predators",
    "NJD":"New Jersey Devils","NYI":"New York Islanders","NYR":"New York Rangers",
    "OTT":"Ottawa Senators","PHI":"Philadelphia Flyers","PIT":"Pittsburgh Penguins",
    "SJS":"San Jose Sharks","SEA":"Seattle Kraken","STL":"St. Louis Blues",
    "TBL":"Tampa Bay Lightning","TOR":"Toronto Maple Leafs","UTA":"Utah Hockey Club",
    "VAN":"Vancouver Canucks","VGK":"Vegas Golden Knights","WSH":"Washington Capitals",
    "WPG":"Winnipeg Jets",
}

AAA_PUBLISHERS = {
    "ubisoft","ea","electronic arts","activision","blizzard","rockstar",
    "take-two","2k games","sony","playstation studios","microsoft","xbox",
    "bethesda","capcom","square enix","bandai namco","sega","nintendo",
    "cd projekt","warner bros","505 games","thq nordic","deep silver",
    "naughty dog","insomniac","guerrilla",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(url, delay=1.5):
    time.sleep(delay)
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def pdate(text, year=None):
    if year is None: year = YEAR
    text = str(text).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try: return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
        except: pass
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(\d{4})", text)
    if m:
        mo = MONTHS.get(m.group(1).lower()[:3])
        if mo:
            try: return date(int(m.group(3)),mo,int(m.group(2)))
            except: pass
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\b", text)
    if m:
        mo = MONTHS.get(m.group(1).lower()[:3])
        if mo:
            try: return date(year,mo,int(m.group(2)))
            except: pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?", text)
    if m:
        mo = MONTHS.get(m.group(2).lower()[:3])
        if mo:
            yr = int(m.group(3)) if m.group(3) else year
            try: return date(yr,mo,int(m.group(1)))
            except: pass
    return None

def pdrange(text, fy=None):
    if fy is None: fy = YEAR
    text = text.replace("--","_").replace("-"," - ").replace("_","-").replace("--","-")
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", text)
    if m:
        m1=MONTHS.get(m.group(1).lower()[:3]); m2=MONTHS.get(m.group(3).lower()[:3]); yr=int(m.group(5))
        if m1 and m2:
            try: return date(yr,m1,int(m.group(2))), date(yr,m2,int(m.group(4)))
            except: pass
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),?\s*(\d{4})", text)
    if m:
        mo=MONTHS.get(m.group(1).lower()[:3]); yr=int(m.group(4))
        if mo:
            try: return date(yr,mo,int(m.group(2))), date(yr,mo,int(m.group(3)))
            except: pass
    d = pdate(text, fy)
    if d: return d, d
    return None, None

def parse_et(game_date: date, time_str: str) -> Optional[datetime]:
    """Parse an ET time string like '7:30 PM' or '8:20PM' into a UTC-aware datetime."""
    if not time_str: return None
    try:
        ts = time_str.strip().replace(" "," ")
        for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
            try:
                t = datetime.strptime(ts, fmt)
                local_dt = datetime(game_date.year, game_date.month, game_date.day,
                                    t.hour, t.minute, 0, tzinfo=ET)
                return local_dt.astimezone(UTC)
            except ValueError:
                continue
    except Exception:
        pass
    return None

@dataclass
class Evt:
    name: str
    sport: str
    start: date
    end: date
    location: str = ""
    url: str = ""
    description: str = ""
    start_dt: Optional[datetime] = None  # timezone-aware datetime; if set → timed event

    @property
    def summary(self):
        tag = SPORT_TAG.get(self.sport,"")
        return f"[{tag}] {self.name}" if tag else self.name


# ---------------------------------------------------------------------------
# F1 -- OpenF1 API (returns exact UTC datetimes)
# ---------------------------------------------------------------------------
def scrape_f1():
    events = []
    for year in [YEAR, YEAR+1]:
        try:
            r = requests.get("https://api.openf1.org/v1/sessions",
                params={"year":year,"session_type":"Race"},timeout=20)
            r.raise_for_status()
            for s in r.json():
                try:
                    raw = s["date_start"]
                    if "T" in raw:
                        start_dt = datetime.fromisoformat(raw.replace("Z","+00:00"))
                        start = start_dt.date()
                        sdt = start_dt.astimezone(UTC)
                    else:
                        start = date.fromisoformat(raw[:10]); sdt = None
                    end = date.fromisoformat(s.get("date_end",raw)[:10])
                    events.append(Evt(
                        name=f"{s['country_name']} Grand Prix", sport="F1",
                        start=start, end=end,
                        location=f"{s.get('circuit_short_name','')}, {s.get('country_name','')}",
                        url=f"https://www.formula1.com/en/racing/{year}.html",
                        description=f"{year} F1 Season",
                        start_dt=sdt))
                except: pass
        except Exception as e:
            print(f"  [F1] {year}: {e}", file=sys.stderr)
    print(f"  [F1] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# Tennis -- Grand Slams only
# ---------------------------------------------------------------------------
# tz = local timezone of the venue (for showing correct kickoff time)
# qf_h / sf_h / final_h = approximate LOCAL hour for first match of that round
GRAND_SLAMS = [
    {"name":"Australian Open","start":date(2026,1,19),"end":date(2026,2,1),
     "location":"Melbourne Park, Melbourne, Australia",
     "wiki":"2026_Australian_Open","ms":False,
     "tz":"Australia/Melbourne","qf_h":11,"sf_h":11,"final_h":19,"bbc_slug":"australian-open"},
    {"name":"Roland Garros","start":date(2026,5,25),"end":date(2026,6,7),
     "location":"Stade Roland Garros, Paris, France",
     "wiki":"2026_French_Open_(tennis)","ms":False,
     "tz":"Europe/Paris","qf_h":12,"sf_h":12,"final_h":12,"bbc_slug":"french-open"},
    {"name":"Wimbledon","start":date(2026,6,29),"end":date(2026,7,13),
     "location":"All England Club, London, UK",
     "wiki":"2026_Wimbledon_Championships","ms":False,  # plays all 14 days since 2022
     "tz":"Europe/London","qf_h":13,"sf_h":13,"final_h":14,"bbc_slug":"wimbledon"},
    {"name":"US Open","start":date(2026,8,31),"end":date(2026,9,13),
     "location":"USTA Billie Jean King National Tennis Center, New York, USA",
     "wiki":"2026_US_Open_(tennis)","ms":False,
     "tz":"America/New_York","qf_h":12,"sf_h":12,"final_h":16,"bbc_slug":"us-open"},
    {"name":"Australian Open","start":date(2027,1,18),"end":date(2027,1,31),
     "location":"Melbourne Park, Melbourne, Australia",
     "wiki":"2027_Australian_Open","ms":False,
     "tz":"Australia/Melbourne","qf_h":11,"sf_h":11,"final_h":19,"bbc_slug":"australian-open"},
]

def slam_sched(slam):
    s=slam["start"]; ms=1 if slam.get("ms") else 0
    return {
        "R1":(s,s+timedelta(1)),"R2":(s+timedelta(2),s+timedelta(3)),
        "R3":(s+timedelta(4),s+timedelta(5)),"R4":(s+timedelta(6+ms),s+timedelta(7+ms)),
        "QF":(s+timedelta(8+ms),s+timedelta(9+ms)),
        "SF-W":(s+timedelta(10+ms),s+timedelta(10+ms)),
        "SF-M":(s+timedelta(11+ms),s+timedelta(11+ms)),
        "F-W":(s+timedelta(12+ms),s+timedelta(12+ms)),
        "F-M":(s+timedelta(13+ms),s+timedelta(13+ms)),
    }

def _link_players_from_soup(soup, res):
    """Extract player name pairs from Wikipedia <a> tag links (players are linked to their pages)."""
    SKIP = {
        "Wimbledon","Australian Open","Roland Garros","French Open","US Open",
        "Tennis","Grand Slam","Open era","ATP","WTA","ITF","BBC","ESPN",
        "Seeding (sports)","Wild card (sports)","Lucky loser","Qualifier",
        "Walkover","Retirement (tennis)","Defending champion","Doubles",
        "Mixed doubles","Boy","Girl",
    }
    def is_player(title):
        return (title and " " in title and len(title) < 50
                and not any(s.lower() in title.lower() for s in SKIP)
                and not re.search(r"[\(\[0-9]", title))

    for heading in soup.find_all(["h2","h3","h4","h5"]):
        htext = heading.get_text(strip=True).lower()
        if   "quarter" in htext: key = "QF"
        elif "semi"    in htext: key = "SF"
        elif htext in ("final","the final","finals") or htext.endswith(" final"): key = "Final"
        else: continue

        # Collect player links in the section under this heading
        node = heading.find_next_sibling()
        names = []
        while node and getattr(node, "name", None) not in ["h2","h3","h4"]:
            for a in getattr(node, "find_all", lambda *a, **k: [])(
                    "a", href=re_mod.compile(r"^/wiki/[^:]+$")):
                title = a.get("title","") or a.get_text(strip=True)
                if is_player(title) and title not in names:
                    names.append(title)
            node = getattr(node, "find_next_sibling", lambda: None)()
        for i in range(0, len(names) - 1, 2):
            pair = (names[i], names[i+1])
            if pair not in res[key]:
                res[key].append(pair)

def _text_players_from_soup(soup, res):
    """Fallback: regex on page text for 'Player A def. Player B' patterns."""
    name_pat = r"([A-ZÀ-ž\u0100-\u017E][a-zÀ-ž\u0100-\u017E'\-\.]+(?:\s[A-ZÀ-ž\u0100-\u017E][a-zÀ-ž\u0100-\u017E'\-\.]+)+)"
    pats = [
        name_pat + r"\s+(?:def\.|defeated|beat)\s+" + name_pat,
        name_pat + r"\s+v\.?s?\.?\s+" + name_pat,
    ]
    SKIP = {"The","This","In","At","After","Before","Match","Round","Final","Open",
            "Championship","Draw","Seeds","Notes","Tennis","Cup","Club","Park",
            "Court","Centre","Grand","All","England","United","Roland","Garros",
            "Billie","Jean","King","National","Women","Men","Singles","Doubles"}
    for block in soup.find_all(["p","li","td","th","caption"]):
        raw = block.get_text(separator=" ", strip=True)
        low = raw.lower()
        for key, kws in [
            ("QF",    ["quarterfinal","quarter-final"]),
            ("SF",    ["semifinal","semi-final"]),
            ("Final", ["final"]),
        ]:
            if key == "Final" and any(w in low for w in ["semi","quarter"]): continue
            if key == "SF"    and "quarter" in low: continue
            if any(k in low for k in kws):
                for pat in pats:
                    for m in re.finditer(pat, raw):
                        p1, p2 = m.group(1).strip(), m.group(2).strip()
                        if (len(p1) > 4 and len(p2) > 4 and p1 != p2
                                and p1.split()[0] not in SKIP
                                and p2.split()[0] not in SKIP
                                and (p1, p2) not in res[key]):
                            res[key].append((p1, p2))

def _bbc_players(slam, sc):
    """Fetch BBC Sport scores-fixtures pages around QF/SF/Final dates for player names."""
    res = {"QF":[], "SF":[], "Final":[]}
    slug = slam.get("bbc_slug")
    if not slug:
        return res
    name_pat = r"([A-ZÀ-ž\u0100-\u017E][a-z][a-zÀ-ž\u0100-\u017E'\-\.]*(?:\s[A-ZÀ-ž\u0100-\u017E][a-z][a-zÀ-ž\u0100-\u017E'\-\.]*)+)"
    SKIP = {"Women","Men","Singles","Doubles","Mixed","Wimbledon","Open","Australian",
            "Roland","Garros","French","United","States","National","Tennis","Cup"}
    round_dates = [
        ("QF",    [sc["QF"][0], sc["QF"][1]]),
        ("SF",    [sc["SF-W"][0], sc["SF-M"][0]]),
        ("Final", [sc["F-W"][0], sc["F-M"][0]]),
    ]
    for key, dates in round_dates:
        for d in dates:
            if d < TODAY - timedelta(5) or d > TODAY + timedelta(60):
                continue  # only fetch near-term dates
            url = f"https://www.bbc.co.uk/sport/tennis/{slug}/scores-fixtures/{d.strftime('%Y-%m-%d')}"
            try:
                soup = get(url, delay=1.0)
                # BBC renders match cards server-side; player names appear in the page text
                page_text = soup.get_text(" ", strip=True)
                # Find "Player A v Player B" patterns in BBC text
                for m in re.finditer(name_pat + r"\s+v\.?\s+" + name_pat, page_text):
                    p1, p2 = m.group(1).strip(), m.group(2).strip()
                    if (len(p1) > 4 and len(p2) > 4 and p1 != p2
                            and p1.split()[0] not in SKIP
                            and p2.split()[0] not in SKIP
                            and (p1, p2) not in res[key]):
                        res[key].append((p1, p2))
            except Exception as e:
                print(f"  [Tennis] BBC {slug} {d}: {e}", file=sys.stderr)
    return res

def wiki_players(slam):
    """Get QF/SF/Final player pairs from BBC Sport, Wikipedia (links + text)."""
    res = {"QF":[], "SF":[], "Final":[]}
    sc  = slam_sched(slam)

    # Source 1: BBC Sport scores-fixtures (live, server-side rendered)
    bbc = _bbc_players(slam, sc)
    for k in res: res[k].extend(bbc[k])

    # Source 2: Wikipedia — try main page + dedicated singles pages
    base = slam["wiki"]
    wiki_urls = [
        f"https://en.wikipedia.org/wiki/{base}",
        f"https://en.wikipedia.org/wiki/{base}_%E2%80%93_Women%27s_singles",
        f"https://en.wikipedia.org/wiki/{base}_%E2%80%93_Men%27s_singles",
    ]
    for url in wiki_urls:
        try:
            soup = get(url, delay=1.5)
            _link_players_from_soup(soup, res)  # link-based (more reliable)
            _text_players_from_soup(soup, res)  # text regex fallback
        except Exception as e:
            print(f"  [Tennis] {slam['name']} wiki ({url.split('/')[-1][:30]}): {e}", file=sys.stderr)

    print(f"  [Tennis] {slam['name']} players — QF:{len(res['QF'])} SF:{len(res['SF'])} F:{len(res['Final'])}")
    return res

def scrape_tennis():
    events = []
    for slam in GRAND_SLAMS:
        if slam["end"] < TODAY - timedelta(60): continue
        wurl  = f"https://en.wikipedia.org/wiki/{slam['wiki']}"
        sc    = slam_sched(slam)
        pl    = wiki_players(slam)
        slam_tz = ZoneInfo(slam.get("tz", "UTC"))
        qf_h  = slam.get("qf_h",  13)
        sf_h  = slam.get("sf_h",  13)
        fin_h = slam.get("final_h", 14)

        for rnd in ["R1","R2","R3","R4"]:
            s, e = sc[rnd]
            events.append(Evt(name=f"{slam['name']} -- {rnd}", sport="Tennis",
                start=s, end=e, location=slam["location"], url=wurl,
                description=f"{slam['name']} {rnd} -- all courts"))

        # QF: Women's day first, then Men's day (each get their own timed event)
        for i, day in enumerate(sc["QF"]):
            g = "Women's" if i == 0 else "Men's"
            h = qf_h + i          # Women's at qf_h, Men's 1h later
            pairs = pl.get("QF", [])
            if i < len(pairs):
                p1, p2 = pairs[i]
                n = f"{slam['name']} QF ({g}) -- {p1} vs {p2}"
            else:
                n = f"{slam['name']} QF ({g}) -- TBD"
            sdt = datetime(day.year, day.month, day.day, h, 0, 0, tzinfo=slam_tz)
            events.append(Evt(name=n, sport="Tennis", start=day, end=day,
                location=slam["location"], url=wurl,
                description="Quarterfinal", start_dt=sdt))

        # SF and Finals: each match on its own day with approximate kickoff time
        for rk, g, pi in [("SF-W","Women's",0), ("SF-M","Men's",1),
                           ("F-W", "Women's",0), ("F-M", "Men's",1)]:
            day = sc[rk][0]
            lbl = "SF" if rk.startswith("SF") else "Final"
            h   = (sf_h if lbl == "SF" else fin_h) + pi  # Women's slightly earlier
            pairs = pl.get("SF" if lbl == "SF" else "Final", [])
            if pi < len(pairs):
                p1, p2 = pairs[pi]
                n = f"{slam['name']} {lbl} ({g}) -- {p1} vs {p2}"
            else:
                n = f"{slam['name']} {lbl} ({g}) -- TBD"
            sdt = datetime(day.year, day.month, day.day, h, 0, 0, tzinfo=slam_tz)
            events.append(Evt(name=n, sport="Tennis", start=day, end=day,
                location=slam["location"], url=wurl,
                description=f"{g} {lbl}", start_dt=sdt))

    print(f"  [Tennis] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# UFC -- Numbered events only (UFC ###) with fighters in title
# UFC main cards: ~10 PM ET = 02:00 UTC (next day in UTC during summer)
# ---------------------------------------------------------------------------
def scrape_ufc():
    events = []; url = "https://en.wikipedia.org/wiki/List_of_UFC_events"
    try:
        soup = get(url); table = None
        for h in soup.find_all(["h2","h3"]):
            if "upcoming" in h.get_text().lower():
                n = h.find_next_sibling()
                while n:
                    if getattr(n,"name",None) == "table": table = n; break
                    n = n.find_next_sibling()
                break
        if not table:
            for t in soup.find_all("table", class_=re.compile("wikitable")):
                if "UFC" in t.get_text()[:500]: table = t; break
        if not table:
            print("  [UFC] No table", file=sys.stderr); return events
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td","th"])]
            if not cells: continue
            ename = None
            for c in cells:
                m = re.match(r"^(UFC\s+\d+)\b", c.strip())
                if m: ename = m.group(1); break
            if not ename: continue
            edate = None
            for c in cells:
                d = pdate(c, YEAR)
                if d and d >= TODAY: edate = d; break
            if not edate: continue
            loc  = next((c for c in cells if "," in c and 5 < len(c) < 60), "")
            main = next((c for c in cells if " vs " in c.lower() and len(c) > 10), "")
            title = f"{ename} -- {main}" if main else ename
            # 10 PM ET main card -- store as ET datetime
            sdt = datetime(edate.year, edate.month, edate.day, 22, 0, 0, tzinfo=ET)
            events.append(Evt(name=title, sport="UFC", start=edate, end=edate,
                location=loc, url=url,
                description="Main card: 10:00 PM ET",
                start_dt=sdt))
    except Exception as e:
        print(f"  [UFC] {e}", file=sys.stderr)
    print(f"  [UFC] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# NFL Bears -- regular season + playoffs
# ---------------------------------------------------------------------------
def scrape_nfl_bears():
    events = []
    for season in [YEAR, YEAR+1]:
        url = f"https://www.pro-football-reference.com/teams/chi/{season}_games.htm"
        try:
            soup = get(url, delay=2.5)
            table = soup.find("table", id=re.compile(r"games"))
            if not table:
                for t in soup.find_all("table"):
                    tx = t.get_text().lower()
                    if "week" in tx and "opponent" in tx: table = t; break
            if not table: continue
            tbody = table.find("tbody") or table
            for row in tbody.find_all("tr"):
                if "thead" in " ".join(row.get("class",[])): continue
                cells = {td.get("data-stat",""):td.get_text(strip=True)
                         for td in row.find_all(["td","th"])}
                week   = cells.get("week_num","")
                gday   = cells.get("game_date","") or cells.get("date_game","")
                gtime  = cells.get("gametime","") or cells.get("game_time","")
                loc    = cells.get("game_location","")
                opp    = cells.get("opp","")
                if not opp or opp.lower() in ("bye week","bye",""): continue
                d = pdate(gday, season)
                if not d: continue
                away = loc.strip() == "@"
                name = f"Chicago Bears {'@' if away else 'vs'} {opp}"
                place = f"{opp} -- Away" if away else "Soldier Field, Chicago, IL"
                try: is_po = int(week) >= 19
                except: is_po = any(k in str(week).lower()
                                    for k in ["wild","division","conference","super"])
                phase = "Playoffs" if is_po else f"Regular Season Week {week}"
                sdt = parse_et(d, gtime) if gtime else None
                desc = f"NFL {phase}" + (f"\nKickoff: {gtime} ET" if gtime else "")
                events.append(Evt(name=name, sport="NFL", start=d, end=d,
                    location=place, url=url, description=desc, start_dt=sdt))
            if events: break
        except Exception as e:
            print(f"  [NFL] {season}: {e}", file=sys.stderr)
    print(f"  [NFL] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# NBA -- season start marker only
# ---------------------------------------------------------------------------
NBA_STARTS = {
    2025: date(2025,10,22),
    2026: date(2026,10,21),
    2027: date(2027,10,21),
}

def scrape_nba():
    events = []
    for year, start in NBA_STARTS.items():
        if start >= TODAY - timedelta(30):
            events.append(Evt(
                name=f"NBA Season {year}-{year+1} Begins", sport="NBA",
                start=start, end=start, location="USA",
                url=f"https://en.wikipedia.org/wiki/{year}%E2%80%93{str(year+1)[2:]}_NBA_season",
                description=f"NBA Regular Season {year}-{year+1} opening night"))
    print(f"  [NBA] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# NHL Canadiens -- all games
# ---------------------------------------------------------------------------
def scrape_nhl_habs():
    events = []
    for ey in [YEAR+1, YEAR]:
        url = f"https://www.hockey-reference.com/teams/MTL/{ey}_games.html"
        try:
            soup = get(url, delay=2.5)
            table = soup.find("table", id="games")
            if not table: continue
            tbody = table.find("tbody") or table
            for row in tbody.find_all("tr"):
                if "thead" in " ".join(row.get("class",[])): continue
                cells = {td.get("data-stat",""):td.get_text(strip=True)
                         for td in row.find_all(["td","th"])}
                ds  = cells.get("date_game","")
                oa  = cells.get("opp","")
                ha  = cells.get("game_location","")
                gt  = cells.get("time_game","") or cells.get("game_start_time","")
                if not ds or not oa: continue
                d = pdate(ds, ey-1)
                if not d: continue
                opp  = NHL_TEAMS.get(oa, oa)
                away = ha.strip() == "@"
                name = f"Canadiens {'@' if away else 'vs'} {opp}"
                place = f"{opp} -- Away" if away else "Centre Bell, Montreal, QC"
                sdt = parse_et(d, gt) if gt else None
                desc = (f"NHL Regular Season {ey-1}-{ey}"
                        + (f"\nPuck drop: {gt} ET" if gt else ""))
                events.append(Evt(name=name, sport="NHL", start=d, end=d,
                    location=place, url=url, description=desc, start_dt=sdt))
            if events: break
        except Exception as e:
            print(f"  [NHL] {ey}: {e}", file=sys.stderr)
    print(f"  [NHL] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# Rocket League RLCS -- Liquipedia
# ---------------------------------------------------------------------------
RL_KW = ["major","open","world championship","finals","regional"]

def scrape_rocket_league():
    events = []
    for slug in ["2025-26","2026-27"]:
        yr = int(slug[:4])
        url = f"https://liquipedia.net/rocketleague/Rocket_League_Championship_Series/{slug}"
        try:
            soup = get(url, delay=2.5); found = []
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = [td.get_text(" ",strip=True) for td in row.find_all(["td","th"])]
                    rt = " ".join(cells).lower()
                    if not any(k in rt for k in RL_KW): continue
                    en = next((c for c in cells
                                if any(k in c.lower() for k in RL_KW) and len(c) < 100), None)
                    if not en: continue
                    s = e = None
                    for c in cells:
                        s, e = pdrange(c, yr)
                        if s: break
                    if s:
                        found.append(Evt(name=f"RLCS {slug} -- {en}", sport="Rocket League",
                            start=s, end=(e or s), url=url, description=f"RLCS {slug}"))
            if not found:
                for lnk in soup.find_all("a", href=True):
                    lt = lnk.get_text(strip=True); h = lnk["href"]
                    if not any(k in lt.lower() for k in RL_KW): continue
                    if "Championship_Series" not in h: continue
                    ctx = lnk.parent.get_text(separator=" ",strip=True) if lnk.parent else ""
                    s, e = pdrange(ctx, yr)
                    if s:
                        fu = f"https://liquipedia.net{h}" if h.startswith("/") else h
                        found.append(Evt(name=f"RLCS {slug} -- {lt}", sport="Rocket League",
                            start=s, end=(e or s), url=fu, description=f"RLCS {slug}"))
            events.extend(found)
        except Exception as e:
            print(f"  [RL] {slug}: {e}", file=sys.stderr)
    print(f"  [Rocket League] {len(events)} events")
    return events

# ---------------------------------------------------------------------------
# FIFA World Cup 2026 -- ESPN public API
# Returns real team names + UTC kickoff times for all matches
# ---------------------------------------------------------------------------
WC_START = date(2026, 6, 11)
WC_END   = date(2026, 7, 19)
ESPN_WC  = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

def _espn_event(event: dict, events: list, seen: set):
    try:
        raw_date = event["date"]   # "2026-06-16T19:00Z"
        match_dt = datetime.fromisoformat(raw_date.replace("Z","+00:00")).astimezone(UTC)
        match_date = match_dt.date()
        comps = event["competitions"][0]["competitors"]
        home = next((c["team"]["displayName"] for c in comps
                     if c.get("homeAway") == "home"), "")
        away = next((c["team"]["displayName"] for c in comps
                     if c.get("homeAway") == "away"), "")
        if not home or not away: return
        title = f"{away} vs {home}"
        key = (title.lower(), match_date)
        if key in seen: return
        seen.add(key)
        venue  = (event["competitions"][0].get("venue") or {}).get("fullName","")
        rnd    = (event.get("season",{}).get("type",{}).get("name","") or
                  event.get("competitions",[{}])[0].get("notes",[""])[0] if
                  event.get("competitions",[{}])[0].get("notes") else "")
        # altGameNote e.g. "FIFA World Cup, Quarterfinals"
        alt = event["competitions"][0].get("altGameNote","")
        if "," in alt: rnd = alt.split(",",1)[1].strip()
        t_utc = match_dt.strftime("%H:%M")
        desc = f"Round: {rnd}\nKickoff: {t_utc} UTC\nVenue: {venue}"
        events.append(Evt(
            name=f"FIFA World Cup -- {title}", sport="World Cup",
            start=match_date, end=match_date,
            location=venue,
            url="https://www.espn.com/soccer/scoreboard/_/league/fifa.world",
            description=desc,
            start_dt=match_dt))
    except Exception as e:
        pass

def scrape_world_cup():
    events = []; seen = set()
    # Fetch from 2 days ago through end of tournament (covers recent + upcoming)
    fetch_from = max(WC_START, TODAY - timedelta(2))
    d = fetch_from
    while d <= WC_END:
        try:
            r = requests.get(ESPN_WC, params={"dates": d.strftime("%Y%m%d")},
                             headers=HEADERS, timeout=20)
            r.raise_for_status()
            for ev in r.json().get("events", []):
                _espn_event(ev, events, seen)
        except Exception as e:
            print(f"  [WC] {d}: {e}", file=sys.stderr)
        d += timedelta(1)
        time.sleep(0.8)
    print(f"  [World Cup] {len(events)} matches")
    return events

# ---------------------------------------------------------------------------
# Video games -- Wikipedia "{year} in video games"
# ---------------------------------------------------------------------------
def scrape_games_wiki(year):
    url = f"https://en.wikipedia.org/wiki/{year}_in_video_games"; games = []
    try:
        soup = get(url, delay=2.0)
        for table in soup.find_all("table", class_=re.compile("wikitable")):
            rows = table.find_all("tr")
            if len(rows) < 2: continue
            hdrs = [h.get_text(strip=True).lower() for h in rows[0].find_all(["th","td"])]
            col = {}
            for i, h in enumerate(hdrs):
                if ("title" in h or "game" in h) and "title" not in col: col["title"] = i
                elif "developer" in h and "dev" not in col: col["dev"] = i
                elif "publisher" in h and "pub" not in col: col["pub"] = i
                elif "platform" in h and "plat" not in col: col["plat"] = i
                elif ("date" in h or "release" in h) and "date" not in col: col["date"] = i
            if "title" not in col or "date" not in col: continue
            for row in rows[1:]:
                cells = row.find_all(["td","th"])
                if not cells: continue
                def ct(k):
                    i = col.get(k)
                    return cells[i].get_text(separator=" ",strip=True) \
                           if i is not None and i < len(cells) else ""
                title = ct("title"); dev = ct("dev"); pub = ct("pub")
                plat  = ct("plat"); dr  = ct("date")
                rel = pdate(dr, year)
                if not rel or not title: continue
                games.append({"title":title,"dev":dev,"pub":pub,
                              "plat":plat,"rel":rel,"url":url})
    except Exception as e:
        print(f"  [Games] {year}: {e}", file=sys.stderr)
    return games

def scrape_ubisoft_games():
    events = []; all_g = []
    for yr in [YEAR, YEAR+1]: all_g.extend(scrape_games_wiki(yr))
    seen = set()
    for g in all_g:
        if ("ubisoft" not in g["pub"].lower()
                and "ubisoft" not in g["dev"].lower()): continue
        k = g["title"].lower()
        if k in seen: continue
        seen.add(k)
        desc = f"Developer: {g['dev']}\nPublisher: {g['pub']}"
        if g["plat"]: desc += f"\nPlatforms: {g['plat']}"
        events.append(Evt(name=f"{g['title']} -- Launch Day", sport="Ubisoft",
            start=g["rel"], end=g["rel"], url=g["url"], description=desc))
    print(f"  [Ubisoft] {len(events)} releases")
    return events

def scrape_aaa_games():
    events = []; all_g = []
    for yr in [YEAR, YEAR+1]: all_g.extend(scrape_games_wiki(yr))
    cands = []
    for g in all_g:
        pl = g["plat"].lower()
        is_aaa = any(p in g["pub"].lower() or p in g["dev"].lower()
                     for p in AAA_PUBLISHERS)
        is_multi = (("pc" in pl or "windows" in pl)
                    and any(p in pl for p in ["playstation","xbox","ps5","ps4","series"]))
        if is_aaa and is_multi: cands.append(g)
    cands.sort(key=lambda g: g["rel"]); cands = cands[:25]
    seen = set()
    for g in cands:
        k = g["title"].lower()
        if k in seen: continue
        seen.add(k)
        desc = f"Publisher: {g['pub']}"
        if g["dev"] and g["dev"] != g["pub"]: desc += f"\nDeveloper: {g['dev']}"
        if g["plat"]: desc += f"\nPlatforms: {g['plat']}"
        events.append(Evt(name=f"{g['title']} -- Release Day", sport="AAA Games",
            start=g["rel"], end=g["rel"], url=g["url"], description=desc))
    print(f"  [AAA Games] {len(events)} releases")
    return events

# ---------------------------------------------------------------------------
# ICS builder -- all-day for events without start_dt, timed otherwise
# ---------------------------------------------------------------------------
def build_ics(events):
    cal = Calendar()
    cal.add("prodid", "-//Big Events Calendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Big Events")
    cal.add("x-wr-caldesc",
        "F1 · Tennis Grand Slams · UFC · NFL Bears · NBA · NHL Canadiens"
        " · Rocket League · FIFA World Cup 2026 · Ubisoft · AAA Games")
    cal.add("x-wr-timezone", "UTC")
    cal.add("refresh-interval;value=duration", "P1D")
    cal.add("x-published-ttl", "PT12H")

    seen = set(); unique = []
    for e in events:
        k = (e.name.lower().strip(), e.start)
        if k not in seen: seen.add(k); unique.append(e)
    unique.sort(key=lambda x: x.start)

    for e in unique:
        ev = Event()
        ev.add("uid", f"{uuid.uuid4()}@big-events")
        ev.add("summary", e.summary)
        if e.start_dt:
            ev.add("dtstart", e.start_dt)
            ev.add("dtend", e.start_dt + timedelta(hours=3))
        else:
            ev.add("dtstart", e.start)
            ev.add("dtend", e.end + timedelta(1))
        if e.location:    ev.add("location", e.location)
        if e.url:         ev.add("url", e.url)
        if e.description: ev.add("description", e.description)
        cal.add_component(ev)

    return cal.to_ical()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    print("Fetching events…")
    all_events = []
    scrapers = [
        scrape_f1, scrape_tennis, scrape_ufc,
        scrape_nfl_bears, scrape_nba, scrape_nhl_habs,
        scrape_rocket_league, scrape_world_cup,
        scrape_ubisoft_games, scrape_aaa_games,
    ]
    for fn in scrapers:
        try:
            all_events.extend(fn())
        except Exception as exc:
            print(f"  [{fn.__name__}] FAILED: {exc}", file=sys.stderr)

    ics = build_ics(all_events)
    out = Path("big_events.ics")
    out.write_bytes(ics)
    print(f"Wrote {out} ({out.stat().st_size} bytes, {len(all_events)} raw events)")

if __name__ == "__main__":
    main()
