"""Shared Apollo targeting and verified-address rules. No network calls or writes."""
import copy
import re

import apollo
import apollo_store

TARGET = "_project_search"
COUNTRIES = {"US": "United States", "GB": "United Kingdom", "IN": "India", "AE": "United Arab Emirates",
             "CA": "Canada", "DE": "Germany", "AT": "Austria", "IT": "Italy", "RU": "Russia",
             "BY": "Belarus", "IR": "Iran", "KP": "North Korea", "SY": "Syria", "CU": "Cuba"}


def strict(cfg):
    return (cfg.get("sourcing") or {}).get("contacts") == "apollo"


def verified(person):
    return bool(person.get("email") and person.get("email_status") == "valid"
                and str(person.get("apollo_email_status") or "").strip().lower() == "verified")


def iso(value):
    text = str(value or "").strip().casefold()
    aliases = {"usa": "US", "united states of america": "US", "uk": "GB", "uae": "AE"}
    if text in aliases:
        return aliases[text]
    return next((code for code, name in COUNTRIES.items() if text in (code.lower(), name.lower())),
                text.upper() if len(text) == 2 else None)


def searches(cfg):
    return (cfg.get("apollo_discovery") or {}).get("searches") or []


def target(cfg, filters):
    options = searches(cfg)
    if not options:
        return None
    key = (filters or {}).get(TARGET) or options[0]["key"]
    found = next((s for s in options if s["key"] == key), None)
    if found is None:
        raise ValueError("Choose one of this project's targeting groups.")
    return found


def audience(cfg, selected):
    key = (selected or {}).get("audience")
    return next((a for a in cfg.get("audiences") or [] if a["key"] == key), {})


def _ranges(values):
    return [(int(str(v).split(",")[0]), int(str(v).split(",")[1])) for v in values]


