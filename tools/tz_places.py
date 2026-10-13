#!/usr/bin/env python3
"""tz_places.py -- the places a lead can name, as IANA time zones. Data only; tools/send_window.py reads it.

The owner, 2026-10-12: "I want you to send mails to the sender's time region between 10 to 10:30AM".
Read as the RECIPIENT's 10:00 (10:00 in Mumbai is 05:30 in London), so every email needs the zone its
reader keeps -- and a lead names its place in whatever shape its source used: ISO codes (Wikidata,
OpenStreetMap, the FDIC, YouTube), country names (Apollo: "United States", "United Kingdom"), US state
codes (FDIC STALP "TX", AICP "CA") and names (Apollo "Texas", "England"), cities, phone numbers.

FROM THE tzdata PACKAGE (requirements.txt), never the machine: zone.tab (each country's zones) and
iso3166.tab (each code's English name). Windows has no system zone files and the slim image's are not
the ones tested, so both read the same package (the Dockerfile sets PYTHONTZPATH="").

  SINGLE_ZONE    {ISO2: zone} for a country with one zone           (zone.tab)
  ZONE_COUNTRY   {zone: ISO2}                                        (zone.tab)
  COUNTRY_ZONES  {ISO2: [zones]}                                     (zone.tab)
  COUNTRY_NAMES  {folded name: ISO2}: iso3166.tab's names, their bracket-free forms when unambiguous,
                 and ALIASES

BY HAND (every key goes through fold(), so "São Paulo", "SAO PAULO" and "Sao Paulo" are one key):

  ALIASES        the other ways a country is written: Apollo's "United States", "England", "UAE" ...
  SHORT_NAME     how a label says a country ("US", "UK", "UAE"); otherwise iso3166's name, brackets off
  MAIN_ZONE      the business zone of a country with several (US New York, AU Sydney, RU Moscow ...),
                 used when nothing held says which part of it
  REGIONS        {ISO2: {code or name: zone}} for the countries where the state decides the zone: US,
                 CA, AU, BR, MX, RU, ID, ES, PT. A state is read only inside its own country: "IN" is
                 Indiana in the US and means nothing in India; "WA" is Washington or Western Australia
  REGION_CODE    {ISO2: {code or name: code}}: the one code each region is known by
  CITY_OVERRIDES {ISO2: {"city|state code": zone}}: the cities whose zone is not their state's (El Paso
                 keeps Mountain time inside Central Texas, Pensacola Central inside Eastern Florida).
                 Keyed by the state as well (override_key), because a city name alone repeats across
                 states: Milton FL is Central, Milton MA is not. Without a state, CITY_HINTS decide
  CITY_HINTS     {ISO2: {city: zone}}: the zone a well-known city gives when no state is held
  NANP           {area code: (ISO2, region code or None)}: North American numbers. Toll-free codes (800,
                 833, 844, 855, 866, 877, 888) and non-geographic ones are left out: they say nothing
                 about where the reader sits
  NANP_ZONE      {area code: zone} for the few area codes whose zone is not their state's
  DIAL           {country calling code: ISO2} for every other number: a country, never a region
"""
import re
import unicodedata

# ------------------------------------------------------------------ folding
_TRANSLIT = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "đ": "d",
                           "Đ": "d", "ł": "l", "Ł": "l", "ı": "i", "ß": "ss", "þ": "th", "ð": "d"})


def fold(s):
    """Accent-free, case-folded, punctuation as single spaces, apostrophes dropped, "saint" as "st":
    "St. John's" / "Saint Johns" -> "st johns"; "São Paulo" -> "sao paulo"; "Trinidad & Tobago" ->
    "trinidad and tobago"."""
    s = unicodedata.normalize("NFKD", str(s or "").translate(_TRANSLIT))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = re.sub(r"['’‘`´]", "", s).replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bft\b", "fort", s)
    s = re.sub(r"\bmt\b", "mount", s)
    return s


# ------------------------------------------------------------ from tzdata
LOAD_ERROR = None
SINGLE_ZONE, ZONE_COUNTRY, COUNTRY_ZONES, ISO_NAME = {}, {}, {}, {}
try:
    from importlib import resources as _res
    _tab = _res.files("tzdata").joinpath("zoneinfo/zone.tab").read_text(encoding="utf-8")
    _iso = _res.files("tzdata").joinpath("zoneinfo/iso3166.tab").read_text(encoding="utf-8")
    for _line in _tab.splitlines():
        if _line.startswith("#") or not _line.strip():
            continue
        _cc, _coord, _zone = _line.split("\t")[:3]
        COUNTRY_ZONES.setdefault(_cc, []).append(_zone)
        ZONE_COUNTRY.setdefault(_zone, _cc)
    for _line in _iso.splitlines():
        if _line.startswith("#") or not _line.strip():
            continue
        _cc, _name = _line.split("\t")[:2]
        ISO_NAME[_cc] = _name.strip()
    SINGLE_ZONE = {c: z[0] for c, z in COUNTRY_ZONES.items() if len(z) == 1}
except Exception as _e:                     # noqa: BLE001 -- send_window.self_check() names the fix
    LOAD_ERROR = "%s: %s" % (type(_e).__name__, _e)


def _bare(name):
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


