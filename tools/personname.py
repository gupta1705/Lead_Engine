#!/usr/bin/env python3
"""personname.py -- pull the person out of a show.

The clipping segment's leads are shows and channels, but the email goes to a
person, and the owner's verdict on the first live pool was exact: "why are
there shows in the software". Feeds publish their business address under the
show's name, YouTube gives a channel title, and so the contact read "Tech Talk
With Sanjeev, contact: Tech Talk With Sanjeev". This module is the fix.

    extract_host(title, author=, owner_name=, description=, artist=)
        -> {"name", "first_name", "display", "confidence", "source"} or None
    looks_like_person(text)  -> bool
    greeting_name(full_name) -> first name, or None when the text is not a person

Where a person's name comes from, in order of trust:
  1. "with X" / "hosted by X" / "ft. X" in the title            (title_with)
  2. the feed's author or owner field when it reads as a name   (feed_author)
  3. "Rahul Jain - Business coaching India"                     (title_prefix)
  4. "The Joe Rogan Experience", "Dr. Shawn Baker Podcast"      (title_suffix)
  5. a title that IS a name, "Aswath Damodaran"                 (title_is_name)
  6. "I'm X" / "hosted by X" in the description                  (description)

Confidence is what decides whether a name is USED (high or medium name the
contact and the greeting; low is kept on the record for a human, nothing
more). The rules are deliberately conservative, and the first live pool set
them: "The Remarkable Leadership Podcast" is not hosted by Remarkable
Leadership, "MomCo Leaders" is not a person, "Cooking With Fire" has no host
called Fire. So words that name things, formats, qualities and businesses
disqualify a candidate outright; a name from a title pattern is high only
when its first word is a known first name or carries an honorific, and a
single first name is accepted only when it is a known one. A wrong greeting
costs a reply; a missing one costs nothing, because the fallback is "Hi there".
"""
import re

HONORIFICS = {"dr", "mr", "mrs", "ms", "miss", "mx", "prof", "professor", "sir", "dame", "coach", "pastor",
              "rev", "reverend", "father", "fr", "captain", "capt", "chef", "sensei", "guru", "swami", "shri",
              "smt", "sri", "pt", "pandit", "ustad", "dj", "mc", "sadhguru", "bishop", "rabbi", "imam",
              "judge", "senator", "mayor", "president", "ca", "adv", "doctor", "teacher", "uncle",
              "aunty", "auntie", "madam", "maam", "baba", "acharya"}

