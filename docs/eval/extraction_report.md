# LISA Phase 2 — LLM extraction vs gold standard

Model `gpt-oss:120b` · prompts {'nodes': 'nodes-v1', 'edges': 'edges-v2'} · match threshold 0.3 · 23 scored units (few-shot units excluded: eoir_4018__u1of1, scotus_2017_17-269__u1of1)

## Headline (micro)

### All units

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| nodes_strict | 0.147 | 0.358 | 0.209 | 743 | 4296 | 1333 |
| nodes_relaxed | 0.204 | 0.495 | 0.289 | 1028 | 4011 | 1048 |
| edges_strict | 0.048 | 0.027 | 0.034 | 89 | 1780 | 3216 |
| edges_relaxed | 0.048 | 0.027 | 0.034 | 89 | 1780 | 3216 |

Macro (mean per unit): nodes_strict F1 0.241, nodes_relaxed F1 0.322, edges_strict F1 0.041, edges_relaxed F1 0.040

### Domain: immigration

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| nodes_strict | 0.211 | 0.401 | 0.277 | 312 | 1164 | 467 |
| nodes_relaxed | 0.268 | 0.508 | 0.351 | 396 | 1080 | 383 |
| edges_strict | 0.093 | 0.043 | 0.059 | 54 | 525 | 1195 |
| edges_relaxed | 0.083 | 0.038 | 0.052 | 48 | 531 | 1201 |

### Domain: litigation

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| nodes_strict | 0.121 | 0.332 | 0.177 | 431 | 3132 | 866 |
| nodes_relaxed | 0.177 | 0.487 | 0.260 | 632 | 2931 | 665 |
| edges_strict | 0.027 | 0.017 | 0.021 | 35 | 1255 | 2021 |
| edges_relaxed | 0.032 | 0.020 | 0.025 | 41 | 1249 | 2015 |

## Per type

### Node types (strict)

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| authority_ref | 0.161 | 0.587 | 0.253 | 227 | 1181 | 160 |
| fact | 0.088 | 0.405 | 0.144 | 100 | 1039 | 147 |
| holding | 0.222 | 0.251 | 0.236 | 66 | 231 | 197 |
| issue | 0.109 | 0.350 | 0.166 | 43 | 352 | 80 |
| opinion | 0.212 | 0.392 | 0.275 | 29 | 108 | 45 |
| outcome | 0.227 | 0.781 | 0.352 | 25 | 85 | 7 |
| reasoning | 0.142 | 0.183 | 0.160 | 113 | 684 | 503 |
| rule | 0.185 | 0.419 | 0.257 | 140 | 616 | 194 |

### Relations (strict)

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| agrees_with | 0.000 | 0.000 | 0.000 | 0 | 5 | 30 |
| applies_rule | 0.018 | 0.006 | 0.009 | 3 | 161 | 517 |
| disagrees_with | 0.000 | 0.000 | 0.000 | 0 | 6 | 110 |
| has_outcome | 0.106 | 0.151 | 0.125 | 5 | 42 | 28 |
| holds | 0.092 | 0.047 | 0.062 | 12 | 119 | 242 |
| presents_issue | 0.118 | 0.114 | 0.116 | 14 | 105 | 109 |
| relevant_to | 0.022 | 0.013 | 0.016 | 3 | 132 | 227 |
| relies_on | 0.031 | 0.021 | 0.025 | 12 | 371 | 571 |
| resolves | 0.021 | 0.010 | 0.013 | 2 | 93 | 203 |
| states_fact | 0.064 | 0.081 | 0.072 | 20 | 292 | 227 |
| states_rule | 0.063 | 0.039 | 0.048 | 13 | 194 | 317 |
| supports | 0.019 | 0.008 | 0.011 | 5 | 260 | 635 |

## Mapped spec tier

OVERRULES occurs once in gold: its P/R is not statistically meaningful. Doctrine is scored as rule-node P/R (gold has no canonical doctrine names).

### Mapped edges

| | P | R | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| FOLLOWS | 0.027 | 0.053 | 0.036 | 1 | 36 | 18 |
| DISTINGUISHES | 0.000 | 0.000 | 0.000 | 0 | 0 | 21 |
| OVERRULES | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 |
| CITES_LLM | 0.742 | 0.087 | 0.157 | 23 | 8 | 240 |
| AUTHORED_BY | 0.917 | 0.978 | 0.946 | 44 | 4 | 1 |
| Doctrine(rule) | 0.185 | 0.419 | 0.257 | 140 | 616 | 194 |

## Provenance

| provenance | count | precision |
|---|---|---|
| llm | 4011 | 0.185 |
| unverified | 1028 | 0.000 |

## Threshold sweep (strict)

| threshold | node P | node R | edge P | edge R |
|---|---|---|---|---|
| 0.1 | 0.179 | 0.435 | 0.071 | 0.040 |
| 0.2 | 0.162 | 0.393 | 0.063 | 0.035 |
| 0.3 | 0.147 | 0.358 | 0.048 | 0.027 |
| 0.4 | 0.125 | 0.303 | 0.041 | 0.023 |
| 0.5 | 0.107 | 0.259 | 0.031 | 0.018 |
| 0.6 | 0.086 | 0.209 | 0.018 | 0.010 |