# ------------------------------------------------------------------ by hand
ALIASES = {
    # the United States, as Apollo and people write it
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US", "u s": "US",
    "u s a": "US", "america": "US", "the united states": "US",
    # the United Kingdom: Apollo's people say "United Kingdom" with the state "England"; some records put
    # the nation where the country goes
    "united kingdom": "GB", "uk": "GB", "u k": "GB", "great britain": "GB", "britain": "GB", "gb": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB", "gbr": "GB",
    "united kingdom of great britain and northern ireland": "GB",
    "united arab emirates": "AE", "uae": "AE", "u a e": "AE", "are": "AE", "emirates": "AE",
    "india": "IN", "ind": "IN", "bharat": "IN",
    "south korea": "KR", "korea": "KR", "republic of korea": "KR", "korea republic of": "KR",
    "korea south": "KR", "north korea": "KP", "korea north": "KP",
    "russia": "RU", "russian federation": "RU",
    "czechia": "CZ", "czech republic": "CZ",
    "vietnam": "VN", "viet nam": "VN",
    "ivory coast": "CI", "cote divoire": "CI",
    "eswatini": "SZ", "swaziland": "SZ", "kingdom of eswatini": "SZ",
    "north macedonia": "MK", "macedonia": "MK",
    "myanmar": "MM", "burma": "MM",
    "holland": "NL", "the netherlands": "NL", "netherlands": "NL",
    "turkey": "TR", "turkiye": "TR", "republic of turkiye": "TR",
    "hong kong": "HK", "hong kong sar": "HK", "hong kong sar china": "HK",
    "macau": "MO", "macao": "MO",
    "taiwan": "TW", "republic of china": "TW", "chinese taipei": "TW",
    "china": "CN", "mainland china": "CN", "peoples republic of china": "CN", "prc": "CN",
    "democratic republic of the congo": "CD", "dr congo": "CD", "drc": "CD", "congo kinshasa": "CD",
    "republic of the congo": "CG", "congo brazzaville": "CG", "congo": "CG",
    "american samoa": "AS", "samoa": "WS", "western samoa": "WS",
    "british virgin islands": "VG", "us virgin islands": "VI", "united states virgin islands": "VI",
    "u s virgin islands": "VI",
    "st martin": "MF", "sint maarten": "SX", "st maarten": "SX",
    "curacao": "CW", "reunion": "RE", "aland islands": "AX", "aland": "AX",
    "cape verde": "CV", "cabo verde": "CV",
    "east timor": "TL", "timor leste": "TL",
    "vatican": "VA", "holy see": "VA", "vatican city": "VA",
    "palestine": "PS", "state of palestine": "PS", "palestinian territories": "PS",
    "laos": "LA", "lao pdr": "LA", "brunei": "BN", "brunei darussalam": "BN",
    "syria": "SY", "syrian arab republic": "SY", "iran": "IR", "iran islamic republic of": "IR",
    "moldova": "MD", "republic of moldova": "MD", "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ",
    "micronesia": "FM", "federated states of micronesia": "FM",
    "bosnia": "BA", "bosnia and herzegovina": "BA", "trinidad and tobago": "TT",
    "st kitts and nevis": "KN", "st lucia": "LC", "st vincent and the grenadines": "VC", "st vincent": "VC",
    "sao tome and principe": "ST", "antigua and barbuda": "AG", "turks and caicos islands": "TC",
    "turks and caicos": "TC", "central african republic": "CF", "falkland islands": "FK",
    "the bahamas": "BS", "bahamas": "BS", "the gambia": "GM", "gambia": "GM",
    "puerto rico": "PR", "guam": "GU",
    # three-letter codes seen in exports
    "can": "CA", "aus": "AU", "deu": "DE", "fra": "FR", "sgp": "SG", "nzl": "NZ", "irl": "IE", "jpn": "JP",
    "chn": "CN", "bra": "BR", "mex": "MX", "esp": "ES", "ita": "IT", "zaf": "ZA", "nld": "NL",
    "che": "CH", "swe": "SE", "nor": "NO", "dnk": "DK", "fin": "FI",
}

SHORT_NAME = {
    "US": "US", "GB": "UK", "AE": "UAE", "IN": "India", "KR": "South Korea", "KP": "North Korea",
    "CD": "DR Congo", "CG": "Congo", "AS": "American Samoa", "WS": "Samoa", "VG": "British Virgin Islands",
    "VI": "US Virgin Islands", "MF": "St Martin", "SX": "Sint Maarten", "MM": "Myanmar", "SZ": "Eswatini",
    "CZ": "Czechia", "BA": "Bosnia and Herzegovina", "TT": "Trinidad and Tobago", "UM": "US Minor Islands",
    "CC": "Cocos Islands", "CF": "Central African Republic", "TC": "Turks and Caicos",
}

# The business zone of a country with several: where its companies and offices mostly keep time.
MAIN_ZONE = {
    "US": "America/New_York", "CA": "America/Toronto", "AU": "Australia/Sydney", "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City", "RU": "Europe/Moscow", "ID": "Asia/Jakarta", "KZ": "Asia/Almaty",
    "AR": "America/Argentina/Buenos_Aires", "CL": "America/Santiago", "CN": "Asia/Shanghai",
    "CD": "Africa/Kinshasa", "CY": "Asia/Nicosia", "DE": "Europe/Berlin", "EC": "America/Guayaquil",
    "ES": "Europe/Madrid", "PT": "Europe/Lisbon", "NZ": "Pacific/Auckland", "MN": "Asia/Ulaanbaatar",
    "MY": "Asia/Kuala_Lumpur", "UA": "Europe/Kyiv", "UZ": "Asia/Tashkent", "PG": "Pacific/Port_Moresby",
    "PS": "Asia/Hebron", "GL": "America/Nuuk", "FM": "Pacific/Pohnpei", "KI": "Pacific/Tarawa",
    "MH": "Pacific/Majuro", "PF": "Pacific/Tahiti",
}

# (code, name and other names separated by "|", zone). The code is what REGION_CODE gives back.
_NY, _CHI, _DEN, _PHX, _LA = "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", \
    "America/Los_Angeles"