# words that name a thing, a format, a quality or a business -- never a person
ORG_WORDS = set("""
podcast podcasts show shows channel channels vlog vlogs media network networks studio studios production
productions official tv television radio news team teams inc llc ltd limited group entertainment films film
pictures daily weekly monthly university college church ministries ministry academy school institute company
co corp records music gaming games game tech technology techno reviews review finance financial learn learning
fast talk talks talking hour experience life world hub lab labs club cast live stories story history
documentaries documentary explained guide guides tips secrets journal report reports digest minute minutes
insider central zone nation planet project projects collective crew squad gang family kids cooking kitchen
travel fitness health wellness mindset motivation money wealth capital ventures partners agency consulting
coaching education english hindi tamil telugu marathi bengali gujarati punjabi urdu spanish french german
italian japanese chinese korean arabic russian portuguese dutch swedish turkish welsh irish scottish global
international national local original originals series episode episodes clips highlights best top new the
and with of for in on at to by from about into your our their his her its this that these those all every
fire pit love food coffee tea wine beer cars car dogs dog cats cat friends purpose passion style faith god
jesus science data code cash crypto bitcoin stocks stock sports sport art books book words ideas dreams power
energy mind soul heart yoga meditation business marketing sales startup startups founders founder investing
investor investors trading trader real estate property properties home homes house design digital online
video videos audio sound voice voices unfiltered uncut raw unplugged unscripted uncensored untold unknown
lessons lesson class classes masterclass course courses training tutorial tutorials reaction reactions
gameplay walkthrough recap recaps analysis commentary debate debates interview interviews conversation
conversations chat chats sessions session diaries diary notes journey journeys adventures adventure wild
nature outdoors garden gardening farm farming cricket football soccer basketball baseball tennis golf boxing
wrestling fight fighting mma ufc fantasy comedy funny laugh laughs jokes joke true crime mystery mysteries
horror scary thriller drama romance anime manga comics movie movies cinema theatre theater streaming stream
streams lives fashion beauty makeup skincare hair nails styles fit gym workout workouts run running cycling
swim swimming hike hiking camp camping fishing hunting bikes motorcycles trucks planes boats trains ai
machine robots robot space astronomy physics chemistry biology math maths geography economics politics
political policy law legal medical medicine doctor doctors nurse nursing dental dentist therapy therapist
psychology mental brain language languages grammar vocabulary vocab pronunciation accent listening speaking
practice fluent fluency beginner beginners intermediate advanced slow quick easy conversational subtitles
ielts toefl exam exams test tests prep upsc ssc neet jee gate mba bank banking sarkari govt government job
jobs career careers resume hr hiring recruit leadership leaders leader remarkable unconventional limitless
connected everyday modern simple smart better bold brave big little small great good real next first last
morning night late early happy healthy wealthy rich poor free hard deep high low open secret hidden inside
outside beyond future past present ultimate complete total pure honest curious creative critical practical
positive mindful conscious spiritual sacred holy divine natural organic urban rural american british indian
canadian australian african asian european tube fm am lounge room garage corner table desk bench cafe bar pub
floor stage arena field court ring track road street avenue lane way path route trip voyage ride drive flight
walk magnet talent concierge today tonight tomorrow yesterday weekend week month year years hours days
personal professional expert experts pro pros master masters mastery legends legend hero heroes champion
champions winner winners success successful growth growing scale scaling hustle grind mission vision
strategy strategies tactics playbook blueprint framework system systems method methods formula secrets
healthcare hospital hospitals clinic clinics care caring pharma pharmacy wellbeing nutrition diet recipes
recipe hoy hablamos habla hablar aprende aprender aprendo escucha escuchar cuentos historias noticias dia
semana espanol español portugues português francais français deutsch lernen apprendre parler leer lectura
nihongo con avec moi para per pour und der die das les des los las una uno una um uma
industries enterprises holdings brothers bros sons associates solutions services creative creatives works
workshop factory editor editors chief host hosts ceo
""".split())

