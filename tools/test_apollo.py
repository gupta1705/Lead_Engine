#!/usr/bin/env python3
"""test_apollo.py -- the Universal page's Apollo client and lead store, as a regression table.

    python tools/test_apollo.py

Part one needs no key and no network: Apollo's answers are stubbed with the
shapes docs.apollo.io documents (read 2026-09-19), so every filter, every error
and every reveal path is exercised without spending a credit. Part two runs the
lead store against the real database inside one transaction that is rolled
back: a throwaway segment, companies and contacts, then ROLLBACK.
Exit code 1 on any failure.
"""
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "app"))
import apollo  # noqa: E402
import apollo_store as store  # noqa: E402

RESULTS = []
PID = ["%024x" % (0xa000 + i) for i in range(30)]          # Apollo IDs are 24 hex characters
OID = ["%024x" % (0xb000 + i) for i in range(10)]


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-60s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


def refused(fn):
    try:
        fn()
    except ValueError as e:
        return str(e)
    return None


class Stub:
    """Stands in for apollo._call: records each request, answers from a list."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, path, query=None, body=None, timeout=30):
        self.calls.append((method, path, query, body))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def offline():
    print("-- filters, exactly as Apollo documents them")
    q = apollo.build_query("people", {
        "person_titles": ["Head of Partnerships", "head of partnerships", "VP Content"],
        "include_similar_titles": False, "person_seniorities": ["director", "vp"],
        "organization_num_employees_ranges": ["11,20", "250,500"],
        "revenue_range": {"min": "500,000", "max": 5000000},
        "currently_using_any_of_technology_uids": ["Google Analytics", "WordPress.org"],
        "organization_headcount_growth_past_n_months": 12,
        "organization_headcount_growth_range": {"min": -20, "max": -1},
        "q_keywords": "  film   partnerships "}, 2, 50)
    check("titles repeat as person_titles[], case-insensitive duplicates dropped",
          [v for p, v in q if p == "person_titles[]"], ["Head of Partnerships", "VP Content"])
    check("similar titles off is sent as false", ("include_similar_titles", "false") in q, True)
    check("seniorities and headcount bands repeat", [v for p, v in q if p in ("person_seniorities[]",
          "organization_num_employees_ranges[]")], ["director", "vp", "11,20", "250,500"])
    check("revenue as revenue_range[min]/[max], commas stripped",
          [x for x in q if x[0].startswith("revenue_range")], [("revenue_range[min]", "500000"),
                                                                ("revenue_range[max]", "5000000")])
    check("technologies become Apollo's IDs",
          [v for p, v in q if p.startswith("currently_using")], ["google_analytics", "wordpress_org"])
    check("shrinking companies: a negative growth range is allowed",
          [x for x in q if x[0].startswith("organization_headcount_growth")],
          [("organization_headcount_growth_past_n_months", "12"),
           ("organization_headcount_growth_range[min]", "-20"), ("organization_headcount_growth_range[max]", "-1")])
    check("keywords squeezed, page and per_page last", (dict(q)["q_keywords"], q[-2:]),
          ("film partnerships", [("page", "2"), ("per_page", "50")]))
    c = apollo.build_query("companies", {"q_organization_name": "Tonko", "organization_not_locations": ["ireland"],
                                         "latest_funding_date_range": {"min": "2025-01-01"},
                                         "q_organization_keyword_tags": ["animation"]})
    check("a company search: name, excluded HQ, funding date, keywords", c[:-2], [
        ("q_organization_name", "Tonko"), ("organization_not_locations[]", "ireland"),
        ("latest_funding_date_range[min]", "2025-01-01"), ("q_organization_keyword_tags[]", "animation")])
    check("similar-titles alone is not sent (it means nothing without titles)",
          apollo.build_query("people", {"include_similar_titles": False})[:-2], [])
    check("a custom headcount band is accepted", apollo.build_query(
        "people", {"organization_num_employees_ranges": ["3,7"]})[0], ("organization_num_employees_ranges[]", "3,7"))
    for label, kind, f, want in (
            ("an unknown filter is refused", "people", {"foo": 1}, "unknown filter 'foo'"),
            ("a company-only filter in a people search is refused", "people",
             {"organization_not_locations": ["x"]}, "Exclude HQ locations is not a people filter"),
            ("a seniority Apollo does not have is refused", "people", {"person_seniorities": ["boss"]},
             "Management level: 'boss' is not one of Apollo's options"),
            ("headcount growth needs both halves", "people", {"organization_headcount_growth_past_n_months": 6},
             "Headcount growth needs both a time frame and a % range"),
            ("a growth window Apollo does not take is refused", "people",
             {"organization_headcount_growth_past_n_months": 3, "organization_headcount_growth_range": {"min": 1}},
             "Headcount growth: over: Apollo takes 6, 12 or 24 months"),
            ("min above max is refused", "companies", {"revenue_range": {"min": 10, "max": 5}},
             "Revenue (USD): the minimum is above the maximum"),
            ("a negative revenue is refused", "companies", {"revenue_range": {"min": -5}},
             "Revenue (USD): -5 cannot be negative"),
            ("text in a number box is refused", "companies", {"total_funding_range": {"max": "lots"}},
             "Total funding (USD): lots is not a whole number"),
            ("a bad date is refused", "companies", {"latest_funding_date_range": {"min": "01/02/2025"}},
             "Latest funding date: dates are YYYY-MM-DD"),
            ("a made-up company ID is refused", "people", {"organization_ids": ["nope"]},
             "Company: 'nope' is not an Apollo company ID"),
            ("more than five lookalike seeds are refused (Apollo's limit)", "companies",
             {"lookalike_organization_ids": OID[:6]}, "Company lookalikes: up to 5")):
        check(label, refused(lambda: apollo.build_query(kind, f)), want)
    check("page 501 is refused (Apollo shows 500)", refused(lambda: apollo.build_query("people", {}, 501)),
          "Apollo shows pages 1 to 500; add filters to narrow the search")
    check("101 a page is refused", refused(lambda: apollo.build_query("people", {}, 1, 101)), "up to 100 results a page")
    check("the search in words", apollo.describe("people", {
        "person_titles": ["head of partnerships"], "person_seniorities": ["c_suite", "vp"],
        "include_similar_titles": False, "revenue_range": {"min": 1000000}, "organization_ids": OID[:2]}),
        "People · Job titles: head of partnerships · exact titles only · Management level: C-suite, VP"
        " · Revenue (USD): 1000000 to any · Company: 2 picked")

    print("\n-- Apollo's answers, stubbed with the documented shapes")
    stub = Stub([{"total_entries": 31993, "people": [
        {"id": PID[0], "first_name": "Elena", "last_name_obfuscated": "Mo***s", "title": "Director of Sales",
         "has_email": False, "has_city": True, "has_direct_phone": "Yes",
         "organization": {"name": "Northwind Systems", "has_industry": True, "has_employee_count": True}},
        {"id": None, "first_name": "Nobody"}]}])
    apollo._call = stub
    r = apollo.search_people({"person_titles": ["sales director"]}, 1, 5)
    check("people search: POST mixed_people/api_search with query parameters",
          stub.calls[0][:2] + (stub.calls[0][3],), ("POST", "/mixed_people/api_search", None))
    check("people search: rows without an ID are dropped, the preview kept", (r["total"], len(r["people"]),
          r["people"][0]["last_name_obfuscated"], r["people"][0]["company"]),
          (31993, 1, "Mo***s", "Northwind Systems"))
    stub = Stub([{"pagination": {"total_entries": 1184, "total_pages": 592}, "accounts": [
        {"id": OID[0], "name": "Mine Co", "website_url": "http://www.mine.co", "organization_id": OID[0]}],
        "organizations": [{"id": OID[1], "name": "Nikkei Asia", "website_url": "http://www.nikkei.com",
                           "primary_phone": {"number": "+81 576-95-0781"}, "linkedin_url": "http://linkedin.com/x",
                           "founded_year": 1876}]}])
    apollo._call = stub
    r = apollo.search_companies({"organization_locations": ["japan"]}, 1, 2)
    check("company search: accounts and organizations both listed, phone and domain filled in",
          [(c["name"], c.get("primary_domain"), c.get("phone"), c["in_apollo_account"]) for c in r["companies"]],
          [("Mine Co", "mine.co", None, True), ("Nikkei Asia", "nikkei.com", "+81 576-95-0781", False)])
    check("company search: total and pages from pagination", (r["total"], r["total_pages"]), (1184, 592))
    apollo._call = Stub([{"pagination": {}, "accounts": [{"id": "c" * 24, "organization_id": OID[7], "name": "Mine"}],
                          "organizations": []}])
    check("an account is listed under its company's ID, not the account's",
          apollo.search_companies({"organization_locations": ["x"]})["companies"][0]["id"], OID[7])
    row = apollo.org_row({"id": OID[8], "name": "X", "linkedin_url": "javascript:alert(1)",
                          "website_url": "https://www.x.example/about", "estimated_num_employees": "abc",
                          "founded_year": "2014", "keywords": "not a list", "short_description": {"a": 1}})
    check("a saved company row keeps only safe links, real numbers and plain text", row,
          {"id": OID[8], "name": "X", "website_url": "https://www.x.example/about", "founded_year": 2014,
           "primary_domain": "x.example"})
    check("company search's organization_revenue is read as the revenue the page shows",
          apollo.org_row({"id": OID[8], "name": "X", "organization_revenue": 2500000.0,
                          "organization_revenue_printed": "2.5M"}),
          {"id": OID[8], "name": "X", "annual_revenue": 2500000, "annual_revenue_printed": "2.5M"})

    def match(i, email="x%d@firm.com", status="verified"):
        return {"id": PID[i], "first_name": "P%d" % i, "last_name": "Q", "name": "P%d Q" % i,
                "email": (email % i) if "%d" in (email or "") else email, "email_status": status,
                "linkedin_url": "https://www.linkedin.com/in/p%d" % i, "title": "Producer",
                "organization": {"id": OID[i % 3], "name": "Firm %d" % (i % 3), "primary_domain": "firm%d.com" % (i % 3),
                                 "industry": "entertainment", "estimated_num_employees": 40}}
    stub = Stub([{"matches": [match(i) for i in range(10)], "credits_consumed": 10},
                 {"matches": [match(i) for i in range(10, 20)] + [None], "credits_consumed": 9.5},
                 {"matches": [match(20, "email_not_unlocked@domain.com")], "credits_consumed": 1}])
    apollo._call = stub
    r = apollo.reveal_people(PID[:25] + ["not-an-id"])
    check("reveal: 25 people in batches of ten, personal emails and phones never asked for",
          [(c[1], c[2], len(c[3]["details"])) for c in stub.calls],
          [("/people/bulk_match", [("reveal_personal_emails", "false"), ("reveal_phone_number", "false")], n)
           for n in (10, 10, 5)])
    check("reveal: credits added up (a fraction is kept)", r["credits"], 20.5)
    check("reveal: the unlock placeholder is never kept as an email",
          [p["email"] for p in r["people"] if p["apollo_id"] == PID[20]], [None])
    check("reveal: who Apollo did not return is reported", r["missing"], PID[21:25])
    stub = Stub([{"matches": [match(i) for i in range(10)], "credits_consumed": 10},
                 apollo.ApolloError("Apollo's rate limit is used up for now.", status=429, retry_after=30)])
    apollo._call = stub
    r = apollo.reveal_people(PID[:20])
    check("reveal: a failure after the first batch keeps what was paid for",
          (len(r["people"]), r["credits"], len(r["unrevealed"]), bool(r["error"])), (10, 10.0, 10, True))
    apollo._call = Stub([apollo.ApolloError("refused", status=403)])
    got = None
    try:
        apollo.reveal_people(PID[:3])
    except apollo.ApolloError as e:
        got = e.status
    check("reveal: a failure on the first batch is raised (nothing was charged)", got, 403)

    print("\n-- people as the lead store keeps them")
    p = apollo.person_record(match(3, status="extrapolated"))
    check("an extrapolated email is kept as unverified", (p["email"], p["email_status"]), ("x3@firm.com", "unverified"))
    check("a verified email is valid", apollo.person_record(match(4))["email_status"], "valid")
    check("no email: status unknown", apollo.person_record(match(5, email=None))["email_status"], "unknown")
    check("tech names to Apollo IDs", [apollo.tech_uid(x) for x in ("Google Analytics", "WordPress.org", " HubSpot ")],
          ["google_analytics", "wordpress_org", "hubspot"])

    print("\n-- Apollo's errors, as the page words them")
    ex = apollo._explain
    check("401 (plain text body)", ex(401, None, "Invalid API key. See https://docs.apollo.io")[0],
          "Apollo did not accept the API key. Check APOLLO_API_KEY.")
    check("403: the key's scope, with Apollo's own reason", ex(403, {
        "error": "This API key is not authorized to access api/v1/mixed_people/api_search.",
        "error_code": "API_INACCESSIBLE", "error_details": {"code": "AUTH.AUTHORIZATION.ENDPOINT_ACCESS_DENIED",
                                                           "message": "Your team is not permitted to call this endpoint."}},
        "")[1], "AUTH.AUTHORIZATION.ENDPOINT_ACCESS_DENIED")
    check("429: the message inside the message is unwrapped", ex(429, {
        "message": "{\"message\": \"The maximum number of api calls allowed for api/v1/mixed_people/api_search is 600 "
                   "times per hour.\"}"}, "")[0].startswith("Apollo's rate limit is used up for now. The maximum"), True)
    check("422", ex(422, {"error": "Invalid parameters"}, "")[0], "Apollo could not use those filters: Invalid parameters")

    print("\n-- no key: nothing is called")
    real_env = apollo.env
    apollo.env = lambda name: None
    s = apollo.status()
    check("status without a key", (s["key_set"], s["connected"]), (False, False))
    import importlib
    importlib.reload(apollo)              # the real _call again, in place of the stubs
    apollo.env = lambda name: None
    got = None
    try:
        apollo._call("GET", "/users/api_profile")
    except apollo.ApolloError as e:
        got = e.code
    check("a call without a key raises NO_KEY", got, "NO_KEY")
    apollo.env = real_env

    print("\n-- the lead dialog for a project with no rubric")
    import explain
    row = {"id": "x", "name": "Firm 1", "domain": "firm1.com", "status": "ready_for_review", "fit_score": None,
           "metadata": {"apollo": {"id": OID[1], "name": "Firm 1", "industry": "entertainment",
                                   "estimated_num_employees": 40, "city": "Mumbai", "country": "India",
                                   "linkedin_url": "https://www.linkedin.com/company/firm1", "phone": "+91 22 1234"},
                        "apollo_people": {PID[1]: {"name": "P1 Q", "title": "Producer", "has_email": True}},
                        "saved_from": {"summary": "People · Job titles: producer", "at": "2026-09-19T10:00:00+00:00",
                                       "by": "owner@tvf.in"}}}
    contacts = explain.rank_contacts([{"id": "c1", "full_name": "P1 Q", "email": "p1@firm1.com",
                                       "email_status": "valid", "rank": 90}], "firm1.com")
    ex = explain.explain_lead("universal", {"rubric": []}, row, contacts)
    a = ex["analysis"]
    check("no verdict and no criteria: nothing to judge by", (a["verdict"], ex["criteria"]), (None, []))
    check("strengths: only what Contacts and Details do not say", [s.split(":")[0] for s in a["strengths"]],
          ["Verified email"])
    check("routes: Apollo's company phone and LinkedIn page",
          [r["label"] for r in ex["contact_routes"]["routes"]][:2], ["Phone (Apollo)", "LinkedIn (company page)"])
    check("tried: what Apollo revealed, not a website read", ex["contact_routes"]["tried"],
          ["Apollo revealed 1 person saved here; 1 came with an email address."])
    bad = dict(row, metadata=dict(row["metadata"], apollo=dict(row["metadata"]["apollo"], estimated_num_employees="abc")))
    got = explain.explain_lead("universal", {"rubric": []}, bad, contacts)["analysis"]["gaps"]
    check("a headcount that is not a number never breaks the dialog", got, ["Apollo gives no headcount for the company."])


def database():
    print("\n-- the lead store, against the database (rolled back)")
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'test', 'company', '{}')"
                    " returning id", ("zz-test-universal-" + uuid.uuid4().hex[:6],))
        seg = cur.fetchone()[0]
        rule = {"domains": ["theviralfever.com"], "name_patterns": ["the viral fever", "tvf"]}

        def person(i, org, email="p%d@%s", status="valid", **kw):
            d = {"apollo_id": PID[i], "name": "Person %d" % i, "first_name": "Person", "title": "Producer",
                 "email": ((email % (i, org.get("primary_domain"))) if "%s" in email else email) if email else None,
                 "email_status": status if email else "unknown", "linkedin_url": "https://www.linkedin.com/in/p%d" % i,
                 "seniority": "director", "city": "Mumbai", "country": "India", "organization": org}
            d.update(kw)
            return d
        firm = {"id": OID[0], "name": "Chitra Films", "primary_domain": "chitrafilms.com", "industry": "entertainment",
                "estimated_num_employees": 18, "city": "Mumbai", "country": "India"}
        tvf = {"id": OID[1], "name": "The Viral Fever", "primary_domain": "theviralfever.com"}
        tvf_sub = {"id": OID[2], "name": "TVF Play", "primary_domain": "play.theviralfever.com"}
        nodomain = {"id": OID[3], "name": "Garage Studio"}
        rep = store.save_people(cur, seg, [person(0, firm), person(1, firm, email=None), person(2, tvf),
                                           person(3, tvf_sub), person(4, nodomain, email="p4@garage.studio")], rule,
                                {"summary": "People · test", "at": "2026-09-19T10:00:00+00:00", "by": "test"})
        check("five revealed: three saved, TVF and its subdomain refused",
              (rep["saved"], rep["with_email"], rep["companies_created"], [s["why"] for s in rep["skipped"]]),
              (3, 2, 2, ["it is TVF (theviralfever.com)", "it is TVF (theviralfever.com)"]))
        cur.execute("select name, domain, source, status, metadata->>'industry', metadata->>'employees',"
                    " metadata->'saved_from'->>'summary' from entities where segment_id = %s order by name", (seg,))
        check("companies: source apollo, To review, the board's fields filled", cur.fetchall(), [
            ("Chitra Films", "chitrafilms.com", "apollo", "ready_for_review", "entertainment", "18", "People · test"),
            ("Garage Studio", None, "apollo", "ready_for_review", None, None, "People · test")])
        cur.execute("select c.full_name, c.email, c.email_status, c.source, c.linkedin_url is not null"
                    " from contacts c join entities e on e.id = c.entity_id where e.segment_id = %s"
                    " order by c.full_name", (seg,))
        check("contacts: with and without an address, LinkedIn kept", cur.fetchall(), [
            ("Person 0", "p0@chitrafilms.com", "valid", "apollo", True),
            ("Person 1", None, "unknown", "apollo", True),
            ("Person 4", "p4@garage.studio", "valid", "apollo", True)])
        check("saved people are known by their Apollo ID", sorted(store.saved_person_ids(cur, seg, PID[:6])),
              sorted([PID[0], PID[1], PID[4]]))
        rep = store.save_people(cur, seg, [person(0, dict(firm, industry=None, estimated_num_employees=None))], rule)
        cur.execute("select count(*) from contacts c join entities e on e.id = c.entity_id where e.segment_id = %s", (seg,))
        n = cur.fetchone()[0]
        cur.execute("select metadata->>'industry' from entities where segment_id = %s and domain = 'chitrafilms.com'",
                    (seg,))
        check("the same person again: no second contact, nothing erased", (rep["companies_updated"], n,
                                                                          cur.fetchone()[0]), (1, 3, "entertainment"))
        rep = store.save_companies(cur, seg, [{"id": OID[0], "name": "Chitra Films", "primary_domain": "chitrafilms.com"},
                                              {"id": OID[5], "name": "New Co", "website_url": "https://www.newco.in/about"}],
                                   rule, {"summary": "Companies · test"})
        cur.execute("select domain, metadata->>'industry' from entities where segment_id = %s order by domain", (seg,))
        check("a company search save: one updated, one new, nothing erased",
              (rep["companies_updated"], rep["companies_created"], cur.fetchall()),
              (1, 1, [("chitrafilms.com", "entertainment"), ("newco.in", None), (None, None)]))
        cur.execute("update entities set status = 'rejected' where segment_id = %s and domain = 'newco.in'", (seg,))
        rep = store.save_people(cur, seg, [person(6, {"id": OID[5], "name": "New Co", "primary_domain": "newco.in"})], rule)
        check("a rejected company is never brought back", (rep["saved"], rep["skipped"][0]["why"]),
              (0, "New Co was rejected earlier"))
        check("saved companies are known, with their status",
              store.saved_company_ids(cur, seg, [OID[0], OID[5], OID[9]]),
              {OID[0]: "ready_for_review", OID[5]: "rejected"})
        rep = store.save_people(cur, seg, [person(7, firm, status="not-a-status"), person(8, firm)], rule)
        check("one row that fails is reported; the rest are still saved",
              (rep["saved"], rep["skipped"][0]["name"], rep["skipped"][0]["why"].startswith("could not be saved")),
              (1, "Person 7", True))
        cur.execute("select to_regclass('saved_searches') is not null")
        if cur.fetchone()[0]:
            cur.execute("insert into saved_searches (segment_id, name, kind, filters) values (%s, 'Heads', 'people', '{}')"
                        " returning id", (seg,))
            cur.execute("insert into saved_searches (segment_id, name, kind, filters) values (%s, 'HEADS', 'people',"
                        " '{\"person_titles\": [\"head\"]}') on conflict (segment_id, lower(name)) do update set"
                        " filters = excluded.filters returning filters", (seg,))
            check("a saved search under a taken name (any case) is replaced", cur.fetchone()[0],
                  {"person_titles": ["head"]})
        else:
            print("skip  saved_searches is not created yet (sql/29_saved_searches.sql)")
    finally:
        conn.rollback()
        conn.close()


def main():
    offline()
    if "--offline" not in sys.argv:
        database()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks%s" % (bad, len(RESULTS), "" if "--offline" in sys.argv
                                             else " (all test rows rolled back)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