_REGION_ROWS = {
    "US": [
        ("AL", "Alabama", _CHI), ("AK", "Alaska", "America/Anchorage"), ("AZ", "Arizona", _PHX),
        ("AR", "Arkansas", _CHI), ("CA", "California", _LA), ("CO", "Colorado", _DEN),
        ("CT", "Connecticut", _NY), ("DE", "Delaware", _NY),
        ("DC", "District of Columbia|Washington DC|Washington D.C.", _NY),
        ("FL", "Florida", _NY), ("GA", "Georgia", _NY), ("HI", "Hawaii", "Pacific/Honolulu"),
        ("ID", "Idaho", "America/Boise"), ("IL", "Illinois", _CHI),
        ("IN", "Indiana", "America/Indiana/Indianapolis"), ("IA", "Iowa", _CHI), ("KS", "Kansas", _CHI),
        ("KY", "Kentucky", _NY), ("LA", "Louisiana", _CHI), ("ME", "Maine", _NY),
        ("MD", "Maryland", _NY), ("MA", "Massachusetts", _NY), ("MI", "Michigan", "America/Detroit"),
        ("MN", "Minnesota", _CHI), ("MS", "Mississippi", _CHI), ("MO", "Missouri", _CHI),
        ("MT", "Montana", _DEN), ("NE", "Nebraska", _CHI), ("NV", "Nevada", _LA),
        ("NH", "New Hampshire", _NY), ("NJ", "New Jersey", _NY), ("NM", "New Mexico", _DEN),
        ("NY", "New York|New York State", _NY), ("NC", "North Carolina", _NY), ("ND", "North Dakota", _CHI),
        ("OH", "Ohio", _NY), ("OK", "Oklahoma", _CHI), ("OR", "Oregon", _LA), ("PA", "Pennsylvania", _NY),
        ("RI", "Rhode Island", _NY), ("SC", "South Carolina", _NY), ("SD", "South Dakota", _CHI),
        ("TN", "Tennessee", _CHI), ("TX", "Texas", _CHI), ("UT", "Utah", _DEN), ("VT", "Vermont", _NY),
        ("VA", "Virginia", _NY), ("WA", "Washington|Washington State", _LA),
        ("WV", "West Virginia", _NY), ("WI", "Wisconsin", _CHI), ("WY", "Wyoming", _DEN),
        ("PR", "Puerto Rico", "America/Puerto_Rico"), ("GU", "Guam", "Pacific/Guam"),
        ("VI", "Virgin Islands|US Virgin Islands|U.S. Virgin Islands", "America/St_Thomas"),
        ("AS", "American Samoa", "Pacific/Pago_Pago"), ("MP", "Northern Mariana Islands", "Pacific/Saipan"),
    ],
    "CA": [
        ("AB", "Alberta", "America/Edmonton"), ("BC", "British Columbia", "America/Vancouver"),
        ("MB", "Manitoba", "America/Winnipeg"), ("NB", "New Brunswick", "America/Moncton"),
        ("NL", "Newfoundland and Labrador|Newfoundland|Labrador", "America/St_Johns"),
        ("NS", "Nova Scotia", "America/Halifax"), ("NT", "Northwest Territories", "America/Edmonton"),
        ("NU", "Nunavut", "America/Iqaluit"), ("ON", "Ontario", "America/Toronto"),
        ("PE", "Prince Edward Island|PEI", "America/Halifax"),
        ("QC", "Quebec|Québec|PQ", "America/Toronto"), ("SK", "Saskatchewan", "America/Regina"),
        ("YT", "Yukon|Yukon Territory", "America/Whitehorse"),
    ],
    "AU": [
        ("NSW", "New South Wales", "Australia/Sydney"), ("VIC", "Victoria", "Australia/Melbourne"),
        ("QLD", "Queensland", "Australia/Brisbane"), ("SA", "South Australia", "Australia/Adelaide"),
        ("WA", "Western Australia", "Australia/Perth"), ("TAS", "Tasmania", "Australia/Hobart"),
        ("NT", "Northern Territory", "Australia/Darwin"),
        ("ACT", "Australian Capital Territory", "Australia/Sydney"),
    ],
    "BR": [
        ("AC", "Acre", "America/Rio_Branco"), ("AL", "Alagoas", "America/Maceio"),
        ("AP", "Amapá", "America/Belem"), ("AM", "Amazonas", "America/Manaus"),
        ("BA", "Bahia", "America/Bahia"), ("CE", "Ceará", "America/Fortaleza"),
        ("DF", "Distrito Federal|Federal District", "America/Sao_Paulo"),
        ("ES", "Espírito Santo", "America/Sao_Paulo"), ("GO", "Goiás", "America/Sao_Paulo"),
        ("MA", "Maranhão", "America/Fortaleza"), ("MT", "Mato Grosso", "America/Cuiaba"),
        ("MS", "Mato Grosso do Sul", "America/Campo_Grande"), ("MG", "Minas Gerais", "America/Sao_Paulo"),
        ("PA", "Pará", "America/Belem"), ("PB", "Paraíba", "America/Fortaleza"),
        ("PR", "Paraná", "America/Sao_Paulo"), ("PE", "Pernambuco", "America/Recife"),
        ("PI", "Piauí", "America/Fortaleza"), ("RJ", "Rio de Janeiro", "America/Sao_Paulo"),
        ("RN", "Rio Grande do Norte", "America/Fortaleza"), ("RS", "Rio Grande do Sul", "America/Sao_Paulo"),
        ("RO", "Rondônia", "America/Porto_Velho"), ("RR", "Roraima", "America/Boa_Vista"),
        ("SC", "Santa Catarina", "America/Sao_Paulo"), ("SP", "São Paulo|State of São Paulo", "America/Sao_Paulo"),
        ("SE", "Sergipe", "America/Maceio"), ("TO", "Tocantins", "America/Araguaina"),
    ],
    "MX": [
        ("AGU", "Aguascalientes", "America/Mexico_City"), ("BCN", "Baja California", "America/Tijuana"),
        ("BCS", "Baja California Sur", "America/Mazatlan"), ("CAM", "Campeche", "America/Merida"),
        ("CHP", "Chiapas", "America/Mexico_City"), ("CHH", "Chihuahua", "America/Chihuahua"),
        ("CMX", "Ciudad de México|Mexico City|CDMX|Distrito Federal|Federal District", "America/Mexico_City"),
        ("COA", "Coahuila|Coahuila de Zaragoza", "America/Monterrey"), ("COL", "Colima", "America/Mexico_City"),
        ("DUR", "Durango", "America/Monterrey"), ("GUA", "Guanajuato", "America/Mexico_City"),
        ("GRO", "Guerrero", "America/Mexico_City"), ("HID", "Hidalgo", "America/Mexico_City"),
        ("JAL", "Jalisco", "America/Mexico_City"),
        ("MEX", "México|State of Mexico|Estado de México|Mexico State", "America/Mexico_City"),
        ("MIC", "Michoacán|Michoacán de Ocampo", "America/Mexico_City"), ("MOR", "Morelos", "America/Mexico_City"),
        ("NAY", "Nayarit", "America/Mazatlan"), ("NLE", "Nuevo León", "America/Monterrey"),
        ("OAX", "Oaxaca", "America/Mexico_City"), ("PUE", "Puebla", "America/Mexico_City"),
        ("QUE", "Querétaro", "America/Mexico_City"), ("ROO", "Quintana Roo", "America/Cancun"),
        ("SLP", "San Luis Potosí", "America/Mexico_City"), ("SIN", "Sinaloa", "America/Mazatlan"),
        ("SON", "Sonora", "America/Hermosillo"), ("TAB", "Tabasco", "America/Mexico_City"),
        ("TAM", "Tamaulipas", "America/Monterrey"), ("TLA", "Tlaxcala", "America/Mexico_City"),
        ("VER", "Veracruz|Veracruz de Ignacio de la Llave", "America/Mexico_City"),
        ("YUC", "Yucatán", "America/Merida"), ("ZAC", "Zacatecas", "America/Mexico_City"),
    ],
    "RU": [
        ("MOW", "Moscow|Moskva|Moscow City", "Europe/Moscow"), ("MOS", "Moscow Oblast", "Europe/Moscow"),
        ("SPE", "Saint Petersburg|Sankt-Peterburg", "Europe/Moscow"), ("LEN", "Leningrad Oblast", "Europe/Moscow"),
        ("TA", "Tatarstan", "Europe/Moscow"), ("NIZ", "Nizhny Novgorod Oblast", "Europe/Moscow"),
        ("KDA", "Krasnodar Krai", "Europe/Moscow"), ("ROS", "Rostov Oblast", "Europe/Moscow"),
        ("KGD", "Kaliningrad Oblast|Kaliningrad", "Europe/Kaliningrad"),
        ("SAM", "Samara Oblast", "Europe/Samara"), ("UD", "Udmurtia|Udmurt Republic", "Europe/Samara"),
        ("SAR", "Saratov Oblast", "Europe/Saratov"), ("ULY", "Ulyanovsk Oblast", "Europe/Ulyanovsk"),
        ("AST", "Astrakhan Oblast", "Europe/Astrakhan"), ("VGG", "Volgograd Oblast", "Europe/Volgograd"),
        ("KIR", "Kirov Oblast", "Europe/Kirov"),
        ("SVE", "Sverdlovsk Oblast", "Asia/Yekaterinburg"), ("CHE", "Chelyabinsk Oblast", "Asia/Yekaterinburg"),
        ("BA", "Bashkortostan", "Asia/Yekaterinburg"), ("PER", "Perm Krai", "Asia/Yekaterinburg"),
        ("TYU", "Tyumen Oblast", "Asia/Yekaterinburg"), ("ORE", "Orenburg Oblast", "Asia/Yekaterinburg"),
        ("KGN", "Kurgan Oblast", "Asia/Yekaterinburg"),
        ("KHM", "Khanty-Mansi Autonomous Okrug|Khanty-Mansiysk", "Asia/Yekaterinburg"),
        ("YAN", "Yamalo-Nenets Autonomous Okrug", "Asia/Yekaterinburg"),
        ("OMS", "Omsk Oblast", "Asia/Omsk"), ("NVS", "Novosibirsk Oblast", "Asia/Novosibirsk"),
        ("ALT", "Altai Krai", "Asia/Barnaul"), ("AL", "Altai Republic", "Asia/Barnaul"),
        ("TOM", "Tomsk Oblast", "Asia/Tomsk"), ("KEM", "Kemerovo Oblast|Kuzbass", "Asia/Novokuznetsk"),
        ("KYA", "Krasnoyarsk Krai", "Asia/Krasnoyarsk"), ("KK", "Khakassia", "Asia/Krasnoyarsk"),
        ("TY", "Tuva", "Asia/Krasnoyarsk"), ("IRK", "Irkutsk Oblast", "Asia/Irkutsk"),
        ("BU", "Buryatia", "Asia/Irkutsk"), ("ZAB", "Zabaykalsky Krai", "Asia/Chita"),
        ("SA", "Sakha|Yakutia|Sakha Republic", "Asia/Yakutsk"), ("AMU", "Amur Oblast", "Asia/Yakutsk"),
        ("PRI", "Primorsky Krai|Primorye", "Asia/Vladivostok"), ("KHA", "Khabarovsk Krai", "Asia/Vladivostok"),
        ("YEV", "Jewish Autonomous Oblast", "Asia/Vladivostok"), ("MAG", "Magadan Oblast", "Asia/Magadan"),
        ("SAK", "Sakhalin Oblast", "Asia/Sakhalin"), ("KAM", "Kamchatka Krai", "Asia/Kamchatka"),
        ("CHU", "Chukotka Autonomous Okrug|Chukotka", "Asia/Anadyr"),
    ],
    "ID": [
        ("AC", "Aceh", "Asia/Jakarta"), ("SU", "North Sumatra|Sumatera Utara", "Asia/Jakarta"),
        ("SB", "West Sumatra|Sumatera Barat", "Asia/Jakarta"), ("RI", "Riau", "Asia/Jakarta"),
        ("KR", "Riau Islands|Kepulauan Riau", "Asia/Jakarta"), ("JA", "Jambi", "Asia/Jakarta"),
        ("BE", "Bengkulu", "Asia/Jakarta"), ("SS", "South Sumatra|Sumatera Selatan", "Asia/Jakarta"),
        ("BB", "Bangka Belitung|Bangka Belitung Islands|Kepulauan Bangka Belitung", "Asia/Jakarta"),
        ("LA", "Lampung", "Asia/Jakarta"), ("BT", "Banten", "Asia/Jakarta"),
        ("JK", "Jakarta|DKI Jakarta|Special Capital Region of Jakarta", "Asia/Jakarta"),
        ("JB", "West Java|Jawa Barat", "Asia/Jakarta"), ("JT", "Central Java|Jawa Tengah", "Asia/Jakarta"),
        ("YO", "Yogyakarta|DI Yogyakarta|Special Region of Yogyakarta", "Asia/Jakarta"),
        ("JI", "East Java|Jawa Timur", "Asia/Jakarta"),
        ("KB", "West Kalimantan|Kalimantan Barat", "Asia/Pontianak"),
        ("KT", "Central Kalimantan|Kalimantan Tengah", "Asia/Pontianak"),
        ("KS", "South Kalimantan|Kalimantan Selatan", "Asia/Makassar"),
        ("KI", "East Kalimantan|Kalimantan Timur", "Asia/Makassar"),
        ("KU", "North Kalimantan|Kalimantan Utara", "Asia/Makassar"), ("BA", "Bali", "Asia/Makassar"),
        ("NB", "West Nusa Tenggara|Nusa Tenggara Barat", "Asia/Makassar"),
        ("NT", "East Nusa Tenggara|Nusa Tenggara Timur", "Asia/Makassar"),
        ("SA", "North Sulawesi|Sulawesi Utara", "Asia/Makassar"),
        ("ST", "Central Sulawesi|Sulawesi Tengah", "Asia/Makassar"),
        ("SN", "South Sulawesi|Sulawesi Selatan", "Asia/Makassar"),
        ("SG", "Southeast Sulawesi|Sulawesi Tenggara", "Asia/Makassar"),
        ("SR", "West Sulawesi|Sulawesi Barat", "Asia/Makassar"), ("GO", "Gorontalo", "Asia/Makassar"),
        ("MA", "Maluku", "Asia/Jayapura"), ("MU", "North Maluku|Maluku Utara", "Asia/Jayapura"),
        ("PA", "Papua", "Asia/Jayapura"), ("PB", "West Papua|Papua Barat", "Asia/Jayapura"),
        ("PS", "South Papua|Papua Selatan", "Asia/Jayapura"), ("PT", "Central Papua|Papua Tengah", "Asia/Jayapura"),
        ("PE", "Highland Papua|Papua Pegunungan", "Asia/Jayapura"),
        ("PD", "Southwest Papua|Papua Barat Daya", "Asia/Jayapura"),
    ],
    "ES": [
        ("CN", "Canary Islands|Canarias|Islas Canarias|Las Palmas|Santa Cruz de Tenerife", "Atlantic/Canary"),
        ("CE", "Ceuta", "Africa/Ceuta"), ("ML", "Melilla", "Africa/Ceuta"),
        ("AN", "Andalusia|Andalucía", "Europe/Madrid"), ("AR", "Aragon|Aragón", "Europe/Madrid"),
        ("AS", "Asturias|Principality of Asturias", "Europe/Madrid"),
        ("IB", "Balearic Islands|Illes Balears|Islas Baleares", "Europe/Madrid"),
        ("PV", "Basque Country|País Vasco|Euskadi", "Europe/Madrid"), ("CB", "Cantabria", "Europe/Madrid"),
        ("CL", "Castile and León|Castilla y León", "Europe/Madrid"),
        ("CM", "Castilla-La Mancha|Castile-La Mancha", "Europe/Madrid"),
        ("CT", "Catalonia|Cataluña|Catalunya", "Europe/Madrid"), ("EX", "Extremadura", "Europe/Madrid"),
        ("GA", "Galicia", "Europe/Madrid"), ("RI", "La Rioja", "Europe/Madrid"),
        ("MD", "Community of Madrid|Comunidad de Madrid|Madrid", "Europe/Madrid"),
        ("MC", "Murcia|Region of Murcia|Región de Murcia", "Europe/Madrid"),
        ("NC", "Navarre|Navarra", "Europe/Madrid"),
        ("VC", "Valencian Community|Comunidad Valenciana|Comunitat Valenciana|Valencia", "Europe/Madrid"),
    ],
    "PT": [
        ("20", "Azores|Açores|Autonomous Region of the Azores", "Atlantic/Azores"),
        ("30", "Madeira|Autonomous Region of Madeira", "Atlantic/Madeira"),
        ("11", "Lisbon|Lisboa|Lisbon District", "Europe/Lisbon"), ("13", "Porto|Porto District", "Europe/Lisbon"),
        ("08", "Faro|Algarve", "Europe/Lisbon"), ("03", "Braga", "Europe/Lisbon"),
        ("15", "Setúbal", "Europe/Lisbon"), ("06", "Coimbra", "Europe/Lisbon"), ("01", "Aveiro", "Europe/Lisbon"),
        ("10", "Leiria", "Europe/Lisbon"),
    ],
}