# a compact first-name lexicon: English, Indian, Spanish, Portuguese, Arabic, Hebrew, common worldwide
FIRST_NAMES = set("""
aaron abby abdul abhishek abigail adam aditya adrian ahmed aisha ajay akash akshay alan albert alex
alexander alexandra alexis alfred ali alice alicia alison allison alyssa amanda amber amir amit amy
ana andre andrea andrew andy angela angel anil anita anjali ankit ankita ann anna anne annie anthony
anton antonio anurag aparna arjun arnav arun aryan ashish ashley ashok ashwin aswath austin avinash
ayesha barbara barry ben benjamin bernard beth betty bill billy blake bob bobby brad bradley brandon
brenda brent brett brian brittany bruce bryan caleb calvin cameron carl carla carlos carmen carol
caroline carolyn carrie casey catherine cathy chad chanie charles charlie charlotte chelsea cheryl chetan
chirag chris christian christin christina christine christopher cindy claire clara claudia clint cody colin
connor courtney craig crystal curtis cynthia dale damon dan dana daniel danielle danny darren dave david
dawn dean deborah debbie deepak deepika denise dennis derek devin dhruv diana diane diego dilip dinesh
divya dominic don donald donna doug douglas drew dustin dylan earl ed eddie edgar edward edwin eleanor
elena eli elizabeth ella ellen emily emma eric erica erik erin ethan eugene eva evan evelyn faisal farah
fatima felix fernando fiona frances francis frank fred gabriel gagan ganesh garima garrett gary gaurav
gautam gavin gene geoff geoffrey george gerald gina glen glenn gloria gopal gordon grace graham grant
greg gregory guy hadar hannah hardik harish harry harsh harshit heather helen henry himanshu holly howard
hugo ian ibrahim imran indira irene isaac isabel isabella ishaan ivan jack jackie jacob jade jai jake
james jamie jan jane janet jared jasmine jason javier jay jayesh jean jeff jeffrey jen jenna jennifer jenny
jeremy jerry jesse jessica jill jim jimmy joan joanna joe joel john johnny jon jonathan jordan jorge jose
joseph josh joshua joy joyce juan judy julia julian julie justin kabir kajal kamal kapil karan karen
karl karthik kate katherine kathleen kathy katie kavita kayla keith kelly ken kenneth kevin kim kimberly
kiran kirk krishna kristen kristin kunal kyle lakshmi lalit larry laura lauren lawrence layla leah lee
leila leo leonard leslie lewis liam lily linda lisa logan lori louis louise lucas lucy luis luke lynn
madhav madhu madison mahesh malcolm manish manoj marc marcus margaret maria marie marilyn marina mario
marion mark martha martin marvin mary mason matt matthew maureen max maya megan meghan mehul melanie
melissa michael michelle miguel mike miku milan mitchell mohammed mohit molly monica morgan muhammad
mukesh nadia nancy naomi natalie nathan naveen neha neil nicholas nick nicole nikhil niki nikita nina
nishant nitin noah nora oliver olivia om omar oscar owen pablo pallavi pankaj parth patricia patrick paul
paula pavan pawan pedro peter phil philip phillip piyush pooja prakash pranav prashant pratik praveen
preeti priya priyanka rachel rafael rahul raj rajat rajesh rajiv raju rakesh ralph ram ramesh randy
ranjit raphael rashmi ravi ray raymond rebecca reema regina rene renee rhonda ricardo richard rick ricky
rishabh rishi rita rob robert roberto robin rocky rodney roger rohan rohit roman ron ronald rosa rose ross
roy ruby russell ruth ryan sachin sagar sahil sally sam samantha sameer samuel sana sandeep sandra sandy
sanjay sanjeev santiago sara sarah sarthak saurabh scott sean sebastian seth shaan shane shannon sharon
shaun shawn sheila shilpa shivam shiv shreya shubham sid siddharth simon simran sneha sofia sonia sophia
sophie spencer stacy stanley stephanie stephen steve steven stuart sudhir sumit sunil sunita suresh susan
suzanne swati sylvia tanya tara tarun taylor ted teresa terry thema theresa thomas tiffany tim timothy
tina todd tom tommy tony tracy travis trevor troy tyler uday umesh utkarsh valerie vanessa varun veronica
vicky victor victoria vijay vikas vikram vinay vincent vinod virginia vishal vivek wade walter wanda
warren wayne wendy wesley will william willie yash yogesh yusuf zach zachary zack zara zoe
anand bala chandra dev devendra hari jagdish jyoti kartik kishore lalita lata mahima manisha meera mohan
murali nandini naresh nisha pradeep pramod prasad rachana radha raghav rajan rajni rekha ruchi sanjana
santosh saroj satish shalini shankar sharad shashi shweta smita sonal srinivas subhash sudha suman sushma
tanvi tejas uma usha vandana venkat vidya vishnu ajit alok amar amrita ankur anup archana ashutosh bhavna
bhupendra chaitanya darshan dhananjay dipika girish hemant ishita jayant jitendra kalpana kaushik kunal
madhavi mayank mihir mridula nalini neeraj nilesh pankaj paras pratibha purnima rajendra ravindra
ritu rupali sadhana sameera sanjiv shefali shilpi shobha shraddha shyam sonali sujit sujith
surya tanmay tushar vaibhav vikrant vimal vinita yamini yuvraj abraham adele adrienne agnes alberto
alejandro alfredo amelia andres angelo arturo aurora beatriz benedict bianca camila carlo cecilia
cesar christophe claude cristina dario dmitri dolores eduardo elias elisa emilio enrique esteban
fabio federico felipe florence francesco francisco frederick gabriela giovanni giulia gonzalo gustavo
hector helena ignacio ines ingrid isabelle ivo javiera joao joaquin jonas jorgen julio karim khadar
lars laurent leonardo lorenzo luca luciano lucia luisa manuel marcelo marco marta matteo mateo mauricio
maximilian mireille nicolas nikolai olga paolo patricio pierre raul renata ricardo rodrigo rosario
salvador sergio silvia simone stefan stefano teodoro tomas valentina valeria vicente viktor yuki yuto
hiroshi kenji sakura takeshi yusuke minjun jihoon seojun mei ling wei jun hao xin yan
""".split())

