"""Memory ledger (Part 8) — the anti-repetition system. One row per user/domain.

Fixes: #7 forecast/general/fame now have checklists; #8 dasha_basis stores only
the relevant window.
"""
import logging

from . import store

log = logging.getLogger("starsage.ledger")

MAX_LEDGER_ANGLES = 25
MAX_PLANNER_ANGLES = 10          # Part 15: inject last 10 into the Planner

DOMAIN_CHECKLISTS = {
    "career": [
        "D1_10th_house", "10th_lord_placement", "Saturn_condition", "Sun_condition",
        "Amatyakaraka", "D10_lagna", "D10_10th_house", "D10_10th_lord", "Mercury_condition",
        "6th_house_service", "aspects_on_10th", "current_MD_AD_PD",
        "Saturn_transit_from_lagna", "Jupiter_transit_from_lagna",
    ],
    "relationship": [
        "D1_7th_house", "7th_lord_condition", "Venus_condition", "Darakaraka",
        "Upapada_Lagna", "D9_lagna", "D9_7th_house", "D9_7th_lord", "Venus_nakshatra_pada",
        "Moon_condition", "aspects_on_7th", "Rahu_Ketu_on_7th_axis",
        "current_MD_AD_PD", "Jupiter_transit", "Saturn_transit",
    ],
    "wealth": [
        "D1_2nd_house", "2nd_lord", "D1_11th_house", "11th_lord", "Jupiter_condition",
        "Venus_condition", "D2_lagna", "D2_2nd_lord", "5th_house_speculation",
        "aspects_on_2nd", "aspects_on_11th", "current_MD_AD_PD", "Jupiter_transit",
    ],
    "health": [
        "D1_1st_house", "lagna_lord_condition", "D1_6th_house", "6th_lord",
        "Sun_condition", "Moon_condition", "Mars_condition", "aspects_on_lagna",
        "Saturn_transit_on_lagna", "current_MD_AD_PD",
    ],
    "property": [
        "D1_4th_house", "4th_lord", "Mars_condition", "Moon_condition",
        "D4_lagna", "D4_4th_lord", "current_MD_AD_PD", "Jupiter_transit",
    ],
    "children": [
        "D1_5th_house", "5th_lord", "Jupiter_condition", "D7_lagna", "D7_5th_lord", "current_MD_AD_PD",
    ],
    "spirituality": [
        "D1_9th_house", "9th_lord", "D1_12th_house", "12th_lord", "Atmakaraka",
        "Ketu_condition", "Jupiter_condition", "current_MD_AD_PD",
    ],
    "travel": [
        "D1_9th_house", "9th_lord", "D1_12th_house", "12th_lord", "Rahu_condition",
        "current_MD_AD_PD", "Jupiter_transit", "Rahu_transit",
    ],
    # Added (bug #7 / #10): previously missing.
    "fame": [
        "D1_10th_house", "10th_lord_placement", "5th_house", "11th_house", "Rahu_condition",
        "aspects_on_10th", "Fame_yoga_check", "current_MD_AD_PD", "Jupiter_transit",
    ],
    "forecast": [
        "current_MD_AD_PD", "upcoming_PDs", "Saturn_transit", "Jupiter_transit",
        "Rahu_Ketu_transit", "lagna_lord_condition", "Moon_condition",
    ],
    "general": [
        "lagna_condition", "lagna_lord_placement", "Moon_condition", "current_MD_AD_PD",
        "Atmakaraka", "dominant_yoga",
    ],
}


def get_or_create_ledger(user_id, domain):
    ledger = store.get_ledger_from_db(user_id, domain)
    if ledger is None:
        ledger = {
            "user_id": user_id,
            "domain": domain,
            "answered_angles": [],
            "used_mechanisms": [],
            "used_insight_axes": [],
            "predictions_made": [],
            "yogas_mentioned": [],
            "checklist_items_used": [],
            "unused_checklist_items": list(DOMAIN_CHECKLISTS.get(domain, [])),
            "last_updated": store.now_iso(),
        }
        store.save_ledger(user_id, domain, ledger)
    return ledger