REGIONS, REGION_CODE = {}, {}
for _cc, _rows in _REGION_ROWS.items():
    for _code, _names, _zone in _rows:
        for _k in [_code] + _names.split("|"):
            REGIONS.setdefault(_cc, {})[fold(_k)] = _zone
            REGION_CODE.setdefault(_cc, {})[fold(_k)] = _code

def override_key(city, region_code):
    """CITY_OVERRIDES' key: the city and its state's code, folded -- "el paso|tx"."""
    return "%s|%s" % (fold(city), fold(region_code))


# Cities whose zone is not their state's, by country, city and state code.
_O = {
    "US": [
        (_DEN, "TX", "El Paso|Horizon City|Socorro|Canutillo|Anthony|Fabens|Van Horn|Sierra Blanca|Dell City"),
        (_CHI, "FL", "Pensacola|Panama City|Panama City Beach|Fort Walton Beach|Destin|Crestview|Navarre|"
                     "Niceville|Milton|Gulf Breeze|DeFuniak Springs|Marianna|Chipley|Lynn Haven|Mary Esther|"
                     "Santa Rosa Beach|Miramar Beach|Pace|Callaway"),
        (_CHI, "IN", "Gary|Hammond|East Chicago|Merrillville|Crown Point|Valparaiso|Portage|Michigan City|"
                     "La Porte|LaPorte|Schererville|Munster|Highland|Hobart|Griffith|Dyer|St John|Chesterton|"
                     "Lake Station|Cedar Lake|Evansville|Newburgh|Boonville|Mount Vernon|Princeton|Tell City|"
                     "Rensselaer|Knox"),
        (_CHI, "KY", "Bowling Green|Paducah|Owensboro|Hopkinsville|Henderson|Madisonville|Murray|Glasgow|"
                     "Mayfield|Russellville|Franklin|Princeton|Fort Campbell"),
        (_NY, "TN", "Knoxville|Chattanooga|Johnson City|Kingsport|Bristol|Cleveland|Morristown|Oak Ridge|"
                    "Maryville|Athens|Greeneville|Elizabethton|Sevierville|Gatlinburg|Pigeon Forge|Farragut|"
                    "Alcoa|Collegedale"),
        ("America/Menominee", "MI", "Menominee|Iron Mountain|Ironwood|Kingsford|Iron River|Norway"),
        (_DEN, "ND", "Dickinson|Beach|Bowman|Hettinger|Mott|New England"),
        (_DEN, "SD", "Rapid City|Spearfish|Sturgis|Belle Fourche|Custer|Hot Springs|Lead|Deadwood|Box Elder|"
                     "Hill City|Wall"),
        (_DEN, "NE", "Scottsbluff|Gering|Alliance|Sidney|Chadron|Kimball|Ogallala|Mitchell|Bridgeport"),
        (_DEN, "KS", "Goodland|Sharon Springs|Tribune|Syracuse|Saint Francis"),
        ("America/Boise", "OR", "Ontario|Nyssa|Vale"),
        (_LA, "ID", "Coeur d'Alene|Lewiston|Moscow|Post Falls|Sandpoint|Hayden|Rathdrum|Grangeville|"
                    "Bonners Ferry|Kellogg|Orofino"),
        (_DEN, "NV", "West Wendover|Jackpot"),
        (_DEN, "AZ", "Window Rock|Tuba City|Kayenta|Chinle|Ganado"),
        ("America/Adak", "AK", "Adak"),
    ],
    "CA": [
        ("America/Edmonton", "BC", "Cranbrook|Fernie|Invermere|Golden|Kimberley|Sparwood"),
        ("America/Dawson_Creek", "BC", "Dawson Creek|Fort St John|Chetwynd"),
        ("America/Fort_Nelson", "BC", "Fort Nelson"), ("America/Creston", "BC", "Creston"),
        ("America/Winnipeg", "ON", "Kenora|Dryden|Fort Frances|Sioux Lookout|Red Lake"),
        ("America/Edmonton", "SK", "Lloydminster"),
        ("America/Halifax", "QC", "Iles de la Madeleine|Magdalen Islands"),
        ("America/Blanc-Sablon", "QC", "Blanc-Sablon"),
        ("America/Goose_Bay", "NL", "Happy Valley-Goose Bay|Goose Bay|Labrador City|Wabush"),
        ("America/Rankin_Inlet", "NU", "Rankin Inlet"), ("America/Cambridge_Bay", "NU", "Cambridge Bay"),
    ],
    "AU": [
        ("Australia/Broken_Hill", "NSW", "Broken Hill"), ("Australia/Lord_Howe", "NSW", "Lord Howe Island"),
        ("Australia/Eucla", "WA", "Eucla"),
    ],
    "MX": [
        ("America/Matamoros", "TAM", "Matamoros|Nuevo Laredo|Reynosa|Rio Bravo|Valle Hermoso"),
        ("America/Matamoros", "COA", "Piedras Negras|Ciudad Acuna|Acuna"),
        ("America/Ciudad_Juarez", "CHH", "Ciudad Juarez|Juarez"), ("America/Ojinaga", "CHH", "Ojinaga"),
        ("America/Bahia_Banderas", "NAY", "Bahia de Banderas|Nuevo Vallarta|Bucerias"),
    ],
    "BR": [
        ("America/Eirunepe", "AM", "Eirunepe"), ("America/Santarem", "PA", "Santarem"),
        ("America/Noronha", "PE", "Fernando de Noronha"),
    ],
}
CITY_OVERRIDES = {}
for _cc, _rows in _O.items():
    for _zone, _region, _cities in _rows:
        for _c in _cities.split("|"):
            CITY_OVERRIDES.setdefault(_cc, {})[override_key(_c, _region)] = _zone