_TOKEN = r"(?:[A-Z]\.|(?:Dr|Mr|Mrs|Ms|Prof|St|Rev|Capt)\.|[A-ZÀ-ÖØ-Þ][^\W\d_'’.\-]*(?:['’.\-][^\W\d_]+)*)"
_NAME = r"(?:%s)(?:\s+(?:%s)){0,3}" % (_TOKEN, _TOKEN)
WITH_RE = re.compile(r"(?:^|[\s(|:\-–—])((?i:with|w/|ft\.?|feat\.?|featuring|hosted by|presented by|by))\s+(" + _NAME + ")")
WEAK_CUES = {"by", "presented by"}           # sponsors and credits hide behind these
SUFFIX_RE = re.compile(r"^(?:(?i:the)\s+)?(" + _NAME + r")(?:'s|’s)?\s+(?i:podcast|show|channel|vlog|vlogs|experience|hour|talks?|report|journal|cast|sessions?|diaries|diary|files|unfiltered|unplugged|uncut|explains)\b")
PREFIX_RE = re.compile(r"^(" + _NAME + r")\s*(?:[-–—:|]|'s\s|’s\s)")
DESC_RE = re.compile(r"((?i:hosted by|your host,?|with your host,?|i['’]m|i am|my name is|presented by))\s+(" + _NAME + ")")
STRONG_DESC_CUES = ("hosted by", "your host", "with your host")
SEPARATOR_RE = re.compile(r"\s+(?:and|&|x|with)\s+|\s*[,|/;]\s*|\s+[-–—]\s+", re.I)


def _first_part(text):
    """'Lindsay McMahon and Michelle Kaplan' -> 'Lindsay McMahon'."""
    return SEPARATOR_RE.split(text.strip(), maxsplit=1)[0].strip() if text else text
INITIAL_RE = re.compile(r"^[A-Z]\.$")
GLUED_HONORIFIC_RE = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof)\.(?=[A-Z])")


def _clean(tok):
    if INITIAL_RE.match(tok):
        return tok
    return tok.strip(" ,;:!?()[]{}\"“”‘’'").rstrip(".")


def tokens(text):
    text = GLUED_HONORIFIC_RE.sub(r"\1. ", text or "")
    return [t for t in (_clean(t) for t in re.split(r"\s+", text.strip())) if t]


def has_honorific(toks):
    return bool(toks) and toks[0].lower().rstrip(".") in HONORIFICS


def strip_honorific(toks):
    toks = list(toks)
    while toks and toks[0].lower().rstrip(".") in HONORIFICS:
        toks = toks[1:]
    return toks


WORD_SUFFIXES = ("ing", "tion", "sion", "ment", "ness", "ship", "ology", "ical", "ious", "ance", "ence",
                 "ity", "ism", "ful", "less", "able", "ible")


def _wordish(low):
    """'Spreading', 'Leadership', 'Ambition': English word shapes, not names."""
    return len(low) > 5 and low.endswith(WORD_SUFFIXES) and low not in FIRST_NAMES


def person_score(text):
    """0: not a person. 1: a single name. 2: a full name (two or more parts)."""
    toks = strip_honorific(tokens(text))
    if not toks or len(toks) > 4:
        return 0
    for i, t in enumerate(toks):
        if any(ch.isdigit() for ch in t):
            return 0
        low = t.lower().rstrip(".").replace("’", "'")
        if low in ORG_WORDS or (_wordish(low) and (i < len(toks) - 1 or len(toks) == 1)):
            return 0
        if not re.fullmatch(_TOKEN, t):
            return 0
        if t.isupper() and len(t) > 2:          # acronyms: UPSC, NBA, CNN
            return 0
    return 2 if len(toks) >= 2 else 1


def _known_first(toks):
    return bool(toks) and toks[0].lower() in FIRST_NAMES


def looks_like_person(text):
    """True when the text reads as a person under the same gate that names
    contacts and greetings: a known first name or honorific, or an unknown
    name of exactly two words. Titles never pass."""
    return _grade(text) is not None


def _shape(name_text, source, confidence):
    orig = tokens(name_text)
    toks = strip_honorific(orig)
    if not toks:
        return None
    first = None if INITIAL_RE.match(toks[0]) else toks[0]      # "J. Smith": no first name to greet by
    return {"name": " ".join(toks), "first_name": first, "display": " ".join(orig),
            "confidence": confidence, "source": source}


