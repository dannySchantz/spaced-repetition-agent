# Grader evaluation

`python evals/run_grader_eval.py` runs 63 labeled, human-reviewable cases offline.
This checks fixture/schema/application contracts, **not live semantic accuracy**.
The labels are an initial engineering dataset and need independent owner review.
Cases span linear algebra, operating systems, biology, economics and computing.
Development and held-out splits are fixed in the data. Keep the held-out split out
of prompt tuning. Every must-fail error must avoid a false Right; clearly gradable
cases target 95% agreement. Inspect every probe for leakage and every disagreement.

After explicit spending authorization and API setup:
`python evals/run_grader_eval.py --live --model YOUR_MODEL --split all --output evals/live-result.json`
This command makes paid calls; it has not been run during implementation.
Only enable automatic live grading after the numeric gate passes and a human has
reviewed the full report. Compare candidate models using token usage and current rates;
no cheapest-model claim is possible until live evaluation is authorized.

Responses implementation reference:
https://developers.openai.com/api/docs/guides/structured-outputs