# The zone a well-known city gives when no state is held. Ambiguous names (Portland, Springfield, Arlington)
# take the one most companies mean.
_H = {
    "US": [
        (_NY, "New York|New York City|NYC|Manhattan|Brooklyn|Queens|Bronx|The Bronx|Staten Island|Long Island City|"
              "Boston|Cambridge|Philadelphia|Washington|Washington DC|Washington D.C.|Atlanta|Miami|Miami Beach|"
              "Orlando|Tampa|Jacksonville|Tallahassee|Fort Lauderdale|West Palm Beach|Boca Raton|Charlotte|"
              "Raleigh|Durham|Pittsburgh|Baltimore|Cleveland|Columbus|Cincinnati|Buffalo|Rochester|Albany|"
              "Newark|Jersey City|Hoboken|Stamford|Hartford|New Haven|Providence|Richmond|Virginia Beach|"
              "Norfolk|Arlington|Alexandria|Reston|Charleston|Greenville|Savannah|Louisville|Lexington|"
              "Wilmington|Burlington|Portsmouth"),
        ("America/Detroit", "Detroit|Ann Arbor|Grand Rapids|Lansing|Troy|Southfield|Dearborn"),
        ("America/Indiana/Indianapolis", "Indianapolis|Carmel|Fishers|Fort Wayne|Bloomington|South Bend"),
        (_CHI, "Chicago|Evanston|Naperville|Houston|Dallas|Austin|San Antonio|Fort Worth|Plano|Irving|Frisco|"
               "Minneapolis|St Paul|St Louis|Kansas City|Milwaukee|Madison|Nashville|Memphis|New Orleans|"
               "Oklahoma City|Tulsa|Omaha|Lincoln|Des Moines|Wichita|Little Rock|Birmingham|Huntsville|Mobile|"
               "Baton Rouge|Jackson|Sioux Falls|Fargo|Lubbock|Corpus Christi|Waco"),
        (_DEN, "Denver|Boulder|Colorado Springs|Fort Collins|Aurora|Salt Lake City|Provo|Albuquerque|Santa Fe|"
               "Cheyenne|Billings|El Paso"),
        ("America/Boise", "Boise|Meridian|Nampa"),
        (_PHX, "Phoenix|Scottsdale|Tempe|Mesa|Chandler|Gilbert|Tucson|Flagstaff"),
        (_LA, "Los Angeles|LA|Hollywood|West Hollywood|Beverly Hills|Santa Monica|Venice|Culver City|Burbank|"
              "Glendale|Pasadena|Sherman Oaks|Studio City|Encino|North Hollywood|Van Nuys|Long Beach|Irvine|"
              "Santa Ana|Anaheim|Torrance|El Segundo|Manhattan Beach|San Diego|San Francisco|Oakland|Berkeley|"
              "San Jose|Palo Alto|Mountain View|Menlo Park|Redwood City|Sunnyvale|Santa Clara|Cupertino|"
              "Sacramento|Fresno|Seattle|Bellevue|Redmond|Tacoma|Spokane|Portland|Las Vegas|Henderson|Reno"),
        ("America/Anchorage", "Anchorage|Juneau|Fairbanks"),
        ("Pacific/Honolulu", "Honolulu|Hilo|Kailua|Maui"),
        (_CHI, "Pensacola|Panama City|Evansville|Gary|Paducah|Owensboro|Bowling Green"),
        (_NY, "Knoxville|Chattanooga|Johnson City|Kingsport"),
        (_DEN, "Rapid City|Scottsbluff"),
        (_LA, "Coeur d'Alene"),
    ],
    "CA": [
        ("America/Toronto", "Toronto|Ottawa|Mississauga|Brampton|Hamilton|London|Markham|Vaughan|Kitchener|"
                            "Waterloo|Windsor|Oakville|Burlington|Kingston|Sudbury|Thunder Bay|Montreal|"
                            "Quebec City|Quebec|Laval|Gatineau|Longueuil|Sherbrooke|Trois-Rivieres"),
        ("America/Vancouver", "Vancouver|Victoria|Surrey|Burnaby|Richmond|Kelowna|Kamloops|Nanaimo|Abbotsford|"
                              "Coquitlam|North Vancouver|West Vancouver"),
        ("America/Edmonton", "Calgary|Edmonton|Red Deer|Lethbridge|Yellowknife"),
        ("America/Winnipeg", "Winnipeg|Brandon"), ("America/Regina", "Regina|Saskatoon"),
        ("America/Halifax", "Halifax|Dartmouth|Charlottetown|Sydney"),
        ("America/Moncton", "Moncton|Fredericton|Saint John"), ("America/St_Johns", "St Johns|St. John's"),
        ("America/Whitehorse", "Whitehorse"), ("America/Iqaluit", "Iqaluit"),
    ],
    "AU": [
        ("Australia/Sydney", "Sydney|Newcastle|Wollongong|Canberra|Parramatta|North Sydney"),
        ("Australia/Melbourne", "Melbourne|Geelong|Ballarat|Bendigo"),
        ("Australia/Brisbane", "Brisbane|Gold Coast|Sunshine Coast|Cairns|Townsville|Toowoomba"),
        ("Australia/Perth", "Perth|Fremantle"), ("Australia/Adelaide", "Adelaide"),
        ("Australia/Hobart", "Hobart|Launceston"), ("Australia/Darwin", "Darwin|Alice Springs"),
    ],
    "BR": [
        ("America/Sao_Paulo", "Sao Paulo|Campinas|Santos|Rio de Janeiro|Rio|Niteroi|Brasilia|Belo Horizonte|"
                              "Curitiba|Porto Alegre|Florianopolis|Goiania|Vitoria|Joinville|Ribeirao Preto"),
        ("America/Bahia", "Salvador"), ("America/Recife", "Recife|Olinda"),
        ("America/Fortaleza", "Fortaleza|Natal|Joao Pessoa|Teresina|Sao Luis"),
        ("America/Manaus", "Manaus"), ("America/Belem", "Belem|Macapa"), ("America/Cuiaba", "Cuiaba"),
        ("America/Campo_Grande", "Campo Grande"), ("America/Porto_Velho", "Porto Velho"),
        ("America/Maceio", "Maceio|Aracaju"), ("America/Araguaina", "Palmas"),
        ("America/Boa_Vista", "Boa Vista"), ("America/Rio_Branco", "Rio Branco"),
    ],
    "MX": [
        ("America/Mexico_City", "Mexico City|Ciudad de Mexico|CDMX|Guadalajara|Puebla|Queretaro|Leon|Toluca|"
                                "Puerto Vallarta|Aguascalientes|San Luis Potosi|Morelia|Veracruz|Oaxaca|Acapulco"),
        ("America/Monterrey", "Monterrey|San Pedro Garza Garcia|Saltillo|Torreon|Durango|Tampico"),
        ("America/Tijuana", "Tijuana|Mexicali|Ensenada"),
        ("America/Cancun", "Cancun|Playa del Carmen|Tulum|Chetumal"), ("America/Merida", "Merida|Campeche"),
        ("America/Hermosillo", "Hermosillo"), ("America/Chihuahua", "Chihuahua"),
        ("America/Mazatlan", "Mazatlan|Culiacan|La Paz|Los Cabos|Cabo San Lucas|San Jose del Cabo|Tepic"),
        ("America/Ciudad_Juarez", "Ciudad Juarez"), ("America/Matamoros", "Matamoros|Reynosa|Nuevo Laredo"),
    ],
    "RU": [
        ("Europe/Moscow", "Moscow|St Petersburg|Saint Petersburg|Kazan|Nizhny Novgorod|Krasnodar|Sochi|"
                          "Rostov-on-Don|Voronezh"),
        ("Europe/Kaliningrad", "Kaliningrad"), ("Europe/Samara", "Samara|Izhevsk"),
        ("Asia/Yekaterinburg", "Yekaterinburg|Chelyabinsk|Ufa|Perm|Tyumen"), ("Asia/Omsk", "Omsk"),
        ("Asia/Novosibirsk", "Novosibirsk"), ("Asia/Krasnoyarsk", "Krasnoyarsk"), ("Asia/Irkutsk", "Irkutsk"),
        ("Asia/Vladivostok", "Vladivostok|Khabarovsk"), ("Asia/Yakutsk", "Yakutsk"),
    ],
    "ID": [
        ("Asia/Jakarta", "Jakarta|Bandung|Surabaya|Semarang|Yogyakarta|Medan|Palembang|Tangerang|Bekasi|Depok|"
                         "Bogor|Batam|Malang|Pekanbaru"),
        ("Asia/Pontianak", "Pontianak"),
        ("Asia/Makassar", "Denpasar|Bali|Makassar|Balikpapan|Manado|Samarinda|Banjarmasin|Mataram|Kupang"),
        ("Asia/Jayapura", "Jayapura|Ambon|Sorong"),
    ],
    "ES": [
        ("Atlantic/Canary", "Las Palmas|Las Palmas de Gran Canaria|Santa Cruz de Tenerife|Tenerife|Gran Canaria"),
        ("Africa/Ceuta", "Ceuta|Melilla"),
        ("Europe/Madrid", "Madrid|Barcelona|Valencia|Seville|Sevilla|Bilbao|Malaga|Zaragoza|Palma"),
    ],
    "PT": [
        ("Atlantic/Azores", "Ponta Delgada"), ("Atlantic/Madeira", "Funchal"),
        ("Europe/Lisbon", "Lisbon|Lisboa|Porto|Braga|Coimbra|Faro"),
    ],
    "MY": [("Asia/Kuching", "Kuching|Kota Kinabalu|Miri|Sandakan")],
    "KZ": [("Asia/Almaty", "Almaty|Astana|Nur-Sultan|Shymkent")],
    "CN": [("Asia/Shanghai", "Shanghai|Beijing|Shenzhen|Guangzhou|Hangzhou|Chengdu")],
    "CL": [("America/Santiago", "Santiago|Valparaiso|Vina del Mar"), ("America/Punta_Arenas", "Punta Arenas")],
    "AR": [("America/Argentina/Buenos_Aires", "Buenos Aires"), ("America/Argentina/Cordoba", "Cordoba"),
           ("America/Argentina/Mendoza", "Mendoza")],
    "UA": [("Europe/Kyiv", "Kyiv|Kiev|Kharkiv|Lviv|Odesa|Odessa|Dnipro")],
    "NZ": [("Pacific/Auckland", "Auckland|Wellington|Christchurch")],
    "EC": [("America/Guayaquil", "Guayaquil|Quito")],
    "DE": [("Europe/Berlin", "Berlin|Munich|Hamburg|Frankfurt|Cologne")],
}
CITY_HINTS = {}
for _cc, _rows in _H.items():
    for _zone, _cities in _rows:
        for _c in _cities.split("|"):
            CITY_HINTS.setdefault(_cc, {})[fold(_c)] = _zone