## Error analysis

Each FP/FN is in exactly one bucket, checked in this order: wrong_type, granularity, quote_miss, endpoint_missed, wrong_relation, spurious/missed.

- **node**: spurious 2716, quote_miss 1028, missed 944, wrong_type 729, granularity 212
- **edge**: endpoint_missed 2824, quote_miss 1320, spurious 452, missed 388, wrong_relation 12

### spurious

- FP node `opinion` in `eoir_3371__u1of1` — Headnote (interim decision): “Interim Decision #3371”
- FP node `fact` in `eoir_3371__u1of1` — Respondent is a 29‑year‑old native of Ecuador: “The respondent is a 29-year-old native and citizen of Ecuador.”
- FP node `fact` in `eoir_3371__u1of1` — Service’s attempt to classify respondent as an aggravated felon: “The Service attempted to establish that the respondent was an aggravated felon, in that the amount of loss to the victim of the conspiracy was more than $200,000 dollars”
- FP node `rule` in `eoir_3371__u1of1` — Aggravated felony loss threshold: “See section 101(a)(43)(M)(i) of the Act, 8 U.S.C. § 1101(a)(43)(M)(i) (1994) (defining certain crimes as aggravated felonies based on the amount of monetary loss to the victim).”
- FP node `holding` in `eoir_3371__u1of1` — Appeal dismissed; waiver unavailable: “The appeal will be dismissed.”

### wrong_type

- FP node `opinion` in `eoir_3371__u1of1` — Majority opinion (Jones): “JONES, Board Member:”
- FP node `issue` in `eoir_3371__u1of1` — Whether the respondent must satisfy the seven‑year lawful presence requirement for a 212(h) waiver: “On appeal, the respondent argues that he is not bound by the requirement that 7 years of lawful presence be demonstrated in order to qualify for a waiver of inadmissibility under section 212(h) of the Act.”
- FP node `fact` in `eoir_3371__u1of1` — Statutory definition of “lawfully admitted for permanent residence”: “The term “lawfully admitted for permanent residence” means the status of having been lawfully accorded the privilege of residing permanently in the United States as an immigrant in accordance with the immigration laws, such status not having changed.”
- FP node `issue` in `eoir_3371__u1of1` — Whether a person previously admitted as a lawful permanent resident is “previously admitted” for purposes of INA §212(h) waiver eligibility: “whether the respondent “has previously been admitted” for permanent residence to the United States.”
- FP node `fact` in `eoir_3371__u1of1` — Respondent has not accrued seven years of lawful residence: “has failed to accrue 7 years of lawful residence since the date of his admission”

### quote_miss

- FP node `fact` in `eoir_3371__u1of1` — Immigration Judge’s deportability findings: “The Immigration Judge found the respondent deportable as charged, both on the basis of his conviction for a crime involving moral turpitude, and as an alien who was excludable at entry under section 212(a)(2)(A)(i)(I) of the Act”
- FP node `rule` in `eoir_3371__u1of1` — 212(h) waiver eligibility requires seven years lawful residence: “A discretionary waiver under section 212(h) of the Immigration and Nationality Act, 8 U.S.C. § 1182(h) (Supp. II 1996), is not available to an alien who has not lawfully resided continuously in the United States for the statutorily required period of 7 years”
- FP node `rule` in `eoir_3371__u1of1` — IIRIRA amendment adds conviction‑based bar to 212(h) waivers: “Section 212(h) of the Act was recently amended by section 348(a) of the Illegal Immigration Reform and Immigrant Responsibility Act of 1996, ... No waiver shall be granted under this subsection in the case of an alien who has previously been admitted to the United States as an alien lawfully admitted for permanent residence if either since the date of such admission the alien has been convicted of an alien has been convicted of an alien has been convicted...”
- FP node `fact` in `eoir_3371__u1of1` — Immigration Judge found respondent ineligible for a waiver because he lacked 7 years lawful residence: “Further, the Immigration Judge found the respondent ineligible for a waiver under section 212(h) of the Act because he had not resided in the United States lawfully for 7 years or more immediately preceding the date of initiation of his deportation proceedings”
- FP node `fact` in `eoir_3371__u1of1` — Section 212(h) amendment adds a 7‑year residency and aggravated felony bar to waiver eligibility: “No waiver shall be granted ... if the alien has not lawfully resided continuously in the United States for a period of not less than 7 years”

### granularity

