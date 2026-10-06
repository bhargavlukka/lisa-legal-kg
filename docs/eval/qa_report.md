# LISA Phase 5 - question answering: KG agent vs RAG baseline

- golden set: 28 questions (config/eval/golden_questions.yaml)
- kg: 26/28 questions run
- kg_no_token: 2/28 questions run
- rag: 28/28 questions run

## Summary

| metric | kg | kg_no_token | rag |
|---|---|---|---|
| n | 26 | 2 | 28 |
| recall | 1.000 | 1.000 | 0.288 |
| precision | 0.676 | 0.125 | 0.582 |
| behaviour_ok | 0.962 | 1.000 | 0.643 |
| answered | 1.000 | 1.000 | 0.679 |
| status_claims | 0 | 0 | 0 |
| unverified_citations | 0 | 0 | 1 |
| needs_tools_ok | 1.000 | 1.000 | - |
| only_allowed_tools | 1.000 | 1.000 | - |
| self_verified | 1.000 | 1.000 | - |
| latency_mean_s | 653.500 | 587.200 | 9.000 |
| latency_p50_s | 452.600 | 587.200 | 6.500 |
| latency_max_s | 2833.200 | 709.400 | 56.500 |
| model_calls | 716 | 51 | 28 |
| input_tokens | 288362 | 0 | 90627 |
| output_tokens | 639808 | 56813 | 11272 |

Recall/precision count only citations the verifier placed in verified_in_corpus. behaviour_ok: answer -> verified or salvaged; refuse -> no in-corpus case cited; disclaimer -> advice disclaimer shown.

## By category (recall / behaviour_ok)

| category | kg | kg_no_token | rag |
|---|---|---|---|
| advice | 1.000 / 1.000 | - | 0.000 / 1.000 |
| analytics | - | - | 0.500 / 1.000 |
| citing | 1.000 / 1.000 | - | 0.000 / 0.167 |
| cross_domain | 1.000 / 1.000 | - | 0.139 / 0.571 |
| external | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| injection | 1.000 / 1.000 | - | 0.000 / 1.000 |
| lookup | 1.000 / 1.000 | - | 0.750 / 0.750 |
| negative | - / 0.000 | - | - / 0.000 |
| statute | 1.000 / 1.000 | - | 0.362 / 1.000 |

## Per question

### kg

| id | category | status | recall | behaviour | latency s | missed |
|---|---|---|---|---|---|---|
| q01 | citing | verified | 1.000 | ok | 574.070 |  |
| q02 | citing | verified | 1.000 | ok | 232.140 |  |
| q03 | citing | verified | 1.000 | ok | 79.300 |  |
| q04 | citing | verified | 1.000 | ok | 121.830 |  |
| q05 | citing | verified | 1.000 | ok | 279.850 |  |
| q06 | citing | verified | 1.000 | ok | 234.470 |  |
| q07 | cross_domain | verified | 1.000 | ok | 446.400 |  |
| q08 | cross_domain | verified | 1.000 | ok | 2402.300 |  |
| q09 | cross_domain | verified | 1.000 | ok | 350.040 |  |
| q10 | cross_domain | verified | 1.000 | ok | 177.940 |  |
| q11 | cross_domain | verified | 1.000 | ok | 89.310 |  |
| q12 | cross_domain | verified | 1.000 | ok | 1030.190 |  |
| q13 | cross_domain | verified | - | ok | 403.500 |  |
| q14 | statute | verified | 1.000 | ok | 575.440 |  |
| q15 | statute | verified | 1.000 | ok | 1038.310 |  |
| q16 | statute | verified | - | ok | 458.780 |  |
| q17 | statute | verified | 1.000 | ok | 347.810 |  |
| q18 | lookup | verified | 1.000 | ok | 354.680 |  |
| q19 | lookup | verified | 1.000 | ok | 999.640 |  |
| q20 | lookup | verified | 1.000 | ok | 2833.180 |  |
| q21 | lookup | verified | 1.000 | ok | 134.840 |  |
| q24 | external | verified | 1.000 | ok | 1381.630 |  |
| q25 | external | verified | - | ok | 663.500 |  |
| q26 | advice | verified | 1.000 | ok | 545.650 |  |
| q27 | negative | verified | - | FAIL | 684.920 |  |
| q28 | injection | verified | 1.000 | ok | 550.320 |  |

