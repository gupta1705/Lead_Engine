# Apollo search and contact constraints

Non-clipping projects accept new companies and contacts from Apollo. Clipping keeps its existing sources, qualification and email behavior.

Unaddressed copy may be saved for review before a company qualifies for a contact reveal. Apply `supabase/migrations/20261019105938_unaddressed_outreach_previews.sql` after `sql/38_apollo_verified_contacts.sql` to allow these draft previews. A preview has no assigned recipient and is visibly blocked in Outreach; assigning an unverified address, approving without a verified recipient, and sending without one remain prohibited. Once the company qualifies and has an eligible contact, **Use verified contact** links the existing copy for human review. This does not approve or send it.

Outreach supports business-category and pitched-service filters, numeric subscriber/view/lead-score ordering, and date ordering in both directions. Filters and sorting run before pagination; unknown audience metrics stay last and are displayed as unknown.

For Apollo projects, every search pass retains `contact_email_status=["verified"]`. A paid reveal is checked again: only a work email with Apollo status `verified` (normalized `valid`) can be stored. Historical unverified contacts remain visible but cannot satisfy contact eligibility, drafting, approval or sending. Bounce downgrades remain possible. The database checks both new contact writes and outbound claims.

Manual searches use the selected project's `apollo_discovery.searches` targeting groups. Each group keeps its industry/size pairing, geographic restrictions and any hiring/funding window. Lists may be narrowed; adding unrelated terms cannot widen the project rules. Saved searches are checked against the current configuration each time they run. Universal has no fixed targeting groups and keeps freeform searching, subject to verified emails and its other configured rules.

Search results carry a signed, expiring receipt tied to the user, project and configuration. Saving uses those original Apollo facts, rather than company fields supplied by the browser. Companies in constrained projects enter `discovered` for normal qualification. Manual contact reveals require a qualified company and the same score, site, country, role, cooldown, credit and previously-revealed-person checks. Current employer and verified email are checked again after the reveal.

LCX routing reads retained Apollo industries, keywords, description, actual headcount, headquarters and buying signals, plus evidence from the company's own site. All 18 services have Apollo-only regression examples. Live-action producers can reach AI VFX + Animation without legacy taxonomy. Known VFX/animation suppliers remain held even with a hiring signal. Shop displays, audiobooks and Reel Forge require supporting evidence; an audience label alone cannot choose them. Human service choices are preserved. An opener whose service changed must be drafted and reviewed again.

Release order: apply `sql/38_apollo_verified_contacts.sql`, then `sql/28_contact_rank.sql` and `sql/14_auto_shortlist.sql`; deploy the application and sync `config/segment.lcx-services.json` using its generated `sql/03f_segment_lcx_services.sql`. Back up LCX metadata before running `tools/lcx_judge.py` to update existing rule-selected routes. That step reads stored evidence, spends no Apollo credits, and sends no emails.

Verification: `tools/test_apollo_constraints.py` covers strict policies, request bypasses, all 18 routes and database gates. Its database fixtures roll back and Apollo is mocked. Existing Apollo, LCX scoring, composing, sending and scheduler suites check the preserved behavior. Run `tools/verify_repo.py` after synchronizing the live configuration.
