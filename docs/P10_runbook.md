# P10 — Manual enrichment via Apollo

**~45 min.** Needs the **Apollo API key errand done** — actually just the web app
login; the API key is P16's problem.

---

## This sitting is a measurement, not just data entry

P10 produces the **human baseline that Checkpoint 2 (P17) measures the Apollo
API against**: contact-find rate, role accuracy, email validity, and the miss
rate on 2–10-person shops — Apollo's known weak spot, and exactly your target
profile.

"The API found 60% of what a human found" is only a meaningful sentence if the
human half was done properly. So work carefully, and record misses as misses.

---

## Why these 12 companies

After P9, 212 connector-discovered entities are scored and **only 12 clear the
review threshold**. Those 12 are precisely the News RSS rows carrying
`international_ip_experience` — proven from a trade headline.

That is not a coincidence, it is the structure: **a connector can observe at
most one or two of six rubric criteria.** `right_size`,
`collaboration_openness`, `distribution_relationship` and
`reachable_decision_maker` all need a site visit or Apollo. Everything else in
the pool is sitting at 4–8 points because nothing is known about it, not because
it is bad.

So these 12 are the only rows where enrichment has something to build on:

**Mediapro Studio · LEONINE Studios · See-Saw Films · Dharma Productions ·
Epic Story Media · CCI Entertainment · Sentient Entertainment · Essential
Media · Highlander Production Company · Tua Films** (+2 borderline)

Two of the twelve — *Country House* and *Goin' Production* — are extraction
artefacts rather than companies. Rejecting them is a valid outcome and worth
recording; the extractor is precision-tuned but not perfect.

---

## Run it

```
python tools/run_sql.py sql/10_enrich_template.sql
```

That prints your worklist (STEP 1) and installs `set_scoring_input()`.

### For each company

**1. Find the domain first.** These rows have none — a headline names a company,
it does not link to its website. Search the name, confirm from the article it is
the same shop, record it. Apollo matches organisations far more reliably by
domain than by name.

**2. Apollo → Search → Companies**, filter by that domain.

**3. People**, filtered to the config's `target_contact_roles`: Founder,
Co-Founder, Head of Development, Development Executive, Executive Producer,
Head of Acquisitions, Head of Distribution.

**4. Reveal the email and note Apollo's verification status** — that maps
straight to `email_status`, and it is what P17 compares against.

**5. Read their actual site** and fill the inputs you can now judge.

Then copy the TEMPLATE block in the SQL file, replace the placeholders, run it.

---

## The one thing that is easy to get wrong

Use **`set_scoring_input()`**, not a hand-written `jsonb_set`.

It does two things that must happen together: writes the value, **and** removes
the key from `unverified_inputs`. That second part is load-bearing — P9's merge
step treats anything still listed there as overwritable by a later connector.
Set a value by hand without clearing the flag and a future News RSS run can
quietly overwrite your research with its own guess.

Verified working: setting `right_size` moved a row from 8 defaulted inputs to 7
and cleared the flag.

---

## Record a miss as a miss

If Apollo returns nobody, **do not skip the row**. The commented block at the
bottom of the SQL file records `enrichment_result = 'no_contact_found'` and sets
`reachable_decision_maker = 0`.

P17's entire question is whether Apollo misses small shops. That cannot be
answered from rows someone quietly passed over — a silent gap and a confirmed
miss look identical afterwards.

---

## Done when

- [ ] 5+ entities at `status = 'enriched'` with an Apollo-verified contact
- [ ] `scoring_inputs` filled from the real site, `unverified_inputs` shrinking
- [ ] Misses recorded explicitly, not skipped
- [ ] Re-scored — expect these rows to jump sharply, since they move from ~1 of
      6 criteria assessed to 5 or 6
- [ ] **Baseline numbers written into `BUILD_PLAN.md`** (the last query in the
      SQL file prints them): attempted, contact found, valid email, find rate

That last one is the actual deliverable. Everything else is how you get there.

---

## Then

**P11 — Checkpoint 1.** The first real calibration: approval rate on
*connector-discovered* candidates, broken out per source. Expect it to be well
below the 70% you got on the hand-curated P1 list — that batch was pre-filtered
by whoever built the spreadsheet, and this one is not.