def _grade(text):
    """Confidence for a candidate name:
    high   -- the first word is a known first name, or an honorific is present
    medium -- an unknown name of exactly two words ("Hadar Shemesh"), or two
              words around an initial; anything longer without a known first
              name reads as a title ("Stuff You Should Know") and is refused
    None   -- not a person"""
    toks = tokens(text)
    stripped = strip_honorific(toks)
    sc = person_score(text)
    if sc == 0:
        return None
    if sc == 2:
        if _known_first(stripped) or has_honorific(toks):
            return "high"
        plain = [t for t in stripped if not INITIAL_RE.match(t)]
        return "medium" if len(plain) == 2 else None
    if _known_first(stripped):
        return "high" if has_honorific(toks) else "medium"
    return None


def extract_host(title, author=None, owner_name=None, description=None, artist=None):
    """The person behind a show, or None. See the module docstring for the
    order of trust and why single names and two-word titles are gated."""
    title = GLUED_HONORIFIC_RE.sub(r"\1. ", title or "")
    description = GLUED_HONORIFIC_RE.sub(r"\1. ", description) if description else description
    author, owner_name, artist = _first_part(author), _first_part(owner_name), _first_part(artist)
    cands = []                                  # (rank, shaped)

    for m in WITH_RE.finditer(title):
        cue, name = m.group(1).lower(), m.group(2)
        g = _grade(name)
        if g and (cue not in WEAK_CUES or g == "high"):
            cands.append((0, _shape(name, "title_with", g)))
            break

    for text, label in ((author, "feed_author"), (owner_name, "feed_owner"), (artist, "apple_artist")):
        if text and person_score(text) == 2 and _grade(text):
            cands.append((1, _shape(text, label, _grade(text))))

    m = PREFIX_RE.match(title)
    if m and person_score(m.group(1)) == 2:
        g = _grade(m.group(1))
        cands.append((2, _shape(m.group(1), "title_prefix", "high" if g == "high" else "low")))

    m = SUFFIX_RE.match(title)
    if m:
        g = _grade(m.group(1))
        if g:
            cands.append((3, _shape(m.group(1), "title_suffix", "high" if g == "high" else "low")))

    toks = strip_honorific(tokens(title))
    if 2 <= len(toks) <= 3 and person_score(" ".join(toks)) == 2:
        g = _grade(title)
        cands.append((4, _shape(title, "title_is_name", "high" if g == "high" else "low")))

    if description:
        m = DESC_RE.search(description[:800])
        if m:
            cue, name = m.group(1).lower(), m.group(2)
            g = _grade(name)
            if g == "high" or (g and cue.startswith(STRONG_DESC_CUES)):
                cands.append((5, _shape(name, "description", "medium")))

    # a feed whose author field is a single known first name ("Chris", "Miku")
    # is naming its host; good enough to greet by, so medium
    for text, label in ((author, "feed_author"), (owner_name, "feed_owner")):
        if text and person_score(text) == 1 and _known_first(strip_honorific(tokens(text))):
            cands.append((6, _shape(text, label, "medium")))

    cands = [c for c in cands if c[1]]
    if not cands:
        return None
    order = {"high": 0, "medium": 1, "low": 2}
    cands.sort(key=lambda c: (order[c[1]["confidence"]], c[0]))
    return cands[0][1]


def greeting_name(full_name):
    """First name for 'Hi X,' -- only when the text is a person."""
    if not full_name or not looks_like_person(full_name):
        return None
    toks = strip_honorific(tokens(full_name))
    return None if INITIAL_RE.match(toks[0]) else toks[0]


if __name__ == "__main__":                       # quick manual check
    import sys
    for t in sys.argv[1:] or ["Tech Talk With Sanjeev", "The L3 Leadership Podcast with Doug Smith",
                              "Dr. Shawn Baker Podcast", "Aswath Damodaran", "Cooking With Fire",
                              "Learn Welsh Fast", "The Joe Rogan Experience", "Techno Vihaan",
                              "Learn and Earn with Pavan Agrawal", "Best History Documentaries",
                              "The Remarkable Leadership Podcast", "Rahul Jain- Business coaching India",
                              "The Dr. Phil Podcast", "The Homecoming Podcast with Dr.Thema"]:
        print("%-45s -> %s" % (t, extract_host(t)))