def constrained_filters(cfg, kind, filters, today=None):
    """Resolve search-bar text BEFORE applying immutable project constraints.

    Apollo lists mean OR, so adding the project's terms to a user's terms would widen
    the search. A manual list must be a subset; headcount/range filters intersect.
    One configured targeting group at a time preserves the industry/size pairing.
    """
    raw = copy.deepcopy(filters or {})
    selected = target(cfg, raw) if strict(cfg) else None
    raw.pop(TARGET, None)
    out = apollo._with_search_text(kind, raw)
    if not strict(cfg):
        apollo.build_query(kind, out)
        return out, selected
    locked = {}
    if selected:
        from discover_lcx_services import apollo_filters
        countries = (cfg.get("apollo_discovery") or {}).get("countries") or []
        worldwide = next((c for c in countries if c["iso"] == "ALL"), None)
        country = worldwide or (countries[0] if countries else {"iso": "ALL"})
        locked = apollo_filters({"search": selected, "country": country}, today)
        # Multiple fixed countries form one union; custom Mumbai HQ locations stay intact.
        if not worldwide and not (selected.get("filters") or {}).get("organization_locations"):
            locked["organization_locations"] = [c["name"] for c in countries]
    geo = cfg.get("geography") or {}
    banned = set(geo.get("disallowed_countries") or []) | set(geo.get("unpayable_countries") or [])
    excluded = [COUNTRIES.get(c, c) for c in sorted(banned)]
    if kind == "people":
        from enrich_apollo import roles_for
        roles = roles_for(cfg, audience(cfg, selected).get("key"))
        if roles:
            locked["person_titles"] = roles
        locked["contact_email_status"] = ["verified"]
        reveal = (cfg.get("enrichment") or {}).get("reveal_countries") or []
        if reveal:
            locked["organization_locations"] = [COUNTRIES.get(c, c) for c in reveal]
        # Apollo has no negative HQ filter on people. The reveal uses current HQ as
        # a second gate. Funding-only presets must be searched as companies first.
        for key in list(locked):
            definition = apollo.FILTER_BY_KEY.get(key)
            if definition and kind not in definition["for"]:
                if key != "organization_not_locations":
                    raise ValueError("This targeting group needs a company search first; save the companies for automatic qualification and contact enrichment.")
                locked.pop(key)
    else:
        locked["organization_not_locations"] = sorted(set(locked.get("organization_not_locations", []) + excluded))
    for loc in out.get("organization_locations") or []:
        if iso(loc) in banned:
            raise ValueError("That headquarters location is excluded by this project.")
    for key, required in locked.items():
        given = out.get(key)
        if key in ("organization_not_locations", "not_organization_websites_list"):
            out[key] = list(dict.fromkeys(list(given or []) + required))
        elif key == "contact_email_status":
            out[key] = ["verified"]
        elif key == "organization_num_employees_ranges" and given:
            bands = [(max(a, c), min(b, d)) for a, b in _ranges(required) for c, d in _ranges(given)
                     if max(a, c) <= min(b, d)]
            if not bands:
                raise ValueError("That headcount is outside this project's targeting group.")
            out[key] = ["%d,%d" % pair for pair in sorted(set(bands))]
        elif isinstance(required, dict):
            given = given or {}
            merged = {"min": max(str(required.get("min") or ""), str(given.get("min") or "")),
                      "max": min(str(required.get("max") or "9999"), str(given.get("max") or "9999"))}
            if key.endswith("_range") and "date" not in key and "posted" not in key:
                merged = {"min": max(float(required.get("min", 0)), float(given.get("min", 0))),
                          "max": min(float(required.get("max", float("inf"))), float(given.get("max", float("inf"))))}
                merged = {k: v for k, v in merged.items() if v != float("inf")}
            if "min" in merged and "max" in merged and merged["min"] > merged["max"]:
                raise ValueError("That range is outside this project's targeting group.")
            out[key] = merged
        elif given:
            norm = lambda v: str(v).strip().casefold()
            allowed = {norm(x) for x in required}
            def within(value):
                if norm(value) in allowed:
                    return True
                if key == "organization_locations":
                    code = iso(str(value).split(",")[-1])
                    return code is not None and code in {iso(x) for x in required}
                return False
            if any(not within(x) for x in given):
                raise ValueError("%s must stay within the selected project targeting group: %s." %
                                 (apollo.FILTER_BY_KEY[key]["label"], ", ".join(required)))
            out[key] = given
        else:
            out[key] = required
    excluded_domains = (cfg.get("self_exclusion") or {}).get("domains") or []
    out["not_organization_websites_list"] = list(dict.fromkeys(out.get("not_organization_websites_list", []) + excluded_domains))
    apollo.build_query(kind, out)
    return out, selected


def company_reason(org, cfg, selected=None, filters=None):
    """Reject contradictory Apollo facts. Missing search fields require later qualification."""
    why = apollo_store.excluded(org, cfg.get("self_exclusion"))
    if why:
        return "TVF or an affiliate"
    if not strict(cfg):
        return None
    geo = cfg.get("geography") or {}
    country = iso(org.get("country"))
    banned = set(geo.get("disallowed_countries") or []) | set(geo.get("unpayable_countries") or [])
    if country and country in banned:
        return "Headquarters country is excluded by this project"
    actual = str(org.get("country") or "").strip()
    locations = (filters or {}).get("organization_locations") or (selected or {}).get("filters", {}).get("organization_locations") or []
    codes = {iso(x) for x in locations} - {None}
    if actual and country and codes and country not in codes:
        return "Apollo headquarters is outside the project's search"
    city_locations = [x for x in locations if not iso(x)]
    if city_locations and org.get("city") and not any(str(org["city"]).casefold() in x.casefold() for x in city_locations):
        return "Apollo headquarters city is outside the project's search"
    employees = org.get("estimated_num_employees")
    bands = (filters or {}).get("organization_num_employees_ranges") or (selected or {}).get("filters", {}).get("organization_num_employees_ranges") or []
    if employees is not None and bands and not any(a <= float(employees) <= b for a, b in _ranges(bands)):
        return "Apollo headcount is outside the project's search"
    names = (cfg.get("apollo_discovery") or {}).get("excluded_name_patterns") or []
    if any(re.search(r"\b" + re.escape(n) + r"\b", str(org.get("name") or ""), re.I) for n in names):
        return "Known major studio"
    return None
