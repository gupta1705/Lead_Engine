"""Evidence-led acquisition targeting. No Apollo calls, estimates of valuation or sends."""
import copy
import datetime as dt
import json
import math
import re
from pathlib import Path

VERSION = "acquisitions-20261116"
OFFICE = ("Contagious Online Media Network Pvt Ltd., 702, 7th Floor, A Wing, Fortune Terraces, "
          "Opp. Citi Mall, New Link Rd, Andheri West, Mumbai, Maharashtra 400053")
LIMIT = 10_000_000
INDIA = {"in", "india"}
REVIEW_FIELDS = {"asking_price_inr", "price_source", "asset_summary", "asset_source",
                 "address", "address_source", "distress_summary", "distress_source", "checked_at", "deal_type"}
DEALS = {"unknown", "full_company_acquisition"}


def enabled(cfg):
    return bool((cfg or {}).get("startup_acquisition"))


def configure(original):
    cfg = copy.deepcopy(original)
    cfg["brief"] = ("Find struggling Indian startups TVF can salvage, prioritising media, creators, consumer "
                    "businesses, software and AI products and physical proximity to the Andheri West office. "
                    "Upfront purchase price must be strictly below INR 1 crore. Unknown price requires review; "
                    "funding, revenue and headcount never establish purchase price. Apollo spending is paused.")
    cfg["startup_acquisition"] = {"version": VERSION, "office_address": OFFICE,
        "max_upfront_inr_exclusive": LIMIT, "evidence_valid_days": 90,
        "allowed_deal_types": ["full_company_acquisition"],
        "deal_types": "Full company acquisitions only. Exclude asset-only purchases, acqui-hires, minority equity and revenue share.",
        "proximity_method": "Address/neighbourhood bands, not measured kilometres or travel time. City-only evidence earns only city-level points."}
    cfg["geography"].update(home_region="India, prioritising Andheri West and Mumbai",
        guidance="Mumbai proximity ranks candidates; another Indian city is not excluded. A confirmed foreign headquarters is excluded. Unconfirmed location remains a research gap.")
    criteria = [
        ("distress_current", "Evidence of current distress", 30,
         "Public distress evidence weighted by recency: up to 6 months full, 6-12 months 75%, 12-24 months 25%. Funding silence or a failed website alone is not confirmed distress."),
        ("tvf_fit", "TVF fit: media, creators, consumer, software and AI", 15,
         "Sector words from the company and its coverage. Fit is a research priority, not proof that TVF can revive the business."),
        ("salvage_value", "A product, users, team or assets worth preserving", 10,
         "Dated, sourced asset evidence from a reviewer, or an app with recent updates and at least 1,000 ratings. A working homepage alone earns no salvage points."),
        ("affordability", "Documented upfront price below INR 1 crore", 20,
         "Full points only for a dated asking price or founder quote with its source, checked within 90 days. Exactly INR 1 crore fails. Funding and revenue are not acquisition prices. Unknown price scores zero and stays unconfirmed."),
        ("office_proximity", "Proximity to TVF's Andheri West office", 20,
         "Andheri West/Oshiwara/Lokhandwala/Versova 100%; adjacent western suburbs 80%; other Mumbai 60%; Thane/Navi Mumbai 40%; other India 10%; unknown 0. Address evidence required for neighbourhood points. These are bands, not measured distances."),
        ("reachable_decision_maker", "Verified founder or decision-maker contact", 5,
         "Apollo-verified current founder/decision-maker contact; existing contact policy remains in force.")]
    cfg["rubric"] = [dict(key=k, label=l, points=p, input="metadata.scoring_inputs."+k, guidance=g)
                     for k,l,p,g in criteria]
    cfg["score_threshold_review"], cfg["score_threshold_priority"] = 35, 65
    cfg["gates"] = [g for g in cfg["gates"] if g["key"] not in {"mumbai_region", "india_based", "under_purchase_ceiling", "full_company_only"}] + [
        {"key":"india_based", "label":"Not confirmed outside India", "input":"metadata.scoring_inputs.acquisition_country_blocked", "exclude_when":True},
        {"key":"under_purchase_ceiling", "label":"Upfront purchase price strictly below INR 1 crore", "input":"metadata.scoring_inputs.acquisition_price_blocked", "exclude_when":True},
        {"key":"full_company_only", "label":"Full company acquisitions only", "input":"metadata.scoring_inputs.acquisition_deal_blocked", "exclude_when":True}]
    tiers = cfg["startup_discovery"]["sector_tiers"]
    extra = ["consumer", "consumer app", "d2c", "e-commerce", "ecommerce", "software", "saas", "artificial intelligence", "ai", "creator", "machine learning", "automation", "analytics"]
    tiers["1"]["words"] = list(dict.fromkeys(tiers["1"]["words"] + tiers.get("0.5",{}).get("words",[]) + extra))
    tiers["1"]["label"] = "Media, creator, consumer, software or AI business"
    tiers["0"]["words"] = [w for w in tiers["0"]["words"] if w not in extra]
    cfg["enrichment"].update(enabled=False, credits_per_run=0, credits_per_week=0,
        require_fitting_role=True, reveal_countries=["IN"], score_over=34,
        guidance="Spending paused by owner, 16 November 2026. Enable only after an explicit new budget. Both manual and automatic reveals require current distress, salvage evidence and Indian headquarters. Unknown acquisition price stays a research gap.")
    bands = ["1,10", "11,20", "21,50"]
    groups = [("media_creator_consumer", ["media", "entertainment", "gaming", "creator", "education", "consumer", "e-commerce"]),
              ("software_ai", ["software", "artificial intelligence", "saas", "machine learning"])]
    cfg["apollo_discovery"]["searches"] = [
        {"key":area+"_"+key, "filters":{"organization_locations":locations,
          "q_organization_keyword_tags":words, "organization_num_employees_ranges":bands}}
        for area,locations in [("mumbai",["Mumbai, India", "Navi Mumbai, India", "Thane, India"]), ("india",["India"])]
        for key,words in groups]
    cfg["apollo_discovery"]["guidance"] = "Mumbai-first discovery, then other Indian cities; teams of 1-50. These filters find research candidates, not proven distressed or affordable acquisitions. No pages are purchased while spending is paused."
    cfg["ui"].update(search_page="apollo", board_title="Startup acquisition research")
    details = [("status", "Acquisition assessment"), ("price_summary", "Upfront price"),
               ("proximity_summary", "Office proximity"), ("asset_summary", "Salvage evidence"),
               ("distress_summary", "Current distress"), ("gaps", "Still to verify")]
    cfg["ui"]["details"] = [{"path":"metadata.startup_acquisition."+k,"label":l,"format":"text"} for k,l in details]
    cfg["metadata_fields"] = list(dict.fromkeys(cfg.get("metadata_fields",[]) + ["startup_acquisition", "startup_review"]))
    return cfg


