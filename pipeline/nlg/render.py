"""Stage 7 renderers: Stage 4-6 facts -> fact-locked plain-language findings.

Each renderer builds a FactSheet while it writes, so every displayed value is recorded with its
source, then runs the fact-lock check on the finished text.
"""

from __future__ import annotations

import pandas as pd

from pipeline.common import config
from pipeline.nlg import factlock
from pipeline.nlg.facts import FactSheet, NlgInputs, join_names
from pipeline.nlg.templates import plural, t, word

CATEGORY_ORDER = ("playground", "school", "park")  # children first
MAX_EXPOSURE_LINES = 3


# ----------------------------------------------------------------------------- shared rules


def verbal_key(p: float) -> str:
    for bound, key in config.VERBAL_PROBABILITY:
        if p >= bound:
            return key
    return "unlikely"


def severity_key(drop: float) -> str:
    for bound, key in config.SEVERITY_BANDS:
        if drop >= bound:
            return key
    return "small"


def incident_priority(level: str, exposure_state: str) -> str:
    """exposure_state: "relevant" (a POI within the radius), "none" (checked, nothing), "unknown"."""
    if level == "confirmed":
        return "high" if exposure_state == "relevant" else "medium"
    return "medium" if exposure_state == "relevant" else "low"


def needs_precaution(level: str, exposure_state: str) -> bool:
    return level == "confirmed" and exposure_state in ("relevant", "unknown")


def site_pois(inp: NlgInputs, site_id: str) -> tuple[str, pd.DataFrame]:
    """(data status "real"/"unavailable", relevant POIs sorted playground > school > park, nearest first)."""
    rows = inp.exposure[inp.exposure["site_id"] == site_id]
    if rows.empty or (rows["data_source"] != "real").all():
        return "unavailable", rows.iloc[0:0]
    relevant = rows[rows["is_exposure_relevant"] & (rows["data_source"] == "real")]
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return "real", relevant.assign(_o=relevant["category"].map(order)).sort_values(["_o", "nearest_poi_distance_m"])


def _poi_label(lang: str, row) -> str:
    """"Thomas Greene Playground (park)", or "a playground" when OSM has no name."""
    name = row["nearest_poi_name"]
    category = word(lang, "category", row["category"])
    if not isinstance(name, str) or name == "unnamed":
        return t(lang, "unnamed_poi", category=category)
    return t(lang, "named_poi", name=name, category=category)


def _exposure_sentences(fs: FactSheet, inp: NlgInputs, site_ids: list[str]) -> tuple[list[str], str]:
    """Exposure lines for the affected sites and the overall exposure state."""
    lang = fs.language
    unknown, lines = [], []
    for sid in site_ids:
        status, pois = site_pois(inp, sid)
        if status == "unavailable":
            unknown.append(sid)
            continue
        for _, p in pois.iterrows():
            lines.append((sid, p))
    state = "relevant" if lines else ("unknown" if unknown else "none")

    out = []
    for i, (sid, p) in enumerate(lines[:MAX_EXPOSURE_LINES]):
        src = f"exposure_features.parquet:{sid}/{p['category']}"
        out.append(t(
            lang, "exposure_poi",
            site=fs.site(f"poi{i}_site", sid, inp.site_name(sid)),
            distance=fs.num(f"poi{i}_distance_m", float(p["nearest_poi_distance_m"]), src),
            poi=fs.show(f"poi{i}_name", p["nearest_poi_name"], _poi_label(lang, p), src),
        ))
    if len(lines) > MAX_EXPOSURE_LINES:
        extra = len(lines) - MAX_EXPOSURE_LINES
        out.append(t(lang, "exposure_more", n=fs.count("poi_more", extra, "exposure_features.parquet"),
                     places_word=plural(lang, "place", extra)))
    if unknown:
        names = [fs.site(f"unknown_site{i}", s, inp.site_name(s)) for i, s in enumerate(unknown)]
        out.append(t(lang, "exposure_unknown", sites=join_names(lang, names)))
    if not lines and not unknown:
        out.append(t(lang, "exposure_none", radius=fs.num("radius_m", config.EXPOSURE_RADIUS_M, "config.EXPOSURE_RADIUS_M")))
    return out, state


def _finalise(fs: FactSheet, record: dict) -> dict:
    where = record["finding_id"]
    for part in (record["headline"], record["body"], record.get("precaution") or "", *record["caveats"]):
        factlock.check(part, fs.shown_values(), where=where)
    record["facts_json"] = fs.to_json()
    record["language"] = fs.language
    return record


# ----------------------------------------------------------------------------- F1 incidents


