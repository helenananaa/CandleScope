# Contributing to CandleScope

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Before you start

- Search [open issues](https://github.com/helenananaa/CandleScope/issues) first.
  Planned work after the first release is tracked under the `post-launch` label.
- For a bug, include your platform, how you run CandleScope (browser version,
  desktop app or from source), the exchange and symbol, and the steps that
  reproduce it.
- For a larger change, open an issue to agree on the approach before writing
  the code.
- Pyne is retired and is not coming back. See [AGENTS.md](AGENTS.md) for the
  development policy.

## Development setup

Follow [Quick start → From source](README.md#from-source) to run the backend and
the frontend.

## Tests

Use focused tests while editing, and keep complete regression as a separate step:

```bash
cd frontend
npm run test:dev -- manual-history
npm run test:dev -- drawings --frontend
npm run test:dev -- --changed --list
npm run test:check
npm run test:full
```

`test:dev` reports its scope and deferred integration files. `test:full` includes
all backend, frontend and desktop host tests; add `--packages` for Python package
suites. See the [testing guide](docs/TESTING.md) for selection, bounded
parallelism, complete profiling and evidence paths.

### Backend checks

Use the virtual environment from Quick start. On Windows, replace `python`
below with `.\.venv\Scripts\python.exe`.

```bash
cd backend
python -m pip install -r requirements-test.txt
python -m compileall app tests -q
python -m pytest tests -q
```

### Frontend checks

```bash
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## Pull requests

- Keep each pull request to one change, and describe what it changes and how
  you checked it.
- User-facing text goes through the i18n catalogs; follow
  [the copy guidelines](frontend/COPY_GUIDELINES.md).
- By contributing you agree that your work is licensed under
  [GPL-3.0](LICENSE).