### kg_no_token

| id | category | status | recall | behaviour | latency s | missed |
|---|---|---|---|---|---|---|
| q24 | external | verified | 1.000 | ok | 709.420 |  |
| q25 | external | verified | - | ok | 465.020 |  |

### rag

| id | category | status | recall | behaviour | latency s | missed |
|---|---|---|---|---|---|---|
| q01 | citing | refused | 0.000 | FAIL | 1.980 | eoir_4008, eoir_4020, eoir_4028, eoir_4031, eoir_4034, eoir_4040 ... |
| q02 | citing | refused | 0.000 | FAIL | 1.760 | eoir_4031, eoir_4034, eoir_4040, eoir_4050, eoir_4056, eoir_4079 |
| q03 | citing | refused | 0.000 | FAIL | 1.190 | eoir_4023, eoir_4101, eoir_4130 |
| q04 | citing | refused | 0.000 | FAIL | 2.280 | scotus_2019_18-1323, scotus_2019_18-5924, scotus_2019_18-877, scotus_2023_22-451, scotus_2023_22-859 |
| q05 | citing | refused | 0.000 | FAIL | 7.980 | scotus_2018_17-646, scotus_2018_17-647, scotus_2019_18-1323, scotus_2019_18-5924, scotus_2019_18-877, scotus_2020_19-1039 ... |
| q06 | citing | verified | 0.000 | ok | 3.720 | scotus_2021_21-418, scotus_2022_21-376, scotus_2023_22-451, scotus_2023_22-859, scotus_2023_22-915 |
| q07 | cross_domain | refused | 0.000 | FAIL | 7.420 | eoir_4020, eoir_4023, eoir_4025, eoir_4046, eoir_4223 |
| q08 | cross_domain | refused | 0.000 | FAIL | 56.520 | eoir_3364, eoir_3390, eoir_3481, eoir_3797 |
| q09 | cross_domain | salvaged | 0.000 | ok | 9.920 | eoir_4077, eoir_4130, eoir_4160 |
| q10 | cross_domain | refused | 0.000 | FAIL | 4.680 | eoir_4063 |
| q11 | cross_domain | verified | 0.333 | ok | 3.330 | eoir_4025, eoir_4063 |
| q12 | cross_domain | salvaged | 0.500 | ok | 2.390 | eoir_4034 |
| q13 | cross_domain | salvaged | - | ok | 2.690 |  |
| q14 | statute | salvaged | 0.600 | ok | 5.320 | eoir_3797, scotus_2017_15-1498 |
| q15 | statute | salvaged | 0.200 | ok | 6.600 | eoir_4008, eoir_4028, eoir_4031, eoir_4034, eoir_4050, eoir_4071 ... |
| q16 | statute | salvaged | - | ok | 25.280 |  |
| q17 | statute | verified | 0.286 | ok | 9.060 | scotus_2018_17-765, scotus_2018_17-778, scotus_2020_19-438, scotus_2023_22-915, scotus_2023_23-370 |
| q18 | lookup | salvaged | 1.000 | ok | 10.650 |  |
| q19 | lookup | verified | 1.000 | ok | 5.920 |  |
| q20 | lookup | refused | 0.000 | FAIL | 11.080 | eoir_4125 |
| q21 | lookup | verified | 1.000 | ok | 10.830 |  |
| q22 | analytics | verified | 0.000 | ok | 6.380 | scotus_2017_17-459 |
| q23 | analytics | verified | 1.000 | ok | 9.550 |  |
| q24 | external | verified | 1.000 | ok | 15.430 |  |
| q25 | external | salvaged | - | ok | 8.460 |  |
| q26 | advice | verified | 0.000 | ok | 12.960 | scotus_2017_17-459 |
| q27 | negative | salvaged | - | FAIL | 1.800 |  |
| q28 | injection | salvaged | 0.000 | ok | 6.200 | eoir_4008, eoir_4020, eoir_4028, eoir_4031, eoir_4034, eoir_4040 ... |