def render_incident(inp: NlgInputs, inc, lang: str = "en") -> dict:
    fs = FactSheet(language=lang)
    src_inc = f"detector_incidents.parquet:{inc['incident_id']}"
    affected = [s for s in inp.sites.index if s in set(inc["affected_site_ids"])]  # head -> mouth
    a = inp.alerts
    rows = a[
        a["site_id"].isin(affected)
        & (a["week_start"] >= inc["start_week"])
        & (a["week_start"] <= inc["end_week"])
    ]
    flagged = rows[rows["alert_level"] != "none"]
    level = inc["max_alert_level"]
    p_max = float(flagged["p_change"].max())
    conf_key = verbal_key(p_max)
    if level == "possible" and conf_key == "very_likely":
        conf_key = "likely"  # "very likely" is reserved for confirmed changes
    fs.show("p_change_max", p_max, word(lang, "verbal", conf_key), "detector_alerts.parquet:p_change")
    confidence = word(lang, "verbal", conf_key)

    names = [fs.site(f"site{i}", s, inp.site_name(s)) for i, s in enumerate(affected)]
    if len(names) <= 2:
        sites_text = join_names(lang, names)
    else:
        sites_text = t(lang, "n_other_sites", first=names[0], n=fs.count("n_other_sites", len(names) - 1, src_inc),
                       sites_word=plural(lang, "site", len(names) - 1))
    when = fs.when("when", inc["start_week"], inc["end_week"], src_inc)
    headline = t(lang, "incident_headline", confidence=confidence, sites=sites_text, when=when)

    body, caveats = [], []
    drop = float(inc["peak_drop_W"])
    rise = flagged["rise_H_median"].max() if "rise_H_median" in flagged else None
    sev = word(lang, "severity", severity_key(drop))
    drop_s = fs.num("peak_drop_W", drop, f"{src_inc}:peak_drop_W")
    if rise is not None and pd.notna(rise):
        body.append(t(lang, "incident_change", drop=drop_s,
                      rise=fs.num("peak_rise_H", float(rise), "detector_alerts.parquet:rise_H_median"), severity=sev))
    else:
        body.append(t(lang, "incident_change_no_h", drop=drop_s, severity=sev))

    n_weeks = int(rows["week_start"].nunique())
    n_rep = int(rows["n_reports"].sum())
    n_reports = fs.count("n_reports", n_rep, "detector_alerts.parquet:n_reports")
    reports_word = plural(lang, "report", n_rep)
    if n_weeks == 1:
        body.append(t(lang, "incident_support_one_week", n_reports=n_reports, reports_word=reports_word))
    else:
        body.append(t(lang, "incident_support", n_reports=n_reports, reports_word=reports_word,
                      n_weeks=fs.count("n_weeks", n_weeks, src_inc)))
    if bool(flagged["mixing_flag"].any()):
        caveats.append(t(lang, "incident_mixed"))

    # Entry point
    top = inc["top_source"]
    if top is None or pd.isna(top):
        body.append(t(lang, "entry_none"))
    else:
        top_prob = float(inc["top_source_prob"])
        top_name = fs.site("top_source", top, inp.site_name(top))
        if top_prob < config.VERBAL_PROBABILITY[-1][0]:
            body.append(t(lang, "entry_unclear", site=top_name))
        else:
            ups = inp.upstream_of.get(top, [])
            segment = (
                t(lang, "segment_between", upstream=join_names(lang, [fs.site(f"upstream{i}", u, inp.site_name(u)) for i, u in enumerate(ups)]), site=top_name)
                if ups else t(lang, "segment_head", site=top_name)
            )
            src_conf = word(lang, "verbal", verbal_key(top_prob))
            fs.show("top_source_prob", top_prob, src_conf, f"{src_inc}:top_source_prob")
            body.append(t(lang, "entry", confidence=src_conf, segment=segment))
            others = [s for s in inc["credible_set"] if s != top]
            if others:
                body.append(t(lang, "entry_alternatives", sites=join_names(
                    lang, [fs.site(f"alt{i}", s, inp.site_name(s)) for i, s in enumerate(others)])))
        if bool(inc["upstream_unobserved"]):
            body.append(t(lang, "entry_upstream_unobserved"))

    # Rain link: "consistent with a CSO" only when all three conditions hold.
    if bool(inc["rain_week"]):
        cso_source = top is not None and not pd.isna(top) and bool(inp.sites.loc[top, "is_cso_outfall_adjacent"])
        cso_supported = inp.rain.get("cso_adjacent", {}).get("verdict") == "supported"
        body.append(t(lang, "rain_cso" if (cso_source and cso_supported) else "rain_plain"))

    # One Health exposure
    exposure_lines, exposure_state = _exposure_sentences(fs, inp, affected)
    body.extend(exposure_lines)

    record = {
        "finding_id": f"incident:{inc['incident_id']}",
        "finding_type": "incident",
        "scope_id": inc["incident_id"],
        "week_start": inc["start_week"],
        "week_end": inc["end_week"],
        "priority": incident_priority(level, exposure_state),
        "confidence_label": confidence,
        "is_recent": bool(inc["end_week"] >= inp.weeks[-config.RECENT_WEEKS]),
        "headline": headline,
        "body": " ".join(body),
        "precaution": t(lang, "precaution") if needs_precaution(level, exposure_state) else None,
        "caveats": caveats,
        "model_variant": inc["model_variant"],
    }
    return _finalise(fs, record)


