# CellWiki semantic evaluation set

This fixed set covers six public-access single-cell papers and six QA cases,
including multi-source context, citation locators, semantic lint and one
deliberately unanswerable request. The JSON stores concise human-authored
paraphrases only; it does not redistribute article text.

Primary source pages:

- [Zheng et al., 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5241818/)
- [Villani et al., 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5775029/)
- [Tabula Muris Consortium, 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC6642641/)
- [Functional CRISPR dissection of human Treg identity](https://pmc.ncbi.nlm.nih.gov/articles/PMC7577958/)
- [Activated Treg/Tconv discrimination](https://pmc.ncbi.nlm.nih.gov/articles/PMC9426617/)
- [SCSA cell-type annotation](https://pmc.ncbi.nlm.nih.gov/articles/PMC7235421/)

`reference_predictions.json` is a gold-reference harness check, not a model
benchmark. Real model runs must write a separate predictions file and are gated
by `thresholds.json`. Memory and external research remain disabled by default
unless an ablation run demonstrates a positive groundedness/recall gain.
