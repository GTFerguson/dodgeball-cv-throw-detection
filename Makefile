# The commands the README quotes, in one place.
PY := .venv/bin/python
CLIP ?= data/footage/wdbf2014_final_h2_set2.mp4
STEM := $(basename $(notdir $(CLIP)))

.PHONY: test lint run evaluate stress ablate budget tactics design

test:            ## every suite; stops at the first failure
	@for t in scripts/test_*.py; do $(PY) "$$t" -q >/dev/null 2>&1 || { echo "FAIL $$t"; $(PY) "$$t"; exit 1; }; echo "ok   $$t"; done

lint:            ## ruff, if installed
	@$(PY) -m ruff check src scripts 2>/dev/null || echo "ruff not installed: .venv/bin/pip install ruff"

run:             ## footage in, timeline and metric out (CLIP=data/footage/x.mp4)
	$(PY) scripts/run.py $(CLIP)

evaluate:        ## score the timeline against the labels
	$(PY) scripts/evaluate.py $(STEM)

stress:          ## the three degraded copies of the clip
	$(PY) scripts/stress.py 480p crf40 drop2

ablate:          ## the cascade with later stages withheld
	$(PY) scripts/ablate.py $(STEM)

budget:          ## efficiency error by source
	$(PY) scripts/error_budget.py $(STEM) --json output/error_budget.json

tactics:         ## efficiency by set-up, predicted and truth
	$(PY) scripts/tactics.py $(STEM) && $(PY) scripts/tactics.py $(STEM) --truth

design:          ## docs/design.tex -> docs/design.pdf (twice, for the contents)
	@mkdir -p .build
	pdflatex -interaction=nonstopmode -halt-on-error -output-directory=.build docs/design.tex >/dev/null
	pdflatex -interaction=nonstopmode -halt-on-error -output-directory=.build docs/design.tex >/dev/null
	@cp .build/design.pdf docs/design.pdf && echo "docs/design.pdf"