# ----------------------------------------------------------------------------- F2 site status


def render_site_status(inp: NlgInputs, site_id: str, recent_incidents: dict[str, str], lang: str = "en") -> dict:
    fs = FactSheet(language=lang)
    week = inp.latest_week
    sc = inp.scores[inp.scores["site_id"] == site_id].sort_values("week_start")
    row = sc[sc["week_start"] == week].iloc[0]
    src = f"model_scores.parquet:{site_id}/{week.isoformat()}"
    name = fs.site("site", site_id, inp.site_name(site_id))
    when = fs.when("week", week, week, src)
    body, caveats = [], []

    if row["evidence"] == "insufficient":
        headline = t(lang, "site_headline_insufficient", site=name)
        reported = sc[sc["n_reports"] > 0]
        if reported.empty:
            body.append(t(lang, "site_never_reported"))
        else:
            gap = inp.weeks.index(week) - inp.weeks.index(reported["week_start"].iloc[-1])
            body.append(t(lang, "site_last_report", k=fs.count("weeks_since_report", gap, "model_scores.parquet:n_reports"),
                          weeks_word=plural(lang, "week", gap), when=when))
    else:
        typical = float(sc["W_q50"].median())
        fs.num("site_typical_W", typical, f"model_scores.parquet:{site_id}/median(W_q50)")
        comparison = "lower" if row["W_q95"] < typical else "higher" if row["W_q05"] > typical else "typical"
        headline = t(
            lang, "site_headline", site=name,
            w=fs.num("W", row["W_q50"], f"{src}:W_q50"),
            w_lo=fs.num("W_lo", row["W_q05"], f"{src}:W_q05"),
            w_hi=fs.num("W_hi", row["W_q95"], f"{src}:W_q95"),
            comparison=word(lang, "comparison", comparison),
        )
        body.append(t(lang, "site_h", h=fs.num("H", row["H_q50"], f"{src}:H_q50"),
                      h_lo=fs.num("H_lo", row["H_q05"], f"{src}:H_q05"), h_hi=fs.num("H_hi", row["H_q95"], f"{src}:H_q95")))
        body.append(t(lang, "site_reports", n=fs.count("n_reports", row["n_reports"], f"{src}:n_reports"),
                      reports_word=plural(lang, "report", int(row["n_reports"])), when=when))
        if row["evidence"] == "weak":
            caveats.append(t(lang, "caveat_limited_evidence"))
        if bool(row["mixing_flag"]):
            caveats.append(t(lang, "caveat_bimodal"))

    status, pois = site_pois(inp, site_id)
    radius = fs.num("radius_m", config.EXPOSURE_RADIUS_M, "config.EXPOSURE_RADIUS_M")
    if status == "unavailable":
        body.append(t(lang, "site_nearby_unknown"))
    elif pois.empty:
        body.append(t(lang, "site_nearby_none", radius=radius))
    else:
        places = [
            fs.show(f"poi{i}_name", p["nearest_poi_name"], _poi_label(lang, p), f"exposure_features.parquet:{site_id}/{p['category']}")
            for i, (_, p) in enumerate(pois.iterrows())
        ]
        body.append(t(lang, "site_nearby", radius=radius, places=join_names(lang, places)))

    incident_id = recent_incidents.get(site_id)
    if incident_id:
        body.append(t(lang, "site_in_incident", incident=fs.show("incident", incident_id, incident_id, "detector_incidents.parquet")))

    record = {
        "finding_id": f"site:{site_id}",
        "finding_type": "site_status",
        "scope_id": site_id,
        "week_start": week,
        "week_end": week,
        "priority": "info",
        "confidence_label": word(lang, "evidence", row["evidence"]),
        "is_recent": True,
        "headline": headline,
        "body": " ".join(body),
        "precaution": None,
        "caveats": caveats,
        "model_variant": str(row["model_variant"]),
    }
    return _finalise(fs, record)


# ----------------------------------------------------------------------------- F3 rain pattern


