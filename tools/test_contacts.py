#!/usr/bin/env python3
"""test_contacts.py -- whose name an email greets, as a regression table.

    python tools/test_contacts.py

Every case is a real row from the live pool (2026-09-17). They fail in two
directions and both matter: a label or a street read as a person ("Hi
Photography,", "Hi Terminal,"), and a real person missed ("Hi team at Taste In
Motion, Inc." while the lead lists Becky Donahue). Exit code 1 on any failure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contacts as ct

# (scraped name, email, company, expected clean name)
CLEAN = [
    ("Becky Donahue Executive", "becky@tasteinmotion.com", "Taste In Motion, Inc.", "Becky Donahue"),
    ("Producer Katherine Lim", "katherine@nativecontent.com", "Native Content", "Katherine Lim"),
    ("Contact Jeffrey Levine", "jlevine@bronsoncanyonpictures.com", "Bronson Canyon Pictures", "Jeffrey Levine"),
    ("Cameron Escalante Cameron", "cameron@golden.la", "Golden Productions, Inc.", "Cameron Escalante"),
    ("Photography Jana Marx", "jana.marx@stinkfilms.com", "Stink Films USA", "Jana Marx"),
    ("Human Resources Amanda", "amanda@example-studio.com", "Example Studio", "Amanda"),
    ("Of Development Anne", "anne@example-studio.com", "Example Studio", "Anne"),
    ("Josephine Douet Controller", "jdouet@example.com", "Example", "Josephine Douet"),
    ("Dmytro Zvarykin E-mail", "dz@example.com", "Example", "Dmytro Zvarykin"),
    ("Film Julie Weitzell", "jweitzell@zoicstudios.com", "Zoic Studios", "Julie Weitzell"),
    ("Corwin Carrol New", "corwin@itsgoodtimes.com", "Good Times Production and Technology", "Corwin Carrol"),
    ("Office Manager Lasse", "lasse.holzmann@stinkfilms.com", "Stink Films USA", "Lasse"),
    ("United States Geno", "info@example.com", "Example", None),
    ("Terminal Ave Vancouver", "info@example.com", "Example", None),
    ("Map Public Relations", "pr@example.com", "Example", None),
    ("Distribution For", "distribution@dharma-production.com", "Dharma Productions", None),
    ("Contact For Licensing", "licensing@krattbrothers.com", "Kratt Brothers", None),
    ("New Business", "newbusiness@passerine.us", "Passerine", None),
    ("Soft White Underbelly", "info@softwhiteunderbelly.org", "Soft White Underbelly", None),
    ("Rahul Jain", "rahul@example.com", "Rahul Jain - Business coaching India", "Rahul Jain"),
    ("Tom Segura", "tom@example.com", "Tom Segura", "Tom Segura"),
    ("Sam Kelly Jr", "sam@invisiblecollective.co", "Invisible Collective", "Sam Kelly Jr"),
]

# (name, email, company, source, expected greeting)
GREET = [
    ("Becky Donahue", "becky@tasteinmotion.com", "Taste In Motion, Inc.", "site_scrape", "Becky"),
    ("Mike Parker", "info@lowbrowstudios.com", "Lowbrow Studios", "aicp_directory", "Mike"),
    ("Bryan Buckley", "reception@hungryman.com", "Hungry Man, Inc.", "aicp_directory", "Bryan"),
    ("Timothy Ward", "tim@bottlerocket360.com", "Bottle Rocket 360, LLC", "aicp_directory", "Tim"),
    ("Matthew N. Wilkinson", "matt@2mpros.com", "2M Productions", "aicp_directory", "Matt"),
    ("Qadree Holmes", "q.holmes@quriosityproductions.com", "Quriosity Productions LLC", "aicp_directory", "Qadree"),
    ("JJ Adler", "jj@ruckusfilms.com", "Ruckus Films", "aicp_directory", "JJ"),
    ("J.P. McMahon", "jp@example.com", "Example Films", "aicp_directory", "J.P."),
    ("Disco Meisch", "disco@hello-liebling.com", "Liebling", "site_scrape", "Disco"),
    ("London Faye Butler", "faye@1stavemachine.com", "1stAveMachine", "site_scrape", "Faye"),
    ("Matt Van Buren", "vanburensmail@yahoo.com", "Spare Parts", "aicp_directory", "Matt"),
    ("Jay Arthur Sterrenberg", "meerkats@meerkatmedia.org", "Meerkat Media", "aicp_directory", "Jay"),
    ("Sally Antonacchio", "nyc@theartistscompany.com", "The Artists Company", "aicp_directory", "Sally"),
    ("Corwin Carroll", "hello@itsgoodtimes.com", "Good Times Production and Technology", "aicp_directory", "Corwin"),
    ("Lasse", "lasse.holzmann@stinkfilms.com", "Stink Films USA", "site_scrape", "Lasse"),
    # a name paired with somebody else's mailbox: the mailbox's own first name, or nobody
    ("Cameron Escalante", "kevin@golden.la", "Golden Productions, Inc.", "pool:aicp_directory", "Kevin"),
    ("Carrie Callaway", "amy@therepublic.co", "The Republic", "pool:site_scrape", "Amy"),
    ("Andre Muir", "andrew@smugglersite.com", "SMUGGLER", "aicp_directory", "Andrew"),
    ("Tor Fitzwilliams", "hackett@anonymouscontent.com", "Anonymous Content", "site_scrape", None),
    # nobody named: a first-name mailbox is still a person, a surname or a place is not
    (None, "nina@tasteinmotion.com", "Taste In Motion, Inc.", "site_scrape", "Nina"),
    (None, "kramer@ironboundfilms.com", "Ironbound Films", "site_scrape", None),
    (None, "berlin@radicalmedia.com", "Radicalmedia", "site_scrape", None),
    (None, "info@myriadpictures.com", "Myriad Pictures", "site_scrape", None),
    (None, "accounting@kfilms.us", "K Films, Inc.", "site_scrape", None),
    # a show's name is never a person, even beside the host's own mailbox
    ("Tech Talk With Sanjeev", "techtalk@gmail.com", "Tech Talk With Sanjeev", "podcast_rss", None),
    ("Photography Jana Marx", "jana.marx@stinkfilms.com", "Stink Films USA", "site_scrape", "Jana"),
]

JUNK = [
    ("%20mail@insigniafilms.com", "a URL fragment, not an address"),
    ("firstname@supplyanddemand.tv", "a placeholder from the website's template"),
    ("hello@neonzoo.co", None),
    ("nmail@insigniafilms.com", "a line break read as part of the address"),
    ("ninfo@blackbearpictures.com", "a line break read as part of the address"),
    ("nina@tasteinmotion.com", None),
    ("not-an-address", "not a well-formed address"),
]


def main():
    bad = 0
    print("-- names read off pages")
    for raw, email, company, want in CLEAN:
        got = ct.clean_name(raw, email, company)
        ok = got == want
        bad += not ok
        print("%s  %-30s -> %r%s" % ("ok  " if ok else "FAIL", raw, got, "" if ok else "  (want %r)" % want))
    print("\n-- who the greeting names")
    for name, email, company, source, want in GREET:
        got = ct.first_name_for(name, email, company, source)
        ok = got == want
        bad += not ok
        print("%s  %-24s %-36s -> %r%s" % ("ok  " if ok else "FAIL", name or "(no name)", email, got,
                                           "" if ok else "  (want %r)" % want))
    print("\n-- addresses that must never be written to")
    for email, want in JUNK:
        got = ct.junk_reason(email)
        ok = got == want
        bad += not ok
        print("%s  %-30s -> %r" % ("ok  " if ok else "FAIL", email, got))
    print("\n%d failure(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
