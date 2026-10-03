"""All Stage 7 wording, keyed by language. This is the only file a translator touches.

Rules for editing:
  * No digits in any template: every number must come from a fact (see facts.FactSheet),
    otherwise the fact-lock check fails.
  * Never "safe"/"unsafe"/"caused"/"definitely"/... (see factlock.BANNED_WORDS). Attribution
    wording is limited to "consistent with" and "followed".
  * Placeholders use str.format names; renderers fill every one of them.
"""

from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "en": {
        # -- shared vocabulary --------------------------------------------------------------
        "verbal": {"very_likely": "very likely", "likely": "likely", "possibly": "possibly", "unlikely": "unlikely"},
        "severity": {"large": "a large", "moderate": "a moderate", "small": "a small"},
        "category": {"playground": "playground", "school": "school", "park": "park"},
        "unnamed_poi": "a {category}",
        "named_poi": "{name} ({category})",
        "and": "and",
        "units": {"report": ("report", "reports"), "week": ("week", "weeks"), "site": ("nearby site", "nearby sites"),
                  "place": ("more nearby place", "more nearby places")},
        "list_sep": ", ",
        "date": "{day} {month} {year}",
        "when_single": "week of {start}",
        "when_range": "{start} to {end}",
        "n_other_sites": "{first} and {n} {sites_word}",
        "evidence": {"sufficient": "good evidence", "weak": "limited evidence", "insufficient": "insufficient evidence"},
        # -- F1 incident --------------------------------------------------------------------
        "incident_headline": "Water quality {confidence} dropped at {sites} ({when})",
        "incident_change": (
            "At its peak, the water-quality index fell by about {drop} points and the health-risk "
            "index rose by about {rise} points, {severity} change."
        ),
        "incident_change_no_h": "At its peak, the water-quality index fell by about {drop} points, {severity} change.",
        "incident_support": "This is based on {n_reports} citizen {reports_word} over {n_weeks} weeks.",
        "incident_support_one_week": "This is based on {n_reports} citizen {reports_word} in one week.",
        "incident_mixed": "Some reports in this period disagreed with each other.",
        "entry": "The contamination {confidence} entered {segment}.",
        "entry_unclear": "We could not pin down where it entered; {site} is only one of several possibilities.",
        "entry_none": "We could not tell where it entered.",
        "segment_between": "between {upstream} and {site}",
        "segment_head": "at or above {site}, the most upstream monitored point",
        "entry_alternatives": "It could also have entered near {sites}.",
        "entry_upstream_unobserved": "No one reported upstream at that time, so it may have entered further up the canal.",
        "rain_cso": "It followed heavy rain, which is consistent with a combined sewer overflow.",
        "rain_plain": "It followed a week of heavy rain.",
        "exposure_poi": "{site} is {distance} m from {poi}.",
        "exposure_more": "Plus {n} {places_word} where people gather.",
        "exposure_none": "No playgrounds, schools or parks were found within {radius} m of the affected spots.",
        "exposure_unknown": "We could not check for playgrounds, schools or parks near {sites}.",
        "precaution": (
            "As a general precaution, avoid direct contact with the water nearby, especially "
            "children and dogs, and report what you see."
        ),
        # -- F2 site status -----------------------------------------------------------------
        "site_headline": "{site}: water quality index {w} (likely {w_lo} to {w_hi}), {comparison} for this site",
        "site_headline_insufficient": "{site}: not enough recent reports to say",
        "comparison": {"typical": "typical", "lower": "lower than usual", "higher": "higher than usual"},
        "site_h": "The health-risk index is {h} (likely {h_lo} to {h_hi}).",
        "site_reports": "Based on {n} citizen {reports_word} in the {when}.",
        "site_last_report": "The last report here was {k} {weeks_word} before the {when}.",
        "site_never_reported": "There are no citizen reports from this spot yet.",
        "site_nearby": "Within {radius} m: {places}.",
        "site_nearby_none": "No playgrounds, schools or parks within {radius} m.",
        "site_nearby_unknown": "We could not check for nearby playgrounds, schools or parks.",
        "site_in_incident": "This spot is part of a recent likely contamination event ({incident}).",
        "caveat_limited_evidence": "Evidence for this week is limited.",
        "caveat_bimodal": "Reports for this week disagreed with each other.",
        # -- F3 rain pattern ----------------------------------------------------------------
        "rain_headline_supported": "Likely contamination is more common after heavy rain",
        "rain_headline_inconclusive": "Possible link between heavy rain and water quality, not yet clear",
        "rain_headline_not_supported": "No sign that heavy rain affects water quality here",
        "rain_headline_insufficient": "Too few reports from rainy weeks to judge the effect of rain",
        "rain_supported": (
            "Across the canal, likely contamination was about {irr} times as common in weeks with "
            "heavy rain (likely range {lo} to {hi})."
        ),
        "rain_cso_clearest": "The pattern is clearest near the combined sewer overflow outfalls: {sites}.",
        "rain_other_sites_too": "It also appears at the other monitored spots.",
        "rain_sewage_more": (
            "Citizen reports of a sewage smell were also more common after heavy rain ({rain_pct}% vs {dry_pct}%)."
        ),
        "rain_sewage_not_more": "Citizen reports of a sewage smell were not more common after heavy rain.",
        "rain_inconclusive": (
            "There are hints that likely contamination is more common after heavy rain, but the "
            "evidence is not strong enough to call it a pattern yet."
        ),
        "rain_not_supported": "Across the canal, likely contamination did not become more common after heavy rain.",
        "rain_insufficient": "There are too few reports from rainy weeks to say whether rain affects water quality here.",
        "caveat_association": "This is an association in the data, not proof of cause.",
        # -- F4 coverage --------------------------------------------------------------------
        "coverage_headline": "Citizen reports cover {pct}% of spot-weeks",
        "coverage_body": "Volunteers filed {n_reports} reports across {n_sites} spots over {n_weeks} weeks.",
        "coverage_least": "{site} had reports in {k} of {n_weeks} weeks.",
        "coverage_cta": "More reports from these spots would sharpen the picture.",
        "disclaimer": (
            "Based on volunteer observations, not laboratory tests. This is not an official health advisory."
        ),
    }
}


def t(language: str, key: str, **fields) -> str:
    """Template lookup + fill. Raises KeyError on a missing template or placeholder."""
    return TEMPLATES[language][key].format(**fields)


def word(language: str, group: str, key: str) -> str:
    return TEMPLATES[language][group][key]


def plural(language: str, unit: str, n: int) -> str:
    one, many = TEMPLATES[language]["units"][unit]
    return one if n == 1 else many