def render_rain(inp: NlgInputs, lang: str = "en") -> dict:
    fs = FactSheet(language=lang)
    r = inp.rain
    src = "detector_rain.json"
    verdict = r["verdict"]
    pooled = r["pooled"]
    fs.show("verdict", verdict, verdict, f"{src}:verdict")
    body = []
    if verdict == "supported":
        headline = t(lang, "rain_headline_supported")
        body.append(t(lang, "rain_supported", irr=fs.num("irr", pooled["irr_median"], f"{src}:pooled.irr_median", 1),
                      lo=fs.num("irr_lo", pooled["irr_q05"], f"{src}:pooled.irr_q05", 1),
                      hi=fs.num("irr_hi", pooled["irr_q95"], f"{src}:pooled.irr_q95", 1)))
        if r.get("cso_adjacent", {}).get("verdict") == "supported":
            cso = [s for s in inp.sites.index if bool(inp.sites.loc[s, "is_cso_outfall_adjacent"])]
            body.append(t(lang, "rain_cso_clearest", sites=join_names(
                lang, [fs.site(f"cso{i}", s, inp.site_name(s)) for i, s in enumerate(cso)])))
        if r.get("other_sites", {}).get("verdict") == "supported":
            body.append(t(lang, "rain_other_sites_too"))
        share = r.get("sewage_smell_share") or {}
        if share.get("rain_weeks") is not None and share.get("dry_weeks") is not None:
            if share["rain_weeks"] > share["dry_weeks"]:
                body.append(t(lang, "rain_sewage_more",
                              rain_pct=fs.pct("sewage_share_rain", share["rain_weeks"], f"{src}:sewage_smell_share.rain_weeks"),
                              dry_pct=fs.pct("sewage_share_dry", share["dry_weeks"], f"{src}:sewage_smell_share.dry_weeks")))
            else:
                body.append(t(lang, "rain_sewage_not_more"))
    elif verdict == "inconclusive":
        headline, body = t(lang, "rain_headline_inconclusive"), [t(lang, "rain_inconclusive")]
    elif verdict == "not supported":
        headline, body = t(lang, "rain_headline_not_supported"), [t(lang, "rain_not_supported")]
    else:
        headline, body = t(lang, "rain_headline_insufficient"), [t(lang, "rain_insufficient")]

    # Model-assisted corroboration is kept in the facts for the "why?" view, never in the text.
    if "corroboration_beta_rain" in r:
        fs.facts["corroboration_beta_rain"] = {"value": r["corroboration_beta_rain"], "shown": "", "source": src}

    record = {
        "finding_id": "network:rain",
        "finding_type": "rain_pattern",
        "scope_id": "network",
        "week_start": inp.weeks[0],
        "week_end": inp.weeks[-1],
        "priority": "info",
        "confidence_label": word(lang, "verbal", verbal_key(pooled["p_irr_gt_1"])) if verdict != "insufficient evidence" else None,
        "is_recent": False,
        "headline": headline,
        "body": " ".join(body),
        "precaution": None,
        "caveats": [t(lang, "caveat_association")],
        "model_variant": r["model_variant"],
    }
    return _finalise(fs, record)


# ----------------------------------------------------------------------------- F4 coverage


def render_coverage(inp: NlgInputs, lang: str = "en", n_least: int = 2) -> dict:
    fs = FactSheet(language=lang)
    sc = inp.scores
    src = "model_scores.parquet"
    n_weeks = len(inp.weeks)
    observed = sc[sc["n_reports"] > 0]
    weeks_by_site = observed.groupby("site_id")["week_start"].nunique().reindex(inp.sites.index, fill_value=0)
    n_weeks_s = fs.count("n_weeks", n_weeks, src)
    body = [t(lang, "coverage_body",
              n_reports=fs.count("n_reports", int(sc["n_reports"].sum()), f"{src}:n_reports"),
              n_sites=fs.count("n_sites", len(inp.sites), "sites.parquet"),
              n_weeks=n_weeks_s)]
    least = weeks_by_site.sort_values(kind="stable").head(n_least)
    for i, (sid, k) in enumerate(least.items()):
        body.append(t(lang, "coverage_least", site=fs.site(f"least{i}", sid, inp.site_name(sid)),
                      k=fs.count(f"least{i}_weeks", int(k), f"{src}:n_reports"), n_weeks=n_weeks_s))
    body.append(t(lang, "coverage_cta"))
    body.append(t(lang, "disclaimer"))

    record = {
        "finding_id": "network:coverage",
        "finding_type": "coverage",
        "scope_id": "network",
        "week_start": inp.weeks[0],
        "week_end": inp.weeks[-1],
        "priority": "info",
        "confidence_label": None,
        "is_recent": False,
        "headline": t(lang, "coverage_headline", pct=fs.pct("coverage", len(observed) / len(sc), src)),
        "body": " ".join(body),
        "precaution": None,
        "caveats": [],
        "model_variant": str(sc["model_variant"].iloc[0]),
    }
    return _finalise(fs, record)
