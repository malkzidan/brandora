import uuid
import pytest
from decimal import Decimal
from app.nlu import (RuleContext, budget_products, classify_rules, extract_entities, find_products, is_decline,
                     is_hostile_text, is_pure_confirmation, match_faq, search_products, within_budget)
from app.schemas import INTENT_TO_E03, OWNER_REVIEW_INTENTS, MatchingProduct, Intent, RouterResult
@pytest.mark.parametrize("text,cap", [
    ("عندكم تيشيرت تحت 200 جنيه", 200), ("عايز حاجة ارخص من 500", 500), ("اقل من 150", 150),
    ("في حدود 300 جنيه", 300), ("ميزانيتي ميتين", 200), ("تحت تلتميه", 300), ("under 300", 300),
    ("t-shirt below 250 EGP", 250), ("cheaper than 90", 90), ("less than 1000", 1000), ("مايزيدش عن 400", 400),
    ("لحد 300 جنيه", 300), ("up to 100 egp", 100), ("تحت ٢٠٠", 200),
])
def test_max_price_is_extracted(text, cap):
    assert extract_entities(text).max_price == Decimal(cap)

@pytest.mark.parametrize("text", ["هاخد 2 تيشيرت", "لحد 5 مساء", "up to 20 pieces", "مقاس 42", "تحت", "تحت الطلب", "عايز تيشيرت"])
def test_no_false_budget(text):
    assert extract_entities(text).max_price is None

def test_the_budget_number_is_not_read_as_a_quantity_or_a_size():
    e = extract_entities("تيشيرت تحت 40 جنيه")
    assert e.max_price == Decimal(40) and e.quantity is None and e.size is None and [t.orig for t in e.product_tokens] == ["تيشيرت"]

def test_find_and_search_products_respect_the_ceiling():
    items = catalog("100", "250", None, "199.99", "200")
    toks = extract_entities("تيشيرت").product_tokens
    assert [str(p.basePrice) for p in find_products(toks, items, Decimal(200))] == ["100", "199.99", "200"]   # unpriced is out
    assert len(find_products(toks, items)) == 5                                                              # no ceiling: all
    assert [str(p.basePrice) for p in search_products("تيشيرت تحت 200 جنيه", items)] == ["100", "199.99", "200"]   # taken from the text
    assert len(search_products("تيشيرت تحت 200", items, Decimal(120))) == 1                                  # explicit cap wins
    assert within_budget(items[0], None) and not within_budget(items[2], Decimal(10))

def test_budget_products_are_cheapest_first_and_exclude_soldout_inactive_unpriced():
    items = catalog("300", "100", "200", None)
    items[1].isActive = True
    items.append(MatchingProduct(id="x", name="خلص", basePrice="50", trackInventory=True, stockQuantity=0))
    items.append(MatchingProduct(id="y", name="قديم", basePrice="40", isActive=False))
    assert [str(p.basePrice) for p in budget_products(items, Decimal(250))] == ["100", "200"]

@pytest.mark.parametrize("text,idx", [("الباقة بكام", 0), ("الباقه بكام؟", 0), ("بكام الباقات", 0), ("اللمبه الحمرا معلقه", 1),
                                      ("الموز بيوصل امتي", 2), ("عايز تيشيرت", None), ("حاجة", None)])
def test_match_faq(text, idx):
    got, score = match_faq(text, FAQS)
    assert got == idx and (idx is None or score >= 2)

def test_the_rule_classifier_routes_faq_questions_to_general_info_with_the_faq_number():
    r = classify_rules("الباقة بكام؟", RuleContext(faqs=FAQS))
    assert r.intents[0] == Intent.GENERAL_INFO and r.faq_id == 1
    assert classify_rules("الباقة بكام؟", RuleContext()).intents[0] != Intent.GENERAL_INFO   # no FAQs, no override

@pytest.mark.parametrize("ctx_name,text,yes,no", [
    ("order", "ايوه اكد", True, False), ("order", "تمام", True, False), ("order", "لا خلاص الغي", False, True),
    ("order", "بلاش", False, True), ("order", "cancel", False, True), ("order", "ايوه الغي", False, False),
    ("cancel", "ايوه الغي", True, False), ("cancel", "اه الغي", True, False), ("cancel", "yes cancel", True, False),
    ("cancel", "لا خلاص الغي", True, False), ("cancel", "ايوه", True, False), ("cancel", "confirm cancellation", True, False),
    ("cancel", "لا", False, True), ("cancel", "لا متلغيش", False, True), ("cancel", "متلغيش", False, True),
    ("cancel", "don't cancel", False, True), ("cancel", "keep it", False, True), ("cancel", "ايوه متلغيش", False, True),
    ("cancel", "مش عايز الغي", False, True), ("cancel", "اشتري تيشيرت", False, False),
    ("modify", "ايوه عدل", True, False), ("modify", "yes change it", True, False), ("modify", "اه غير", True, False),
    ("modify", "لا سيبه", False, True), ("modify", "مش عايز اعدل", False, True), ("modify", "متغيرش", False, True),
    ("modify", "don't change", False, True), ("modify", "ايوه", True, False),
])
def test_confirmation_and_decline_words_depend_on_the_question_we_asked(ctx_name, text, yes, no):
    assert is_pure_confirmation(text, ctx_name) is yes and is_decline(text, ctx_name) is no

def test_hostility_detector():
    assert is_hostile_text("هشتكي عليكم") and is_hostile_text("أنا دفعت ومحدش رد") and is_hostile_text("اتخصم مني مرتين")
    assert not is_hostile_text("الطلب اتأخر") and not is_hostile_text("دفعت وعايز اطلب") and not is_hostile_text("عايز تيشيرت")

def test_every_intent_maps_to_e03_and_only_three_are_owner_review():
    assert set(INTENT_TO_E03) == set(Intent) and len(list(Intent)) == 16
    assert OWNER_REVIEW_INTENTS == {Intent.PAYMENT_DISPUTE, Intent.LEGAL_THREAT, Intent.CUSTOM_REQUEST}





def catalog(*prices):
    return [MatchingProduct(id=str(uuid.uuid4()), name=f"تيشيرت {i}", category="تيشيرتات", basePrice=p, trackInventory=False)
            for i, p in enumerate(prices)]

FAQS = [{"question": "الباقة بكام؟", "keywords": ["باقة", "الباقات"], "answer": "x"},
        {"question": "اللمبة الحمرا معلقة", "keywords": ["لمبة"], "answer": "y"},
        {"question": "الموز بيوصل امتى؟", "keywords": ["موز"], "answer": "z"},
        {"question": "بدون إجابة", "keywords": ["حاجة"], "answer": ""}]