# ----------------------------------------------------------- phone numbers
# North American area codes by state or province (as assigned to 2025, overlays included). Toll-free
# (800 833 844 855 866 877 888), premium (900) and non-geographic (500s, 600, 700) codes are left out.
_NANP_US = {
    "AL": "205 251 256 334 659 938", "AK": "907", "AZ": "480 520 602 623 928", "AR": "327 479 501 870",
    "CA": "209 213 279 310 323 341 350 369 408 415 424 442 510 530 559 562 619 626 628 650 657 661 669 707 "
          "714 747 760 805 818 820 831 840 858 909 916 925 949 951",
    "CO": "303 719 720 970 983", "CT": "203 475 860 959", "DE": "302", "DC": "202 771",
    "FL": "239 305 321 324 352 386 407 448 561 645 656 689 727 728 754 772 786 813 850 863 904 941 954",
    "GA": "229 404 470 478 678 706 762 770 912 943", "HI": "808", "ID": "208 986",
    "IL": "217 224 309 312 331 447 464 618 630 708 730 773 779 815 847 861 872",
    "IN": "219 260 317 463 574 765 812 930", "IA": "319 515 563 641 712", "KS": "316 620 785 913",
    "KY": "270 364 502 606 859", "LA": "225 318 337 504 985", "ME": "207", "MD": "227 240 301 410 443 667",
    "MA": "339 351 413 508 617 774 781 857 978", "MI": "231 248 269 313 517 586 616 679 734 810 906 947 989",
    "MN": "218 320 507 612 651 763 924 952", "MS": "228 601 662 769", "MO": "235 314 417 557 573 636 660 816 975",
    "MT": "406", "NE": "308 402 531", "NV": "702 725 775", "NH": "603",
    "NJ": "201 551 609 640 732 848 856 862 908 973", "NM": "505 575",
    "NY": "212 315 329 332 347 363 516 518 585 607 624 631 646 680 716 718 838 845 914 917 929 934",
    "NC": "252 336 472 704 743 828 910 919 980 984", "ND": "701",
    "OH": "216 220 234 283 326 330 380 419 436 440 513 567 614 740 937", "OK": "405 539 572 580 918",
    "OR": "458 503 541 971", "PA": "215 223 267 272 412 445 484 570 582 610 717 724 814 835 878",
    "RI": "401", "SC": "803 821 839 843 854 864", "SD": "605", "TN": "423 615 629 731 865 901 931",
    "TX": "210 214 254 281 325 346 361 409 430 432 469 512 682 713 726 737 806 817 830 832 903 915 936 940 "
          "945 956 972 979",
    "UT": "385 435 801", "VT": "802", "VA": "276 434 540 571 686 703 757 804 826 948",
    "WA": "206 253 360 425 509 564", "WV": "304 681", "WI": "262 274 353 414 534 608 715 920", "WY": "307",
}
_NANP_CA = {
    "AB": "368 403 587 780 825", "BC": "236 250 257 604 672 778", "MB": "204 431 584", "NB": "428 506",
    "NL": "709 879", "NS": "782 902", "ON": "226 249 289 343 365 382 416 437 519 548 613 647 683 705 742 753 "
                                           "807 905 942",
    "QC": "263 354 367 418 438 450 468 514 579 581 819 873", "SK": "306 474 639",
}
# Caribbean and Pacific members of the plan: a country of their own, no region
_NANP_OTHER = {
    "787": "PR", "939": "PR", "340": "VI", "671": "GU", "670": "MP", "684": "AS", "242": "BS", "246": "BB",
    "264": "AI", "268": "AG", "284": "VG", "345": "KY", "441": "BM", "473": "GD", "649": "TC", "658": "JM",
    "876": "JM", "664": "MS", "721": "SX", "758": "LC", "767": "DM", "784": "VC", "809": "DO", "829": "DO",
    "849": "DO", "868": "TT", "869": "KN",
}
NANP = {}
for _region, _codes in _NANP_US.items():
    for _ac in _codes.split():
        NANP[_ac] = ("US", _region)