- FP node `authority_ref` in `eoir_3371__u1of1` — Matter of R‑, 8 I&N Dec. 598 (Asst. Comm’r 1960): “Matter of R-, 8 I&N Dec. 598 (Asst. Comm’r 1960)”
- FP node `reasoning` in `eoir_3371__u1of1` — Consistent statutory construction favors substantive “lawful admission”: “I believe that the varied usage … would be given effect most reasonably … a lawful admission for permanent residence seems most reasonably construed as referring to a lawful admission in substance, rather than merely in form.”
- FN node `authority_ref` in `eoir_3371__u1of1` — Matter of Lok: “although a respondent maintains his permanent resident status until a final administrative order is issued, Matter of Lok, 18 I&N Dec. 101 (BIA 1981)”
- FP node `authority_ref` in `eoir_3380__u1of1` — Matter of Soriano: “Matter of Soriano, 21 I&N Dec. 516 (BIA 1996; A.G. 1997), followed.”
- FP node `authority_ref` in `eoir_3380__u1of1` — INA § 212(a)(6)(C)(i) (fraud inadmissibility): “Section 212(a)(6)(C)(i) of the Act states: [A]ny alien who, by fraud or willfully misrepresenting a material fact, seeks to procure (or has sought to procure or has procured) a visa, other documentation, or admission into the United States...”

### missed

- FN node `opinion` in `eoir_3371__u1of1` — Headnote / syllabus (publisher summary): “is not available to an alien who has been convicted of an aggravated felony, or to an alien who has not lawfully resided continuously in the United”
- FN node `opinion` in `eoir_3371__u1of1` — Board opinion (dismissing appeal): “This is a timely appeal from an April 22, 1997, decision of the Immigration Judge”
- FN node `holding` in `eoir_3371__u1of1` — Headnote: 212(h) waiver unavailable to prior LPR: “is not available to an alien who has been convicted of an aggravated felony, or to an alien who has not lawfully resided continuously in the United”
- FN node `holding` in `eoir_3371__u1of1` — Headnote: Michel inapplicable: “previously been lawfully admitted for permanent residence to the United States but later claims that such admission was not lawful”
- FN node `issue` in `eoir_3371__u1of1` — Does prior unlawful LPR admission avoid 212(h) seven-year bar: “The only issue on appeal relates to the Immigration Judge’s finding that the respondent was ineligible for a waiver under”

### endpoint_missed

- FN edge `presents_issue` in `eoir_3371__u1of1` — eoir_3371:opinion:majority -> eoir_3371:issue:212h_prior_lpr_unlawful_admission: “This is a timely appeal from an April 22, 1997, decision of the Immigration Judge”
- FN edge `states_fact` in `eoir_3371__u1of1` — eoir_3371:opinion:majority -> eoir_3371:fact:admitted_immigrant_1991: “This is a timely appeal from an April 22, 1997, decision of the Immigration Judge”
- FN edge `relevant_to` in `eoir_3371__u1of1` — eoir_3371:fact:admitted_immigrant_1991 -> eoir_3371:issue:212h_prior_lpr_unlawful_admission: “reentered on July 3, 1991, at which time he was admitted as an immigrant.”
- FN edge `states_fact` in `eoir_3371__u1of1` — eoir_3371:opinion:majority -> eoir_3371:fact:conspiracy_conviction_1996: “This is a timely appeal from an April 22, 1997, decision of the Immigration Judge”
- FN edge `relevant_to` in `eoir_3371__u1of1` — eoir_3371:fact:conspiracy_conviction_1996 -> eoir_3371:issue:212h_prior_lpr_unlawful_admission: “On April 26, 1996, the respondent was convicted in the United States District Court, District of Rhode Island, of conspiracy in violation of 18 U.S.C. § 371 (1994)”

### wrong_relation

- FP edge `holds` in `eoir_3395__u1of1` — eoir_3395:opinion:concurring_and_dissenting_opinion_john_w_guendelsberger -> eoir_3395:holding:appeal_is_not_moot_despite_respondent_s_departure_to_cuba: “the instant appeal has not been rendered moot or effectively withdrawn by the respondent’s departure from the United States to Cuba during the pendency of the appeal”
- FN edge `has_outcome` in `eoir_3395__u1of1` — eoir_3395:op:majority -> eoir_3395:outcome:appeal_sustained_vacated_remanded: “The appeal of the Immigration and Naturalization Service is sustained.”
- FP edge `relies_on` in `eoir_4128__u1of1` — eoir_4128:rule:circumstantial_evidence_may_satisfy_the_burden_of_proof -> eoir_4128:authority_ref:desert_palace_inc_v_costa_539_u_s_90_100_2003: “Desert Palace, Inc. v. Costa, 539 U.S. 90, 100 (2003).”
- FP edge `relies_on` in `eoir_4128__u1of1` — eoir_4128:rule:circumstantial_evidence_may_satisfy_the_burden_of_proof -> eoir_4128:authority_ref:holland_v_united_states_348_u_s_121_140_1954: “Holland v. United States, 348 U.S. 121, 140 (1954).”
- FN edge `relies_on` in `eoir_4128__u1of1` — eoir_4128:reasoning:circumstantial_evidence_can_suffice -> eoir_4128:authority_ref:desert_palace_v_costa: “Desert Palace, Inc. v. Costa, 539 U.S. 90, 100 (2003)”

## Run cost

- runs: 5
- requests: 72
- cache_hits: 295
- input_tokens: 1476625
- output_tokens: 596781
- rate_limited: 0
- retries: 0
- repairs: 0
- truncations: 15
- wall_s: 1394.5
