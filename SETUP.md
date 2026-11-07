# Run, test and publish: step by step

## 1. Unzip and set up

```bash
unzip content-to-post-agent.zip
cd content-to-post-agent

python3.11 -m venv .venv
source .venv/bin/activate            # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

cp .env.example .env                 # Windows: copy .env.example .env
```

Open `.env` and set `OPENAI_API_KEY=sk-...`.

## 2. Test (offline, free)

```bash
pytest                                                     # expect: 24 passed
python -m agent run --file evals/sample_article.txt --fake # offline demo; type "a" to approve
python evals/run_evals.py --fake --limit 3                 # checks the eval harness
```

## 3. Run for real

```bash
# CLI on a real article
python -m agent run --url https://<any public blog post>

# API
uvicorn api.main:app --reload
# open http://localhost:8000/docs, or use the curl examples in README.md

# Docker
docker compose up --build
```

## 4. Generate real eval results (do this before linking the repo)

```bash
python evals/run_evals.py
```

Then:
1. Open `evals/results.md` and copy the summary numbers into the **Evals** table in `README.md`.
2. Replace the **Sample output** block in `README.md` with output from a real `python -m agent run --url ...`.
3. Fill in the "Numbers to know" section in `docs/INTERVIEW_NOTES.md`.
4. Optional: record a 20-30 second GIF of a CLI run and save it as `docs/demo.gif`.

## 5. Push to a new public GitHub repo

With the GitHub CLI (`gh auth login` once first):

```bash
git init -b main
git add .
git status                       # check that .env is NOT listed
git commit -m "Content-to-Post Agent: LangGraph agent with critique loop, human review, API and evals"
gh repo create glitchvishal/content-to-post-agent --public --source=. --push \
  --description "LangGraph agent that turns articles into reviewed LinkedIn and X posts"
```

Without the GitHub CLI:
1. Create an empty public repo named `content-to-post-agent` at https://github.com/new (no README, no .gitignore, no license; the project already has them).
2. Then:

```bash
git init -b main
git add .
git status                       # check that .env is NOT listed
git commit -m "Content-to-Post Agent: LangGraph agent with critique loop, human review, API and evals"
git remote add origin https://github.com/glitchvishal/content-to-post-agent.git
git push -u origin main
```

After pushing:
- Check the **Actions** tab: the CI workflow should go green (it runs the tests with the fake model, no secrets needed).
- On the repo page, add topics: `langgraph`, `langchain`, `ai-agents`, `llm`, `fastapi`, `human-in-the-loop`.
- If you ever committed a real key by accident, revoke it in the OpenAI dashboard immediately; deleting the commit is not enough.