for _region, _codes in _NANP_CA.items():
    for _ac in _codes.split():
        NANP[_ac] = ("CA", _region)
NANP["867"] = ("CA", None)               # Yukon, Northwest Territories and Nunavut share it: three zones
for _ac, _cc in _NANP_OTHER.items():
    NANP[_ac] = (_cc, None)

# area codes that keep another zone than their state: El Paso (Mountain), East Tennessee (Eastern),
# north-west Indiana and western Kentucky (Central)
NANP_ZONE = {"915": _DEN, "423": _NY, "865": _NY, "219": _CHI, "270": _CHI, "364": _CHI}

# country calling codes, longest first when read (a +1 number is NANP above)
DIAL = {
    "7": "RU", "76": "KZ", "77": "KZ", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE", "33": "FR",
    "34": "ES", "36": "HU", "39": "IT", "40": "RO", "41": "CH", "43": "AT", "44": "GB", "45": "DK", "46": "SE",
    "47": "NO", "48": "PL", "49": "DE", "51": "PE", "52": "MX", "53": "CU", "54": "AR", "55": "BR", "56": "CL",
    "57": "CO", "58": "VE", "60": "MY", "61": "AU", "62": "ID", "63": "PH", "64": "NZ", "65": "SG", "66": "TH",
    "81": "JP", "82": "KR", "84": "VN", "86": "CN", "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK",
    "95": "MM", "98": "IR",
    "211": "SS", "212": "MA", "213": "DZ", "216": "TN", "218": "LY", "220": "GM", "221": "SN", "225": "CI",
    "230": "MU", "233": "GH", "234": "NG", "237": "CM", "250": "RW", "251": "ET", "254": "KE", "255": "TZ",
    "256": "UG", "260": "ZM", "263": "ZW", "264": "NA", "265": "MW", "267": "BW", "268": "SZ",
    "350": "GI", "351": "PT", "352": "LU", "353": "IE", "354": "IS", "355": "AL", "356": "MT", "357": "CY",
    "358": "FI", "359": "BG", "370": "LT", "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY",
    "376": "AD", "377": "MC", "380": "UA", "381": "RS", "382": "ME", "385": "HR", "386": "SI", "387": "BA",
    "389": "MK", "420": "CZ", "421": "SK", "423": "LI",
    "501": "BZ", "502": "GT", "503": "SV", "504": "HN", "505": "NI", "506": "CR", "507": "PA", "509": "HT",
    "591": "BO", "593": "EC", "595": "PY", "598": "UY", "675": "PG", "679": "FJ",
    "852": "HK", "853": "MO", "855": "KH", "856": "LA", "880": "BD", "886": "TW",
    "960": "MV", "961": "LB", "962": "JO", "963": "SY", "964": "IQ", "965": "KW", "966": "SA", "967": "YE",
    "968": "OM", "970": "PS", "971": "AE", "972": "IL", "973": "BH", "974": "QA", "975": "BT", "976": "MN",
    "977": "NP", "992": "TJ", "993": "TM", "994": "AZ", "995": "GE", "996": "KG", "998": "UZ",
}

# ------------------------------------------------------------------ names
COUNTRY_NAMES = {}
_bare_seen = {}
for _cc, _name in ISO_NAME.items():
    COUNTRY_NAMES[fold(_name)] = _cc
    _b = fold(_bare(_name))
    _bare_seen.setdefault(_b, set()).add(_cc)
for _b, _ccs in _bare_seen.items():
    if len(_ccs) == 1:                       # "Korea (North)" and "Korea (South)" both bare to "korea": neither
        COUNTRY_NAMES.setdefault(_b, next(iter(_ccs)))
COUNTRY_NAMES.update({fold(k): v for k, v in ALIASES.items()})


def country_name(iso):
    """How a label says a country: "US", "UK", "UAE", "India", "Czechia"."""
    iso = str(iso or "").upper()
    return SHORT_NAME.get(iso) or _bare(ISO_NAME.get(iso, iso)) or iso
