# CUAD fixture attribution

The PDFs in this directory are 6 contracts from the **Contract Understanding
Atticus Dataset (CUAD v1)**, curated by The Atticus Project, Inc., and used
here as source documents for golden eval records (`evals/golden/`).

CUAD v1 is licensed under the **Creative Commons Attribution 4.0 International
License (CC BY 4.0)**: <https://creativecommons.org/licenses/by/4.0/>.

- Dataset: <https://www.atticusprojectai.org/cuad>
- Paper: Hendrycks et al., "CUAD: An Expert-Annotated NLP Dataset for Legal
  Contract Review", NeurIPS 2021 (<https://arxiv.org/abs/2103.06268>)
- Mirrored from: <https://huggingface.co/datasets/theatticusproject/cuad>

Files were selected from `master_clauses.csv` for small size and clause
coverage: these are among the highest-coverage contracts in the dataset, each
annotated for all 41 CUAD clause types, and together the six span six
different agreement categories (the CUAD category folder each file sits in).
Contracts whose text cannot be extracted with pdfplumber are swapped out
rather than repaired. File names are the original CUAD names and key into
`master_clauses.csv` rows.

| File (CUAD name) | Agreement category | Clause types annotated |
| --- | --- | --- |
| DataCallTechnologies_20060918_SB-2A_EX-10.9_944510_EX-10.9_Content License Agreement.pdf | Content License | 41 |
| EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement Agreement.pdf | Endorsement | 41 |
| EmeraldHealthBioceuticalsInc_20200218_1-A_EX1A-6 MAT CTRCT_11987205_EX1A-6 MAT CTRCT_Development Agreement.pdf | Development | 41 |
| VertexEnergyInc_20200113_8-K_EX-10.1_11943624_EX-10.1_Marketing Agreement.pdf | Marketing | 41 |
| AgapeAtpCorp_20191202_10-KA_EX-10.1_11911128_EX-10.1_Supply Agreement.pdf | Supply | 41 |
| WaterNowInc_20191120_10-Q_EX-10.12_11900227_EX-10.12_Distributor Agreement.pdf | Distributor | 41 |

SPDX-License-Identifier: CC-BY-4.0
