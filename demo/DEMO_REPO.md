# Demo Repository Guide

## Repository
**URL:** `https://github.com/<your-fork>/patcharena-demo`

> Create this repo before the hackathon. It should be a small Flask web app you control.

## App Description
A simple Flask web app that computes pagination for a blog. It has an off-by-one bug: page 1 shows items 1-10 correctly, but page 2 shows items 11-21 (should be 11-20).

## Commands

| Step | Command |
|------|---------|
| Install | `pip install -e ".[test]"` |
| Test | `python -m pytest -x -q --tb=short` |
| Start | `python app.py` |
| Port | `5000` |
| Health | `GET /health` returns `{"status": "ok"}` |

## Issue Description
**Title:** Pagination off-by-one on page 2+
**Number:** `1`
**Body:** When visiting `/posts?page=2`, the page shows 11 items instead of 10. The last item from page 1 appears again at the start of page 2. Expected: each page shows exactly 10 items.

## Reproduction
```
$ curl http://localhost:5000/api/posts?page=2 | python -m json.tool | grep '"id"' | wc -l
11  # should be 10
```

## Expected Fix
The `paginate()` function uses `offset = (page - 1) * per_page + 1` (off by one). Should be `offset = (page - 1) * per_page`.

## Expected Screenshot Description
The app shows exactly 10 post items per page, with no duplicates between pages. Page 2 starts with "Post #11".

## Strategy Expected Behavior
- **minimal**: Fix the one arithmetic line in `paginate()`.
- **rootcause**: Fix `paginate()` and update the comment explaining the formula.
- **testfirst**: First adds `test_page_two_has_ten_items` to `tests/test_pagination.py`, then fixes.
- **defensive**: Fix `paginate()`, add assertion that `per_page > 0` and `page >= 1`.

## Pass Rate Target
At least 2 of 3 candidates should pass at least 8 out of 10 dry runs.

## Rehearsal Checklist
- [ ] Repo cloned fresh from GitHub takes < 30s to install
- [ ] Test suite runs in < 20s
- [ ] Bug is reproducible (baseline fails) every time
- [ ] All 3 strategies produce different diffs
- [ ] App boots on port 5000 and serves `/health` within 5s
