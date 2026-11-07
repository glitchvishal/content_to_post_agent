# Eval results

Not generated yet. Run the evals with your OpenAI key to fill this file:

```bash
python evals/run_evals.py
```

This overwrites `evals/results.md` with real scores (and writes the raw data to `evals/results.json`). Then copy the summary numbers into the Evals table in the README.

`python evals/run_evals.py --fake` checks that the harness works offline, but its numbers come from a fake model and say nothing about quality, so don't publish them.