def fresh(stamp, now, days):
    try:
        date = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=dt.timezone.utc)
        return 0 <= (now-date).total_seconds() <= days*86400
    except (ValueError, TypeError):
        return False


def valid_review(data, user, now=None):
    """Validate authenticated reviewer input; no client-provided scoring values are accepted."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(data, dict) or set(data)-REVIEW_FIELDS:
        raise ValueError("Only acquisition evidence fields may be saved.")
    out = {k:str(v or "").strip()[:2000] for k,v in data.items() if k != "asking_price_inr"}
    if out.get("deal_type", "unknown") not in DEALS:
        raise ValueError("Choose a listed deal structure or leave it undecided.")
    value = data.get("asking_price_inr")
    if value not in (None, ""):
        try:
            n = float(value)
        except (ValueError, TypeError):
            raise ValueError("Enter the upfront asking price in rupees.") from None
        if isinstance(value,bool) or not math.isfinite(n) or n < 0:
            raise ValueError("The price must be zero or a positive number.")
        out["asking_price_inr"] = n
        if not out.get("price_source"):
            raise ValueError("Add the asking-price source or founder quote reference.")
        if out.get("deal_type") != "full_company_acquisition":
            raise ValueError("Confirm the quoted price covers a full company acquisition.")
    else:
        out["asking_price_inr"] = None
    if any(out.get(k) for k in ("price_source", "asset_summary", "address", "distress_summary")):
        if not fresh(out.get("checked_at"), now, 90):
            raise ValueError("Evidence must have a check date within the last 90 days.")
    for field,source in [("asset_summary","asset_source"),("address","address_source"),("distress_summary","distress_source")]:
        if out.get(field) and not out.get(source):
            raise ValueError("Add the source for the %s evidence." % field.replace("_", " "))
    out.update(updated_by=str(user), updated_at=now.isoformat())
    return out


def assess(meta, cfg, now=None):
    """Return new scoring inputs and a candid reviewer assessment from existing evidence only."""
    import startup_signals as ss
    now = now or dt.datetime.now(dt.timezone.utc)
    block = cfg["startup_acquisition"]
    review = meta.get("startup_review") or {}
    verified = fresh(review.get("checked_at"), now, block["evidence_valid_days"]) and bool(review.get("updated_by"))
    org = meta.get("apollo") or {}
    site = meta.get("site_health") or {}
    app = meta.get("app") or {}
    si = meta.get("scoring_inputs") or {}
    country = str(org.get("country") or meta.get("hq_country") or "").strip().lower()
    country_blocked = bool(country and country not in INDIA)
    india = country in INDIA
    deal_blocked = review.get("deal_type", "unknown") not in DEALS
    price = review.get("asking_price_inr")
    known = (verified and review.get("deal_type") == "full_company_acquisition" and bool(review.get("price_source")) and isinstance(price,(int,float))
             and not isinstance(price,bool) and math.isfinite(price) and price >= 0)
    price_blocked = bool(known and price >= block["max_upfront_inr_exclusive"])
    affordable = bool(known and not price_blocked)
    price_summary = ("INR {:,.0f}; {}. Source: {}".format(price, "below ceiling" if affordable else "at/above ceiling",review["price_source"])) if known else "Price unknown; confirm an upfront asking price below INR 1 crore"
    # Apollo raw_address is a structured HQ field. A website city mention may be a branch or customer.
    address = review.get("address") if verified and review.get("address_source") else org.get("raw_address")
    source = review.get("address_source") if verified and review.get("address") else "Apollo headquarters"
    city = str(org.get("city") or meta.get("hq_city") or "").lower()
    text = str(address or "").lower()
    proximity, label = 0.0, "Location unknown"
    if india:
        proximity, label = .1, "Other India"
        if city in {"mumbai", "bombay"}:
            proximity, label = .6, "Mumbai; neighbourhood not confirmed"
        if city in {"navi mumbai", "thane"}:
            proximity, label = .4, "Navi Mumbai / Thane"
        # Conflicting non-Mumbai structured HQ evidence must not gain neighbourhood points.
        local = not city or city in {"mumbai", "bombay", "andheri", "andheri west"}
        if address and local:
            if re.search(r"\b(andheri west|andheri \(w\)|andheri \(west\)|oshiwara|lokhandwala|versova|400053)\b", text):
                proximity,label = 1.0,"Andheri West and nearby neighbourhoods"
            elif re.search(r"\b(juhu|goregaon|jogeshwari|andheri east|andheri \(e\)|andheri \(east\)|vile parle|santacruz)\b",text):
                proximity,label = .8,"Adjacent western suburbs"
    proximity_summary = label + (". %s: %s" % (source,address) if address else ". City-level evidence only" if india else "") + "; neighbourhood band, not a measured distance"
    events = meta.get("press_events") or []
    distress = []
    for e in events:
        stamp = ss._parse(e.get("published_at"))
        age = ss._months(stamp, now)
        if e.get("track") == "distress" and age is not None and 0 <= (now-stamp).total_seconds() and age <= 24:
            strength = max(0,min(1,float(e.get("strength") or 0)))
            factor = 1 if age <= 6 else .75 if age <= 12 else .25
            distress.append((strength*factor, e))
    distress_score, event = max(distress, key=lambda x:x[0]) if distress else (0,None)
    manual_distress = verified and review.get("distress_summary") and review.get("distress_source")
    if manual_distress:
        distress_score = 1.0
    direct_distress = bool(manual_distress or (event and event.get("link") and event.get("strength",0) >= .5 and distress_score >= .375))
    summary = (review["distress_summary"]+". Source: "+review["distress_source"]) if manual_distress else (
        "%s (%s). %s" % (event.get("title"),event.get("published_at"),event.get("link") or "source link missing") if event else "No current, dated distress evidence; funding gaps and an unavailable website are research signals only")
    # A website loading is not evidence of transferable assets or customers.
    asset = bool(verified and review.get("asset_summary") and review.get("asset_source"))
    app_signal = bool((app.get("ratings") or 0) >= 1000 and app.get("url") and fresh(app.get("last_update"),now,365))
    salvage = 1.0 if asset else .5 if app_signal else 0.0
    asset_summary = review["asset_summary"]+". Source: "+review["asset_source"] if asset else (
        "App with 1,000+ ratings, updated within a year; confirm users, ownership and transferability" if app_signal else "No verified salvage assets yet; a live homepage alone is insufficient")
    words = " ".join(str(v or "") for v in [org.get("industry"),org.get("short_description"),meta.get("descriptor"),site.get("title"),site.get("description")])
    fit,_ = ss.sector_for(words, cfg["startup_discovery"]["sector_tiers"])
    structural = any(si.get(k) for k in ("major_or_oversized_signal","acquired_signal")) or si.get("activity_signal") == "confirmed_dormant"
    contact_eligible = bool(india and direct_distress and salvage > 0 and not price_blocked and not deal_blocked and not structural)
    gaps = []
    if not india: gaps.append("Indian headquarters")
    if not direct_distress: gaps.append("current distress evidence")
    if salvage == 0: gaps.append("salvageable assets")
    if not affordable: gaps.append("confirmed price below INR 1 crore")
    gaps.extend(["ownership and liabilities", "full company deal terms and approval"])
    status = "Excluded deal structure" if deal_blocked else "Outside purchase ceiling" if price_blocked else "Outside India" if country_blocked else "Existing acquisition/size/activity exclusion" if structural else "Budget-fit candidate; diligence required" if contact_eligible and affordable else "Founder research; price unconfirmed" if contact_eligible else "Research required"
    contact = meta.get("apollo_enrich") or {}
    people = list((meta.get("apollo_people") or {}).values()) + [contact]
    reachable = any(isinstance(p,dict) and (p.get("apollo_email_status") or p.get("email_status")) == "verified"
                    and (p.get("name") or p.get("first_name"))
                    and re.search(r"\b(founder|ceo|director|chief executive)\b", str(p.get("title") or ""),re.I) for p in people)
    return {"distress_current":distress_score, "tvf_fit":fit or 0.0, "salvage_value":salvage,
            "reachable_decision_maker":1.0 if reachable else 0.0,
            "no_struggle_signal":0.0 if distress_score > 0 else 1.0,
            "affordability":1.0 if affordable else 0.0, "office_proximity":proximity,
            "acquisition_country_blocked":country_blocked,"acquisition_price_blocked":price_blocked,"acquisition_deal_blocked":deal_blocked}, {
        "version":VERSION,"status":status,"price_summary":price_summary,"proximity_summary":proximity_summary,
        "asset_summary":asset_summary,"distress_summary":summary,"gaps":"; ".join(gaps),
        "contact_eligible":contact_eligible,"price_confirmed":known,"assessed_at":now.isoformat()}


def refresh(meta, cfg, now=None):
    out = copy.deepcopy(meta or {})
    inputs, assessment = assess(out,cfg,now)
    out.setdefault("scoring_inputs",{}).update(inputs)
    out["startup_acquisition"] = assessment
    out["unverified_inputs"] = [k for k in out.get("unverified_inputs",[]) if k not in inputs]
    return out


# Used by BOTH automatic enrichment and the manual Apollo reveal route.
CONTACT_SQL = (" and e.metadata->'startup_acquisition'->>'contact_eligible'='true'"
               " and nullif(e.metadata->'startup_acquisition'->>'assessed_at','')::timestamptz > now()-interval '7 days'")


def update_live(apply=False):
    import psycopg2
    from run_sql import load_db_url
    now = dt.datetime.now(dt.timezone.utc)
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("select id,config from segments where slug='startup-acquisitions' for update")
        sid, previous = cur.fetchone()
        cfg = configure(previous)
        assert previous.get("outreach") == cfg.get("outreach")
        # Review decisions and all outreach history remain untouched.
        cur.execute("select id,metadata from entities where segment_id=%s and status in ('discovered','enriched','scored','ready_for_review','shortlisted') for update",(sid,))
        rows = [(eid,refresh(meta,cfg,now)) for eid,meta in cur.fetchall()]
        result = {"applied":apply,"leads_assessed":len(rows),"eligible_for_contact_research":sum(m["startup_acquisition"]["contact_eligible"] for _,m in rows),"price_confirmed":sum(m["startup_acquisition"]["price_confirmed"] for _,m in rows),"apollo_spending":False,"outreach_preserved":True}
        if apply:
            folder = Path(__file__).resolve().parent.parent / "logs" / VERSION
            folder.mkdir(parents=True,exist_ok=True)
            (folder/(now.strftime("%Y%m%d-%H%M%S")+"-config-before.json")).write_text(json.dumps(previous),encoding="utf-8")
            cur.execute("update segments set config=%s::jsonb,updated_at=now() where id=%s",(json.dumps(cfg),sid))
            for eid,meta in rows:
                cur.execute("update entities set metadata=%s::jsonb,updated_at=now() where id=%s",(json.dumps(meta),eid))
                cur.execute("select score_entity(%s)",(eid,))
            conn.commit()
        else:
            conn.rollback()
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-live",action="store_true")
    parser.add_argument("--preview-live",action="store_true")
    args = parser.parse_args()
    if args.apply_live or args.preview_live:
        print(json.dumps(update_live(args.apply_live)))
    else:
        path = Path(__file__).resolve().parent.parent/"config/segment.startup-acquisitions.json"
        path.write_text(json.dumps(configure(json.loads(path.read_text(encoding="utf-8"))),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