def update_ledger(user_id, domain, planner_json, critic_json):
    ledger = get_or_create_ledger(user_id, domain)

    # Angle summary from the Critic (Generator may have diverged from the plan).
    ledger["answered_angles"].append(critic_json.get("angle_summary", ""))
    ledger["answered_angles"] = ledger["answered_angles"][-MAX_LEDGER_ANGLES:]

    if planner_json.get("mechanism"):
        ledger["used_mechanisms"].append(planner_json["mechanism"])
    if planner_json.get("insight_axis"):
        ledger["used_insight_axes"].append(planner_json["insight_axis"])

    yoga = planner_json.get("yoga_used")
    if yoga and yoga not in ledger["yogas_mentioned"]:
        ledger["yogas_mentioned"].append(yoga)

    if planner_json.get("intent") == "predictive" and planner_json.get("timing_windows"):
        for window in planner_json["timing_windows"]:
            ledger["predictions_made"].append({
                "id": store.generate_id(),
                "domain": domain,
                "prediction": critic_json.get("prediction_summary", ""),
                "timing": window,               # #8: only the relevant window, not the whole list
                "made_on": store.today(),
                "surfaced": False,
            })

    for item in planner_json.get("checklist_items_used", []):
        if item in ledger["unused_checklist_items"]:
            ledger["unused_checklist_items"].remove(item)
        if item not in ledger["checklist_items_used"]:
            ledger["checklist_items_used"].append(item)

    if not ledger["unused_checklist_items"]:
        ledger["unused_checklist_items"] = list(DOMAIN_CHECKLISTS.get(domain, []))
        ledger["checklist_items_used"] = []

    ledger["last_updated"] = store.now_iso()
    store.save_ledger(user_id, domain, ledger)
    _verify_write(user_id, domain, ledger)
    return ledger


def _verify_write(user_id, domain, expected):
    """Read the ledger back after every write and confirm the angle actually landed.

    The ledger is the anti-repetition memory: if a write is silently dropped the
    Planner keeps being told the angle is unused and re-answers it, which surfaces
    to the user as the assistant repeating itself several turns later — far from the
    real cause. One extra read per response is cheap insurance against that."""
    try:
        stored = store.get_ledger_from_db(user_id, domain)
        if not stored:
            log.error("ledger write LOST for user=%s domain=%s — row absent after save",
                      user_id, domain)
            return False
        want, got = expected["answered_angles"], stored.get("answered_angles") or []
        if len(got) != len(want) or (want and got[-1] != want[-1]):
            log.error("ledger write MISMATCH for user=%s domain=%s: expected %d angles "
                      "(last=%r), read back %d (last=%r)", user_id, domain, len(want),
                      want[-1] if want else None, len(got), got[-1] if got else None)
            return False
        log.info("ledger ok: user=%s domain=%s angles=%d mechanisms=%d unused_checklist=%d",
                 user_id, domain, len(got), len(stored.get("used_mechanisms") or []),
                 len(stored.get("unused_checklist_items") or []))
        return True
    except Exception as e:
        log.error("ledger write verification FAILED for user=%s domain=%s: %s: %s",
                  user_id, domain, type(e).__name__, e, exc_info=True)
        return False


def planner_view(ledger):
    """Compact ledger projection for the Planner (last 10 angles, per Part 15)."""
    return {
        "answered_angles": ledger["answered_angles"][-MAX_PLANNER_ANGLES:],
        "used_mechanisms": ledger["used_mechanisms"][-MAX_PLANNER_ANGLES:],
        "used_insight_axes": ledger["used_insight_axes"][-MAX_PLANNER_ANGLES:],
        "yogas_mentioned": ledger["yogas_mentioned"],
        "unused_checklist_items": ledger["unused_checklist_items"],
    }
